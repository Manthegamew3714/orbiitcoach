"""Data assembly for weekly plan generation — no LLM call.

Assembles 10+ data sources into a structured text prompt consumed by the
plan generation template. Demonstrates the pattern of separating data
collection from LLM interaction.

Note: This is a condensed version showing the architectural pattern.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


class UltimatePromptBuilder:
    """Assembles the complete weekly plan generation brief from user data.

    The key design decision: this class does NO LLM calls. It purely
    transforms and assembles data from multiple sources (profile, planner,
    resources, memory, market research, etc.) into a structured prompt
    that another template consumes.

    This separation means:
    - Data assembly is testable without mocking LLM calls
    - Token budget is managed before the expensive API call
    - Each data source can be independently updated or replaced
    """

    version = "1.0.0"
    TOKEN_BUDGET = 4000  # Target input tokens for the downstream model

    def build(
        self,
        user_data: dict,
        gap_report: Optional[dict] = None,
        research: Optional[dict] = None,
        question_responses: Optional[dict] = None,
        week_start: Optional[str] = None,
    ) -> str:
        """Build the complete prompt from all data sources.

        Args:
            user_data: Aggregated user snapshot from data collector.
            gap_report: Output from gap analysis template (optional).
            research: Output from research analysis template (optional).
            question_responses: User's pre-weekly check-in answers (optional).
            week_start: ISO date for the week start (defaults to next Monday).

        Returns:
            Complete prompt string ready for plan generation.
        """
        profile = user_data.get("profile", {})
        planner = user_data.get("planner", {})
        done_tasks = user_data.get("done_tasks", [])
        resources = user_data.get("resources", [])
        memory = user_data.get("memory", [])

        if not week_start:
            today = datetime.now(timezone.utc)
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            monday = today + timedelta(days=days_until_monday)
            week_start = monday.strftime("%Y-%m-%d")
            week_end = (monday + timedelta(days=6)).strftime("%Y-%m-%d")
        else:
            ws = datetime.fromisoformat(week_start)
            week_end = (ws + timedelta(days=6)).strftime("%Y-%m-%d")

        # Assemble all sections — each method handles one data source
        sections = [
            f"# WEEKLY PLAN GENERATION BRIEF\n"
            f"## Week of: {week_start} — {week_end}\n\n---",
            self._section_profile(profile),
            self._section_config(profile),
            self._section_prev_performance(planner, done_tasks),
            self._section_checkin_responses(question_responses),
            self._section_resources(resources),
            self._section_skills(profile),
            self._section_gaps(gap_report),
            self._section_proposed(research),
            self._section_roadmap(profile),
            self._section_market(research),
            self._section_insights(memory),
            self._section_done_history(done_tasks),
        ]

        return "\n\n".join(s for s in sections if s)

    # --- Section builders (each handles one data source) ---

    def _section_profile(self, profile: dict) -> str:
        """Extract user identity — role, target, location, timeline."""
        career_goals = profile.get("career_goals", {})
        work_history = profile.get("work_history", [])

        current_role = "Not set"
        if isinstance(work_history, list) and work_history:
            latest = work_history[0]
            current_role = f"{latest.get('role', '?')} at {latest.get('company', '?')}"

        target_role = career_goals.get("target_role", "Not set")
        timeline = career_goals.get("timeline", "N/A")

        return (
            f"## 1. USER PROFILE\n"
            f"Current Role: {current_role}\n"
            f"Target Role: {target_role}\n"
            f"Timeline: {timeline}"
        )

    def _section_config(self, profile: dict) -> str:
        """Extract time budget and availability configuration."""
        config = profile.get("user_config", {})
        time_budget = config.get("time_budget", {})
        total = float(time_budget.get("total_weekly_hours", 0))

        categories = time_budget.get("categories", {})
        learning = float(categories.get("learning", 0))
        projects = float(categories.get("projects", 0))
        job_hunting = float(categories.get("job_hunting", 0))

        return (
            f"## 2. TIME BUDGET\n"
            f"Total: {total}h/week\n"
            f"Split: Learning {learning}% | Projects {projects}% | "
            f"Job Search {job_hunting}%"
        )

    def _section_prev_performance(self, planner: dict, done_tasks: list) -> str:
        """Analyze previous week's task completion for feedback loop."""
        prev = planner.get("previous_week", {})
        total = prev.get("total_tasks", 0)
        completed = prev.get("completed", 0)
        rate = (completed / total * 100) if total > 0 else 0

        return (
            f"## 3. PREVIOUS WEEK PERFORMANCE\n"
            f"Tasks: {completed}/{total} completed ({rate:.0f}%)\n"
            f"Completed items: {', '.join(t.get('title', '?') for t in done_tasks[:5])}"
        )

    def _section_resources(self, resources: list) -> str:
        """List active learning resources and progress."""
        if not resources:
            return ""

        items = []
        for r in resources[:10]:
            progress = r.get("progress", 0)
            items.append(f"- {r.get('title', '?')} ({progress}% complete)")

        return f"## 5. ACTIVE RESOURCES\n" + "\n".join(items)

    def _section_insights(self, memory: list) -> str:
        """Surface relevant insights from long-term memory."""
        if not memory:
            return ""

        items = [f"- {m.get('content', '?')}" for m in memory[:8]]
        return f"## 10. INSIGHTS FROM MEMORY\n" + "\n".join(items)

    def _section_done_history(self, done_tasks: list) -> str:
        """4-week trend of completed tasks for pattern recognition."""
        if not done_tasks:
            return ""

        return (
            f"## 11. COMPLETION HISTORY (4 weeks)\n"
            f"Total completed: {len(done_tasks)} tasks"
        )

    # Additional section methods follow the same pattern:
    # _section_checkin_responses, _section_skills, _section_gaps,
    # _section_proposed, _section_roadmap, _section_market
    # Each extracts and formats data from its respective source.
