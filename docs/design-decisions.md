# Design Decisions

Key technical decisions made while building OrbiitCoach, with rationale and trade-offs.

## 1. Serverless over Containers

**Choice:** AWS Lambda + API Gateway over ECS/EKS

**Why:**
- Zero idle cost — I pay only when users interact with the system
- No infrastructure management — no patching, no scaling decisions, no container orchestration
- Natural fit for event-driven patterns (Step Functions, EventBridge triggers)
- As a solo builder, operational simplicity matters more than fine-grained control

**Trade-off:** Cold starts add ~300ms on first invocation. Acceptable for a coaching tool where users aren't expecting sub-100ms responses.

## 2. Multi-Model AI Strategy

**Choice:** 3 different Claude models for different tasks

**Why:**
- **Opus 4.6** (~45s, highest cost): Used only for weekly plan generation where the model needs to synthesise 10+ data sources into a coherent strategy. The quality difference is noticeable.
- **Sonnet 4.5** (~2s, moderate cost): Core coaching conversations and tool orchestration. Good balance of quality and speed.
- **Haiku 4.5** (~200ms, lowest cost): Fast classification, fact extraction, structured parsing. Tasks where speed matters and deep reasoning doesn't.

A single-model approach would either be too expensive (Opus for everything) or too shallow (Haiku for everything).

**Trade-off:** More complex model management, but the cost savings and quality improvements justify it. A weekly plan that uses Opus costs roughly the same as the equivalent Haiku calls for simple classification.

## 3. Function Calling over Text Parsing

**Choice:** AWS Bedrock Converse API with JSON schema enforcement

**Why:**
- Schema-enforced structured output eliminates brittle regex/JSON parsing
- The model is forced to respond in the exact shape I define
- Validation can be added at the schema level
- Retry with self-correction: if output fails validation, the error is appended to the prompt and the model self-corrects

**Trade-off:** Tied to Converse API format (AWS-specific), but the reliability improvement over parsing ````json ... ```` blocks is dramatic.

## 4. Step Functions over In-Lambda Orchestration

**Choice:** AWS Step Functions state machines for multi-step AI pipelines

**Why:**
- Visual debugging — I can see exactly which step failed and why
- Built-in retry and error handling per step
- Timeout handling (critical for Opus calls that can take 60s+)
- Each step is an independent Lambda invocation with its own timeout and memory
- Step-level CloudWatch metrics for free

**Trade-off:** More infrastructure to define in SAM template, slower cold-start for the overall pipeline. But for a 4-step pipeline where each step takes 10-45 seconds, the orchestration overhead is negligible.

## 5. DynamoDB over RDS

**Choice:** DynamoDB (NoSQL) for all data storage

**Why:**
- Serverless-native: no connection pooling headaches in Lambda (a notorious RDS+Lambda pain point)
- Pay-per-request pricing matches the usage pattern
- Single-digit millisecond latency at any scale
- GSIs handle the access patterns cleanly
- No database server to manage, patch, or right-size

**Trade-off:** No relational joins — I denormalise data and use GSIs. For this application, the access patterns are well-defined (always query by user_id + sort key), so the NoSQL model fits naturally.

## 6. Prompt Templates over Ad-Hoc Strings

**Choice:** Abstract base class pattern for all LLM prompts

**Why:**
- Every prompt has a consistent contract: system prompt, user prompt, tool schema, validation
- Prompts are versioned — I can A/B test prompt changes
- Input/output validation catches issues before/after LLM calls
- Prompts are testable in isolation (no mocking needed for the template itself)
- New team members (or future-me) can add prompts by extending the base class

**Trade-off:** More boilerplate than a simple f-string. But with 6+ prompt types in production, the consistency pays off immediately.

## 7. Shared Lambda Layer over Per-Function Dependencies

**Choice:** AWS Lambda Layer for shared code (Bedrock client, auth, prompts)

**Why:**
- Single source of truth for shared logic (Bedrock client, auth utilities, prompt templates)
- Reduces deployment package size for each function
- Changes to shared code propagate to all functions on next deploy

**Trade-off:** Layer updates require redeploying all dependent functions. SAM handles this automatically via CloudFormation.

## 8. Infrastructure as Code (Everything)

**Choice:** AWS SAM template defines the entire stack — no console-created resources

**Why:**
- Reproducible: I can tear down and recreate the entire system from one command
- Version controlled: infrastructure changes go through the same PR process as code
- Self-documenting: the SAM template IS the architecture documentation
- No configuration drift between environments

**Trade-off:** Steeper initial learning curve, and some AWS features are easier to configure in the console. But the confidence of `sam deploy` knowing exactly what will change is worth it.
