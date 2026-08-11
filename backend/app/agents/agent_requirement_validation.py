"""
Requirement Validation Agent
——————————————————————————————
Node:          req_validation
Predecessor:   req_extraction
Input:         ReviewState.requirements + ReviewState.pr_context (diff + files)
Output:        ReviewState.findings (requirement-category findings)
               ReviewState.validation_output (full ValidationOutput dict)

Responsibilities:
  1. Validate each extracted requirement against the actual code diff
  2. Detect missing implementations (requirement exists, no code change)
  3. Detect partial implementations (some but not all AC steps present)
  4. Detect regression risks (existing behaviour changed without corresponding tests)
  5. Produce ReviewFindings for all gaps found
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.agents.models.validation_models import (
    MissingRequirement,
    PartialImplementation,
    RegressionRisk,
    RegressionRiskLevel,
    RequirementValidationResult,
    ValidationOutput,
    ValidationStatus,
)
from app.agents.state import FindingDict, ReviewState
from app.core.logging import get_logger

log = get_logger(__name__)


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a Senior QA Engineer and Requirements Traceability Expert.

Your task is to validate whether a code diff correctly and completely implements a set of structured requirements.

## Your Responsibilities

### 1. Requirement Validation
For EACH requirement provided, determine its implementation status:
- **implemented**: Clearly present in the diff with correct logic
- **partial**: Some aspects implemented but incomplete
- **missing**: No evidence in the diff at all
- **violated**: Code contradicts or breaks the requirement
- **not_applicable**: Requirement doesn't apply to this code change (e.g. UI req in backend-only PR)
- **cannot_determine**: Insufficient diff context to evaluate

### 2. Missing Requirements Detection
Identify requirements with NO corresponding code change. These are high-priority findings.

### 3. Partial Implementation Detection
For partial implementations, specify EXACTLY:
- What IS implemented (with file/line if visible)
- What is NOT implemented
- Estimated completion percentage

### 4. Regression Risk Analysis
Examine files changed for risks to EXISTING functionality:
- Shared utilities modified without updating callers
- Database schema changes without migration
- API contract changes breaking consumers
- Removed or renamed methods still referenced
- Configuration changes with undocumented side-effects

## Output Format
Return ONLY a single valid JSON object:

```json
{
  "jira_key": "PROJ-123",
  "overall_compliance_score": 0-100,
  "requirement_results": [
    {
      "requirement_id": "FR-01",
      "requirement_type": "functional",
      "description": "...",
      "status": "implemented|partial|missing|violated|not_applicable|cannot_determine",
      "evidence": "code snippet or null",
      "file_path": "path/to/file or null",
      "line_number": null,
      "gap_description": "what is missing/wrong or null",
      "suggestion": "how to fix or null",
      "confidence": 0.0-1.0
    }
  ],
  "missing_requirements": [
    {
      "requirement_id": "FR-02",
      "description": "...",
      "severity": "critical|high|medium|low",
      "impact": "business impact description",
      "suggested_fix": "concrete implementation suggestion"
    }
  ],
  "partial_implementations": [
    {
      "requirement_id": "AC-01",
      "description": "...",
      "implemented_part": "what is done",
      "missing_part": "what is not done",
      "file_path": "path or null",
      "line_number": null,
      "severity": "high|medium|low",
      "completion_percent": 0-100
    }
  ],
  "regression_risks": [
    {
      "id": "REG-01",
      "risk_level": "high|medium|low|none",
      "area": "feature area name",
      "description": "what could regress",
      "affected_files": ["file1.java"],
      "mitigation": "how to mitigate"
    }
  ],
  "validation_notes": "any important observations"
}
```

## Rules
- Be precise — reference exact file paths and line numbers when visible in diff
- Score compliance_score: 100 = all requirements fully implemented, 0 = nothing implemented
- A requirement marked "not_applicable" does NOT reduce the compliance score
- Treat each acceptance criterion independently
- High-severity missing requirements must have detailed suggested_fix
""".strip()


# ── LangGraph Node Function ───────────────────────────────────────────────────

async def req_validation_node(state: ReviewState) -> dict:
    """LangGraph node — validates requirements against the PR diff."""
    agent = RequirementValidationAgent(state)  # state used as settings fallback here
    return await agent.run(state)


# ── Agent Implementation ──────────────────────────────────────────────────────

class RequirementValidationAgent(BaseAgent):
    name     = "req_validation"
    category = "requirement"

    def _get_llm(self, temperature: float = 0.05):
        return super()._get_llm(temperature=temperature, json_mode=True)

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        requirements = state.get("requirements", [])
        pr_context   = state.get("pr_context", {})
        diff         = pr_context.get("diff", "")
        files        = pr_context.get("files_changed", [])

        # Early-exit guards
        if not requirements:
            logs.append(self._make_log("No requirements to validate — skipping.", "warning"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 34}

        if not diff:
            logs.append(self._make_log("No diff available — skipping validation.", "warning"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 34}

        log.info("agent.req_validation.start",
                 review_id=self._review_id,
                 requirements=len(requirements),
                 diff_bytes=len(diff))

        user_prompt = self._build_prompt(requirements, diff, files, pr_context, state)

        try:
            raw_json = await self._invoke_llm_json(SYSTEM_PROMPT, user_prompt)
            validation = self._parse_and_validate(
                raw_json, state.get("jira_context", {}).get("jira_key", "UNKNOWN")
            )
            findings = self._to_findings(validation)

            existing_findings = list(state.get("findings", []))

            logs.append(self._make_log(
                f"Validation complete — compliance: {validation.overall_compliance_score:.0f}%, "
                f"missing: {validation.missing_count}, partial: {validation.partial_count}, "
                f"regressions: {len(validation.regression_risks)}."
            ))

            if validation.high_regression_count:
                logs.append(self._make_log(
                    f"⚠ {validation.high_regression_count} HIGH regression risk(s) detected.", "warning"
                ))

            log.info("agent.req_validation.complete",
                     review_id=self._review_id,
                     compliance=validation.overall_compliance_score,
                     findings=len(findings))

            return {
                "findings":          existing_findings + findings,
                "validation_output": validation.model_dump(),
                "logs":              logs,
                "current_agent":     self.name,
                "progress_percent":  34,
            }

        except Exception as exc:
            log.error("agent.req_validation.failed", review_id=self._review_id, error=str(exc))
            logs.append(self._make_log(f"Validation failed: {exc}", "error"))
            errors = {**(state.get("agent_errors") or {}), self.name: str(exc)}
            return {
                "logs":          logs,
                "agent_errors":  errors,
                "current_agent": self.name,
                "progress_percent": 34,
            }

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        requirements: list[dict],
        diff: str,
        files: list[dict],
        pr_context: dict,
        state: Optional[dict] = None,
    ) -> str:
        req_block = self._format_requirements(requirements)
        files_block = self._format_files(files)
        diff_block = self._truncate_diff(diff, 14000)

        return f"""## Pull Request Context
PR: #{pr_context.get('pr_number')} — {pr_context.get('pr_title', '')}
Source Branch: {pr_context.get('source_branch', '')}
Target Branch: {pr_context.get('target_branch', '')}
Author: {pr_context.get('author', '')}

## Changed Files ({len(files)} total)
{files_block}

## Requirements to Validate ({len(requirements)} total)
{req_block}

## Code Diff
```diff
{diff_block}
```
{self._get_class_structures_prompt(state)}
{self._get_changed_methods_prompt(state)}

Validate EACH requirement above against this diff and code context. Be thorough."""

    @staticmethod
    def _format_requirements(requirements: list[dict]) -> str:
        lines = []
        for r in requirements[:30]:  # cap at 30 to stay in context window
            rid   = r.get("id", "?")
            rtype = r.get("type", "functional")
            desc  = r.get("description", "")
            pri   = r.get("priority", "must")
            lines.append(f"[{rid}] ({rtype}, {pri}) {desc}")
            # Add AC sub-fields if present
            if r.get("given"):
                lines.append(f"  Given: {r['given']}")
            if r.get("when"):
                lines.append(f"  When: {r['when']}")
            if r.get("then"):
                lines.append(f"  Then: {r['then']}")
        return "\n".join(lines)

    @staticmethod
    def _format_files(files: list[dict]) -> str:
        lines = []
        for f in files[:20]:
            path  = f.get("path", "unknown")
            added = f.get("lines_added", 0)
            removed = f.get("lines_removed", 0)
            lines.append(f"  {path}  (+{added} / -{removed})")
        return "\n".join(lines) or "  (no file list available)"

    # ── Parser & validator ────────────────────────────────────────────────────

    def _parse_and_validate(self, raw: dict, jira_key: str) -> ValidationOutput:
        # Normalise top-level key
        raw["jira_key"] = jira_key
        try:
            return ValidationOutput.model_validate(raw)
        except ValidationError as e:
            log.warning("agent.req_validation.partial_parse", errors=str(e)[:200])
            return self._build_partial_output(raw, jira_key)

    def _build_partial_output(self, raw: dict, jira_key: str) -> ValidationOutput:
        def safe_list(items, model):
            result = []
            for item in (items or []):
                try:
                    result.append(model.model_validate(item))
                except Exception:
                    pass
            return result

        return ValidationOutput(
            jira_key=jira_key,
            overall_compliance_score=float(raw.get("overall_compliance_score", 50)),
            requirement_results=safe_list(raw.get("requirement_results", []), RequirementValidationResult),
            missing_requirements=safe_list(raw.get("missing_requirements", []),  MissingRequirement),
            partial_implementations=safe_list(raw.get("partial_implementations", []), PartialImplementation),
            regression_risks=safe_list(raw.get("regression_risks", []),           RegressionRisk),
            validation_notes=raw.get("validation_notes", "Partial parse — some data may be missing."),
        )

    # ── Convert ValidationOutput → ReviewFindings ─────────────────────────────

    def _to_findings(self, validation: ValidationOutput) -> list[FindingDict]:
        findings: list[FindingDict] = []

        # 1. Missing requirements → high/critical findings
        for mr in validation.missing_requirements:
            findings.append(self._make_finding(
                severity=mr.severity,
                title=f"Missing Implementation: {mr.requirement_id}",
                description=mr.description,
                recommendation=mr.suggested_fix,
                review_comment=(
                    f"**Requirement `{mr.requirement_id}` not implemented.**\n\n"
                    f"{mr.description}\n\n"
                    f"**Business Impact:** {mr.impact}\n\n"
                    f"**Suggested Fix:** {mr.suggested_fix}"
                ),
                evidence=None,
                tags=["missing-requirement", mr.requirement_id],
            ))

        # 2. Partial implementations → medium findings
        for pi in validation.partial_implementations:
            sev = pi.severity if pi.severity in ("critical","high","medium","low","info") else "medium"
            findings.append(self._make_finding(
                severity=sev,
                title=f"Partial Implementation: {pi.requirement_id} ({pi.completion_percent}% complete)",
                description=pi.description,
                recommendation=f"Complete the missing part: {pi.missing_part}",
                review_comment=(
                    f"**Requirement `{pi.requirement_id}` is only partially implemented "
                    f"({pi.completion_percent}%).**\n\n"
                    f"✅ **Done:** {pi.implemented_part}\n\n"
                    f"❌ **Missing:** {pi.missing_part}"
                ),
                file_path=pi.file_path,
                line_number=pi.line_number,
                tags=["partial-implementation", pi.requirement_id],
            ))

        # 3. Violated requirements → critical/high findings
        for rr in validation.requirement_results:
            if rr.status == ValidationStatus.violated:
                findings.append(self._make_finding(
                    severity="high",
                    title=f"Requirement Violated: {rr.requirement_id}",
                    description=rr.gap_description or rr.description,
                    recommendation=rr.suggestion or "Correct the implementation to satisfy this requirement.",
                    review_comment=(
                        f"**Requirement `{rr.requirement_id}` is VIOLATED by this change.**\n\n"
                        f"**Requirement:** {rr.description}\n\n"
                        f"**Violation:** {rr.gap_description}\n\n"
                        f"**Fix:** {rr.suggestion or 'Review and correct the implementation.'}"
                    ),
                    file_path=rr.file_path,
                    line_number=rr.line_number,
                    evidence=rr.evidence,
                    confidence_score=rr.confidence,
                    tags=["requirement-violated", rr.requirement_id],
                ))

        # 4. Regression risks → severity based on risk level
        severity_map = {
            RegressionRiskLevel.high:   "high",
            RegressionRiskLevel.medium: "medium",
            RegressionRiskLevel.low:    "low",
            RegressionRiskLevel.none:   "info",
        }
        for reg in validation.regression_risks:
            if reg.risk_level == RegressionRiskLevel.none:
                continue
            findings.append(self._make_finding(
                severity=severity_map[reg.risk_level],
                title=f"Regression Risk: {reg.area}",
                description=reg.description,
                recommendation=reg.mitigation,
                review_comment=(
                    f"**⚠ Regression Risk Detected — {reg.risk_level.upper()}**\n\n"
                    f"**Area:** {reg.area}\n\n"
                    f"**Risk:** {reg.description}\n\n"
                    f"**Affected Files:** {', '.join(reg.affected_files) or 'see diff'}\n\n"
                    f"**Mitigation:** {reg.mitigation}"
                ),
                tags=["regression-risk", reg.risk_level],
            ))

        # 5. Low compliance score → summary finding
        if validation.overall_compliance_score < 60:
            findings.append(self._make_finding(
                severity="high",
                title=f"Low Requirements Compliance: {validation.overall_compliance_score:.0f}%",
                description=(
                    f"Only {validation.overall_compliance_score:.0f}% of requirements are implemented. "
                    f"{validation.missing_count} requirement(s) missing, "
                    f"{validation.partial_count} partial."
                ),
                recommendation="Review and implement all missing and partial requirements before merging.",
                review_comment=(
                    f"**This PR implements only {validation.overall_compliance_score:.0f}% of its requirements.**\n\n"
                    f"| Status | Count |\n|--------|-------|\n"
                    f"| ✅ Implemented | {validation.implemented_count} |\n"
                    f"| ⚠ Partial | {validation.partial_count} |\n"
                    f"| ❌ Missing | {validation.missing_count} |\n"
                    f"| 🚫 Violated | {validation.violated_count} |"
                ),
                tags=["compliance-score"],
            ))

        return findings

    # ── Evaluation helper (used by tests / scoring pipeline) ─────────────────

    @staticmethod
    def evaluate_compliance(validation: ValidationOutput) -> dict:
        """
        Returns a structured evaluation report for scoring and reporting.
        Usable outside the agent — e.g. in CI gates.
        """
        total = len(validation.requirement_results)
        if total == 0:
            return {"score": 0, "grade": "N/A", "summary": "No requirements to evaluate."}

        # Weighted scoring
        weights = {
            ValidationStatus.implemented:      1.0,
            ValidationStatus.partial:           0.5,
            ValidationStatus.missing:           0.0,
            ValidationStatus.violated:         -0.5,
            ValidationStatus.not_applicable:    1.0,  # excluded from denominator
            ValidationStatus.cannot_determine:  0.5,
        }
        na_count = sum(1 for r in validation.requirement_results if r.status == ValidationStatus.not_applicable)
        effective_total = total - na_count
        if effective_total == 0:
            score = 100.0
        else:
            raw_score = sum(
                weights.get(r.status, 0)
                for r in validation.requirement_results
                if r.status != ValidationStatus.not_applicable
            )
            score = max(0.0, min(100.0, (raw_score / effective_total) * 100))

        # Regression penalty
        high_reg = sum(1 for r in validation.regression_risks if r.risk_level == RegressionRiskLevel.high)
        score = max(0.0, score - (high_reg * 10))

        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

        return {
            "score":             round(score, 1),
            "grade":             grade,
            "total_requirements": total,
            "effective_total":   effective_total,
            "implemented":       validation.implemented_count,
            "partial":           validation.partial_count,
            "missing":           validation.missing_count,
            "violated":          validation.violated_count,
            "regression_risks":  len(validation.regression_risks),
            "high_regressions":  high_reg,
            "summary": (
                f"Grade {grade} ({score:.0f}%): "
                f"{validation.implemented_count} implemented, "
                f"{validation.missing_count} missing, "
                f"{validation.partial_count} partial, "
                f"{high_reg} high-risk regression(s)."
            ),
        }
