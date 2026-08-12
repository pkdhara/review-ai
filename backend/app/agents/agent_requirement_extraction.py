"""
Requirement Extraction Agent
─────────────────────────────
Node: req_extraction
Input:  Jira story (summary, description, ACs, technical notes)
Output: ExtractedRequirements — structured explicit & inferred requirement categories
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.models.requirement_models import (
    AcceptanceCriterion,
    ApiRequirement,
    BusinessRule,
    ExtractedRequirements,
    FunctionalRequirement,
    PerformanceRequirement,
    RequirementItem,
    RequirementSource,
    RequirementSourceLocation,
    UiRequirement,
)
from app.agents.state import ReviewState
from app.core.logging import get_logger

log = get_logger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a Principal Business Analyst and Requirements Engineer.
Your task is to extract and structure requirements from a Jira issue into two STRICTLY SEPARATE lists:

1. **explicit_requirements**: Requirements EXPLICITLY stated in the Jira Acceptance Criteria section.
   - Assign sequential IDs starting with "AC-": AC-01, AC-02, ...
   - Set source: "explicit"
   - Set source_location: "jira_acceptance_criteria"
   - Set mandatory: true
   - If NO explicit Acceptance Criteria are provided in Jira (e.g., "Acceptance Criteria: None" or empty list), this array MUST BE EMPTY: []. DO NOT invent or fabricate AC IDs!

2. **inferred_requirements**: Useful expectations derived from Jira Summary, Description, Comments, or Technical Notes when explicit ACs are missing or incomplete.
   - Assign sequential IDs starting with "INF-": INF-01, INF-02, ...
   - Set source: "inferred"
   - Set source_location: "jira_summary" | "jira_description" | "jira_comment"
   - Set mandatory: false
   - Set confidence: 0.0 to 1.0 reflecting how clearly the text implies this expectation.
   - DO NOT assign IDs like AC-01, FR-01, or BR-01 to inferred expectations! Inferred expectations MUST use "INF-" namespace IDs!

## Additional Backwards-Compatible Category Arrays (Optional)
You may also categorize requirements into functional_requirements, business_rules, api_requirements, ui_requirements, performance_requirements. However:
- Any requirement derived from Summary/Description without explicit AC must have source: "inferred" and ID: "INF-XX".

## Rules
- NEVER fabricate "AC-01", "FR-01", "BR-01" if the Jira Acceptance Criteria section is empty or specifies "None".
- Never mix explicit_requirements and inferred_requirements into a single list without clear source metadata.
- confidence_score: 0.0–1.0 reflecting overall story clarity.
- extraction_notes: note any ambiguities or missing criteria.

## Output Format
Return ONLY a single valid JSON object:

{
  "jira_key": "PROJ-123",
  "explicit_requirements": [
    {
      "id": "AC-01",
      "title": "...",
      "description": "...",
      "source": "explicit",
      "source_location": "jira_acceptance_criteria",
      "mandatory": true,
      "priority": "must",
      "confidence": 1.0,
      "type": "acceptance_criterion"
    }
  ],
  "inferred_requirements": [
    {
      "id": "INF-01",
      "title": "...",
      "description": "...",
      "source": "inferred",
      "source_location": "jira_description",
      "mandatory": false,
      "priority": "should",
      "confidence": 0.85,
      "type": "functional"
    }
  ],
  "extraction_notes": "...",
  "confidence_score": 0.85
}
""".strip()


# ── LangGraph Node Function ───────────────────────────────────────────────────

async def req_extraction_node(state: ReviewState) -> dict:
    """LangGraph node — extracts structured requirements from Jira context."""
    agent = RequirementExtractionAgent(state)
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
                "explicit_requirements": [],
                "inferred_requirements": [],
                "logs": logs,
                "current_agent": self.name,
                "progress_percent": 26,
            }

        user_prompt = self._build_user_prompt(jira)
        log.info("agent.req_extraction.start", review_id=self._review_id, jira_key=jira.get("jira_key"))

        try:
            raw_json = await self._invoke_llm_json(SYSTEM_PROMPT, user_prompt)
            extracted = self._parse_and_validate(raw_json, jira.get("jira_key", ""))
            flat_requirements = self._flatten_to_requirement_list(extracted)
            explicit_flat = [r for r in flat_requirements if r.get("source") in ("explicit", "jira") or r.get("mandatory") is True]
            inferred_flat = [r for r in flat_requirements if r.get("source") == "inferred" or r.get("mandatory") is False]

            logs.append(self._make_log(
                f"Extracted {len(explicit_flat)} explicit and {len(inferred_flat)} inferred requirements "
                f"(confidence: {extracted.confidence_score:.0%}) from {jira.get('jira_key')}."
            ))

            if extracted.extraction_notes:
                logs.append(self._make_log(f"Notes: {extracted.extraction_notes}", "warning"))

            log.info(
                "agent.req_extraction.complete",
                review_id=self._review_id,
                explicit=len(explicit_flat),
                inferred=len(inferred_flat),
                confidence=extracted.confidence_score,
            )

            return {
                "requirements": flat_requirements,
                "explicit_requirements": explicit_flat,
                "inferred_requirements": inferred_flat,
                "extracted_requirements": extracted.model_dump(),
                "logs": logs,
                "current_agent": self.name,
                "progress_percent": 26,
            }

        except Exception as exc:
            log.error("agent.req_extraction.failed", review_id=self._review_id, error=str(exc))
            logs.append(self._make_log(f"Requirement extraction failed: {exc}", "error"))
            errors = {**(state.get("agent_errors") or {}), self.name: str(exc)}
            return {
                "requirements": [],
                "explicit_requirements": [],
                "inferred_requirements": [],
                "logs": logs,
                "agent_errors": errors,
                "current_agent": self.name,
                "progress_percent": 26,
            }

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_user_prompt(self, jira: dict) -> str:
        acs = jira.get("acceptance_criteria", [])
        ac_block = "\n".join(f"  - {ac}" for ac in acs) if acs else "  (none provided — explicit Acceptance Criteria section is empty)"

        return f"""## Jira Issue: {jira.get('jira_key', 'UNKNOWN')}

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

---
Extract requirements carefully.
If Acceptance Criteria from Jira is empty or "(none provided)", `explicit_requirements` MUST be empty [].
Put expectations inferred from Summary or Description into `inferred_requirements` using INF-01, INF-02 namespace.
jira_key must be exactly: {jira.get('jira_key', 'UNKNOWN')}"""

    # ── Parser & validator ────────────────────────────────────────────────────

    def _parse_and_validate(self, raw: dict, jira_key: str) -> ExtractedRequirements:
        """Normalise LLM output keys and validate with Pydantic."""
        raw_explicit = raw.get("explicit_requirements", raw.get("explicitRequirements", []))
        raw_inferred = raw.get("inferred_requirements", raw.get("inferredRequirements", []))

        explicit_items = []
        for item in raw_explicit:
            if isinstance(item, dict):
                item["source"] = "explicit"
                item["source_location"] = item.get("source_location", "jira_acceptance_criteria")
                item["mandatory"] = True
                if not item.get("id", "").startswith("AC-") and not item.get("id", "").startswith("REQ-"):
                    item["id"] = f"AC-{len(explicit_items)+1:02d}"
                explicit_items.append(item)

        inferred_items = []
        for item in raw_inferred:
            if isinstance(item, dict):
                item["source"] = "inferred"
                item["source_location"] = item.get("source_location", "jira_description")
                item["mandatory"] = False
                if not item.get("id", "").startswith("INF-"):
                    item["id"] = f"INF-{len(inferred_items)+1:02d}"
                inferred_items.append(item)

        normalised = {
            "jira_key": jira_key,
            "explicit_requirements": explicit_items,
            "inferred_requirements": inferred_items,
            "functional_requirements": raw.get("functionalRequirements", raw.get("functional_requirements", [])),
            "acceptance_criteria": raw.get("acceptanceCriteria", raw.get("acceptance_criteria", [])),
            "business_rules": raw.get("businessRules", raw.get("business_rules", [])),
            "api_requirements": raw.get("apiRequirements", raw.get("api_requirements", [])),
            "ui_requirements": raw.get("uiRequirements", raw.get("ui_requirements", [])),
            "performance_requirements": raw.get("performanceRequirements", raw.get("performance_requirements", [])),
            "extraction_notes": raw.get("extraction_notes", ""),
            "confidence_score": float(raw.get("confidence_score", 0.8)),
        }
        try:
            return ExtractedRequirements.model_validate(normalised)
        except Exception as e:
            log.warning("agent.req_extraction.validation_partial", errors=str(e))
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
            explicit_requirements=safe_list(data.get("explicit_requirements", []), RequirementItem),
            inferred_requirements=safe_list(data.get("inferred_requirements", []), RequirementItem),
            functional_requirements=safe_list(data.get("functional_requirements", []), FunctionalRequirement),
            acceptance_criteria=safe_list(data.get("acceptance_criteria", []), AcceptanceCriterion),
            business_rules=safe_list(data.get("business_rules", []), BusinessRule),
            api_requirements=safe_list(data.get("api_requirements", []), ApiRequirement),
            ui_requirements=safe_list(data.get("ui_requirements", []), UiRequirement),
            performance_requirements=safe_list(data.get("performance_requirements", []), PerformanceRequirement),
            extraction_notes=data.get("extraction_notes", "Partial extraction due to validation errors."),
            confidence_score=data.get("confidence_score", 0.5),
        )

    # ── Flatten to simple dicts for state storage ─────────────────────────────

    @staticmethod
    def _flatten_to_requirement_list(extracted: ExtractedRequirements) -> list[dict]:
        """
        Produces flat dictionaries carrying provenance metadata.
        """
        flat_explicit: list[dict] = []
        flat_inferred: list[dict] = []
        all_flat: list[dict] = []

        for req in extracted.explicit_requirements:
            d = {
                "id": req.id,
                "title": req.title,
                "description": req.description,
                "source": "explicit",
                "source_location": req.source_location.value if hasattr(req.source_location, "value") else str(req.source_location),
                "mandatory": True,
                "priority": req.priority,
                "confidence": req.confidence,
                "type": req.type,
                "given": req.given,
                "when": req.when,
                "then": req.then,
            }
            flat_explicit.append(d)
            all_flat.append(d)

        for req in extracted.inferred_requirements:
            d = {
                "id": req.id,
                "title": req.title,
                "description": req.description,
                "source": "inferred",
                "source_location": req.source_location.value if hasattr(req.source_location, "value") else str(req.source_location),
                "mandatory": False,
                "priority": req.priority,
                "confidence": req.confidence,
                "type": req.type,
            }
            flat_inferred.append(d)
            all_flat.append(d)

        # Fallback to category lists if explicit/inferred were not populated directly by LLM
        if not all_flat:
            for r in extracted.acceptance_criteria:
                d = {
                    "id": r.id,
                    "title": r.description[:50],
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": r.priority,
                    "type": "acceptance_criterion",
                    "given": r.given,
                    "when": r.when,
                    "then": r.then,
                }
                if d["source"] in ("explicit", "jira"):
                    flat_explicit.append(d)
                else:
                    flat_inferred.append(d)
                all_flat.append(d)

            for r in extracted.functional_requirements:
                d = {
                    "id": r.id,
                    "title": r.title,
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": r.priority,
                    "type": "functional",
                    "testable": r.testable,
                }
                if d["source"] in ("explicit", "jira"):
                    flat_explicit.append(d)
                else:
                    flat_inferred.append(d)
                all_flat.append(d)

            for r in extracted.business_rules:
                d = {
                    "id": r.id,
                    "title": r.description[:50],
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": "should",
                    "type": "business_rule",
                }
                if d["source"] in ("explicit", "jira"):
                    flat_explicit.append(d)
                else:
                    flat_inferred.append(d)
                all_flat.append(d)

            for r in extracted.api_requirements:
                d = {
                    "id": r.id,
                    "title": r.description[:50],
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": "should",
                    "type": "api",
                    "method": r.method,
                    "endpoint": r.endpoint,
                }
                all_flat.append(d)

            for r in extracted.ui_requirements:
                d = {
                    "id": r.id,
                    "title": r.description[:50],
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": "should",
                    "type": "ui",
                    "component": r.component,
                }
                all_flat.append(d)

            for r in extracted.performance_requirements:
                d = {
                    "id": r.id,
                    "title": r.description[:50],
                    "description": r.description,
                    "source": r.source.value if hasattr(r.source, "value") else str(r.source),
                    "source_location": r.source_location.value if hasattr(r.source_location, "value") else str(r.source_location),
                    "mandatory": r.mandatory,
                    "priority": "should",
                    "type": "performance",
                    "metric": r.metric,
                    "threshold": r.threshold,
                }
                all_flat.append(d)

        return all_flat
