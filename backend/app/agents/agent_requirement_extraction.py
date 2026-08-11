"""
Requirement Extraction Agent
——————————————————————————————
Node: req_extraction
Input:  Jira story (summary, description, ACs, technical notes)
Output: ExtractedRequirements — 6 structured requirement categories
LLM:    GPT-5 (falls back to gpt-4o if GPT-5 not available on account)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.agents.models.requirement_models import (
    AcceptanceCriterion,
    ApiRequirement,
    BusinessRule,
    ExtractedRequirements,
    FunctionalRequirement,
    PerformanceRequirement,
    UiRequirement,
)
from app.agents.state import ReviewState
from app.core.logging import get_logger

log = get_logger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a Principal Business Analyst and Requirements Engineer with 15 years of experience.
Your task is to extract and structure ALL requirements from a Jira story into 6 clearly defined categories.

## Categories

1. **functionalRequirements** — What the system must DO.
   - Format: { "id": "FR-01", "title": "...", "description": "...", "priority": "must|should|could", "source": "jira|inferred", "testable": true }

2. **acceptanceCriteria** — Specific conditions for accepting the feature (Gherkin-style when possible).
   - Format: { "id": "AC-01", "given": "...", "when": "...", "then": "...", "description": "...", "priority": "must" }

3. **businessRules** — Constraints, policies, and domain rules the implementation must respect.
   - Format: { "id": "BR-01", "description": "...", "rationale": "...", "impact": "high|medium|low" }

4. **apiRequirements** — REST/GraphQL endpoint contracts implied or stated in the story.
   - Format: { "id": "API-01", "method": "GET|POST|...", "endpoint": "/api/...", "description": "...", "request": "...", "response": "...", "auth": "required|optional|none" }

5. **uiRequirements** — Frontend/UX requirements for Angular components, forms, or user interactions.
   - Format: { "id": "UI-01", "component": "...", "description": "...", "user_action": "...", "system_response": "..." }

6. **performanceRequirements** — SLAs, response time targets, throughput constraints.
   - Format: { "id": "PERF-01", "description": "...", "metric": "...", "threshold": "...", "scope": "api|db|ui|background" }

## Rules
- If a category is not applicable, return an empty array — do NOT omit the key.
- Derive implicit requirements from context (e.g. if a login form is mentioned, auth is required).
- Assign sequential IDs: FR-01, FR-02 ... within each category.
- Priority: "must" = required for MVP, "should" = important but deferrable, "could" = nice-to-have.
- confidence_score: 0.0–1.0 reflecting how clearly the story specifies the requirements.
- extraction_notes: mention any ambiguities, missing information, or assumptions made.

## Output Format
Return ONLY a single valid JSON object. No markdown, no explanation:

{
  "jira_key": "PROJ-123",
  "functionalRequirements": [...],
  "acceptanceCriteria": [...],
  "businessRules": [...],
  "apiRequirements": [...],
  "uiRequirements": [...],
  "performanceRequirements": [...],
  "extraction_notes": "...",
  "confidence_score": 0.85
}
""".strip()


# ── LangGraph Node Function ───────────────────────────────────────────────────

async def req_extraction_node(state: ReviewState) -> dict:
    """
    LangGraph node — extracts structured requirements from Jira context.
    Designed to be registered as a node in ReviewWorkflow's StateGraph.
    """
    agent = RequirementExtractionAgent(state)  # state used as settings fallback here
    return await agent.run(state)


# ── Agent Implementation ──────────────────────────────────────────────────────

class RequirementExtractionAgent(BaseAgent):
    name     = "req_extraction"
    category = "requirement"

    def _get_llm(self, temperature: float = 0.05):
        return super()._get_llm(temperature=temperature, json_mode=True)

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        jira = self._jira_context(state)

        if not jira:
            msg = "No Jira context available — requirement extraction skipped."
            logs.append(self._make_log(msg, "warning"))
            log.warning("agent.req_extraction.no_jira", review_id=self._review_id)
            return {
                "requirements": [],
                "logs":         logs,
                "current_agent": self.name,
                "progress_percent": 26,
            }

        user_prompt = self._build_user_prompt(jira)
        log.info("agent.req_extraction.start", review_id=self._review_id, jira_key=jira.get("jira_key"))

        try:
            raw_json = await self._invoke_llm_json(SYSTEM_PROMPT, user_prompt)
            extracted = self._parse_and_validate(raw_json, jira.get("jira_key", ""))
            flat_requirements = self._flatten_to_requirement_list(extracted)

            logs.append(self._make_log(
                f"Extracted {extracted.total_requirements} requirements "
                f"(confidence: {extracted.confidence_score:.0%}) from {jira.get('jira_key')}."
            ))

            if extracted.extraction_notes:
                logs.append(self._make_log(f"Notes: {extracted.extraction_notes}", "warning"))

            log.info(
                "agent.req_extraction.complete",
                review_id=self._review_id,
                total=extracted.total_requirements,
                confidence=extracted.confidence_score,
            )

            return {
                "requirements":       flat_requirements,
                "extracted_requirements": extracted.model_dump(),  # full structured output
                "logs":               logs,
                "current_agent":      self.name,
                "progress_percent":   26,
            }

        except Exception as exc:
            log.error("agent.req_extraction.failed", review_id=self._review_id, error=str(exc))
            logs.append(self._make_log(f"Requirement extraction failed: {exc}", "error"))
            errors = {**(state.get("agent_errors") or {}), self.name: str(exc)}
            return {
                "requirements":   [],
                "logs":           logs,
                "agent_errors":   errors,
                "current_agent":  self.name,
                "progress_percent": 26,
            }

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_user_prompt(self, jira: dict) -> str:
        acs = jira.get("acceptance_criteria", [])
        ac_block = "\n".join(f"  - {ac}" for ac in acs) if acs else "  (none provided)"

        return f"""## Jira Story: {jira.get('jira_key', 'UNKNOWN')}

### Summary
{jira.get('summary', '(no summary)')}

### Issue Type
{jira.get('issue_type', 'Story')}  |  Priority: {jira.get('priority', 'Medium')}  |  Status: {jira.get('status', 'In Progress')}

### Description
{jira.get('description', '(no description provided)')[:4000]}

### Acceptance Criteria (from Jira)
{ac_block}

### Technical Notes
{jira.get('technical_notes', '(none)')}

### Labels
{', '.join(jira.get('labels', [])) or '(none)'}

### Story Points
{jira.get('story_points') or 'unestimated'}

---
Extract ALL requirements. Derive implicit ones from context.
jira_key must be exactly: {jira.get('jira_key', 'UNKNOWN')}"""

    # ── Parser & validator ────────────────────────────────────────────────────

    def _parse_and_validate(self, raw: dict, jira_key: str) -> ExtractedRequirements:
        """Normalise LLM output keys and validate with Pydantic."""
        # Handle camelCase vs snake_case from LLM
        normalised = {
            "jira_key":                jira_key,
            "functional_requirements": raw.get("functionalRequirements", raw.get("functional_requirements", [])),
            "acceptance_criteria":     raw.get("acceptanceCriteria",     raw.get("acceptance_criteria", [])),
            "business_rules":          raw.get("businessRules",          raw.get("business_rules", [])),
            "api_requirements":        raw.get("apiRequirements",         raw.get("api_requirements", [])),
            "ui_requirements":         raw.get("uiRequirements",          raw.get("ui_requirements", [])),
            "performance_requirements": raw.get("performanceRequirements", raw.get("performance_requirements", [])),
            "extraction_notes":        raw.get("extraction_notes", ""),
            "confidence_score":        float(raw.get("confidence_score", 0.7)),
        }
        try:
            return ExtractedRequirements.model_validate(normalised)
        except ValidationError as e:
            log.warning("agent.req_extraction.validation_partial", errors=str(e))
            # Return partial result rather than failing completely
            return self._build_partial_result(normalised, jira_key)

    def _build_partial_result(self, data: dict, jira_key: str) -> ExtractedRequirements:
        """Best-effort construction when Pydantic validation partially fails."""
        def safe_list(items: list, model) -> list:
            result = []
            for item in items:
                try:
                    result.append(model.model_validate(item))
                except Exception:
                    pass
            return result

        return ExtractedRequirements(
            jira_key=jira_key,
            functional_requirements=safe_list(data.get("functional_requirements", []), FunctionalRequirement),
            acceptance_criteria=safe_list(data.get("acceptance_criteria", []),     AcceptanceCriterion),
            business_rules=safe_list(data.get("business_rules", []),               BusinessRule),
            api_requirements=safe_list(data.get("api_requirements", []),           ApiRequirement),
            ui_requirements=safe_list(data.get("ui_requirements", []),             UiRequirement),
            performance_requirements=safe_list(data.get("performance_requirements", []), PerformanceRequirement),
            extraction_notes=data.get("extraction_notes", "Partial extraction due to validation errors."),
            confidence_score=data.get("confidence_score", 0.5),
        )

    # ── Flatten to simple dicts for state storage ─────────────────────────────

    @staticmethod
    def _flatten_to_requirement_list(extracted: ExtractedRequirements) -> list[dict]:
        """
        Produces the flat list stored in ReviewState.requirements
        and used by the Requirement Validation Agent.
        """
        flat: list[dict] = []

        for r in extracted.functional_requirements:
            flat.append({"id": r.id, "type": "functional", "description": r.description,
                         "priority": r.priority, "testable": r.testable})

        for r in extracted.acceptance_criteria:
            flat.append({"id": r.id, "type": "acceptance_criterion",
                         "description": r.description, "priority": r.priority,
                         "given": r.given, "when": r.when, "then": r.then})

        for r in extracted.business_rules:
            flat.append({"id": r.id, "type": "business_rule",
                         "description": r.description, "impact": r.impact})

        for r in extracted.api_requirements:
            flat.append({"id": r.id, "type": "api",
                         "description": r.description,
                         "method": r.method, "endpoint": r.endpoint})

        for r in extracted.ui_requirements:
            flat.append({"id": r.id, "type": "ui",
                         "description": r.description, "component": r.component})

        for r in extracted.performance_requirements:
            flat.append({"id": r.id, "type": "performance",
                         "description": r.description,
                         "metric": r.metric, "threshold": r.threshold})

        return flat
