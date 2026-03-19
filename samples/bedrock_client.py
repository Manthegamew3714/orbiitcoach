"""AWS Bedrock Converse API wrapper with native function calling.

Provides structured LLM interactions using Claude's tool use capabilities.
Replaces regex-based JSON parsing with schema-enforced responses.
"""
import json
import logging
import time
from typing import Any, Optional

import boto3

logger = logging.getLogger(__name__)


class BedrockConverseClient:
    """Wrapper around AWS Bedrock Converse API with function calling.

    Uses Claude's native tool use to enforce structured outputs via JSON schema,
    eliminating the need for brittle regex-based response parsing.
    """

    def __init__(self, region: str = None):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=region or "us-east-1",
        )

    def call_with_tool_use(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        output_schema: dict,
        model_id: str = "anthropic.claude-sonnet-4-5-20250929-v1:0",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict:
        """Call Bedrock Converse API with a tool use schema and return structured output.

        The key insight: by defining a tool with a JSON schema and forcing the model
        to call it (toolChoice: tool), we get guaranteed structured output without
        parsing free-form text. The model's "tool input" IS our structured response.

        Args:
            system_prompt: System instructions for the model.
            user_prompt: User message content.
            tool_name: Name of the tool/function to call.
            tool_description: Description of what the tool does.
            output_schema: JSON schema for the tool's input (= model's structured output).
            model_id: Bedrock model ID.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            Dictionary with 'result' (parsed tool input), 'usage' (token counts),
            'duration_ms', and 'model_id'.

        Raises:
            ValueError: If model doesn't return a tool use block.
        """
        start = time.monotonic()

        tool_config = {
            "tools": [{
                "toolSpec": {
                    "name": tool_name,
                    "description": tool_description,
                    "inputSchema": {"json": output_schema},
                }
            }],
            "toolChoice": {"tool": {"name": tool_name}},
        }

        try:
            response = self.client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                system=[{"text": system_prompt}],
                toolConfig=tool_config,
                inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(json.dumps({
                "step": "bedrock_converse",
                "status": "error",
                "model_id": model_id,
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "error": str(e),
            }))
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        usage = response.get("usage", {})

        # Extract the tool use result from the response
        output_message = response.get("output", {}).get("message", {})
        for block in output_message.get("content", []):
            if "toolUse" in block:
                result = block["toolUse"]["input"]
                logger.info(json.dumps({
                    "step": "bedrock_converse",
                    "status": "success",
                    "model_id": model_id,
                    "tool_name": tool_name,
                    "duration_ms": duration_ms,
                    "input_tokens": usage.get("inputTokens", 0),
                    "output_tokens": usage.get("outputTokens", 0),
                }))
                return {
                    "result": result,
                    "usage": {
                        "input_tokens": usage.get("inputTokens", 0),
                        "output_tokens": usage.get("outputTokens", 0),
                    },
                    "duration_ms": duration_ms,
                    "model_id": model_id,
                }

        # No tool use block — model responded with text instead
        text_content = ""
        for block in output_message.get("content", []):
            if "text" in block:
                text_content = block["text"]
        raise ValueError(
            f"Model did not return tool use block. Text response: {text_content[:500]}"
        )

    def call_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        output_schema: dict,
        validate_fn=None,
        **kwargs,
    ) -> dict:
        """Call with tool use and retry once on validation failure.

        Implements a single-retry pattern: if the model's structured output fails
        validation, we append the error message to the prompt and retry. This
        leverages the model's ability to self-correct when given specific feedback.

        Args:
            validate_fn: Optional callable that takes the result dict and raises
                         ValueError if validation fails.
            **kwargs: Passed to call_with_tool_use.

        Returns:
            Validated result dictionary.
        """
        result = self.call_with_tool_use(
            system_prompt, user_prompt, tool_name, tool_description,
            output_schema, **kwargs
        )

        if validate_fn:
            try:
                validate_fn(result["result"])
            except (ValueError, KeyError, TypeError) as validation_error:
                logger.warning(json.dumps({
                    "step": "bedrock_converse_retry",
                    "status": "validation_failed",
                    "tool_name": tool_name,
                    "error": str(validation_error),
                }))
                correction = (
                    f"{user_prompt}\n\n"
                    f"IMPORTANT CORRECTION: Your previous response had validation "
                    f"issues: {validation_error}. Please fix and try again."
                )
                result = self.call_with_tool_use(
                    system_prompt, correction, tool_name, tool_description,
                    output_schema, **kwargs
                )
                if validate_fn:
                    validate_fn(result["result"])

        return result
