"""
Requirement Validation Agent
─────────────────────────────
Node:          req_validation
Predecessor:   req_extraction
Input:         ReviewState.requirements + ReviewState.pr_context (diff + files)
Output:        ReviewState.findings (requirement-category findings)
               ReviewState.validation_output (full ValidationOutput dict)

Responsibilities:
  1. Validate requirements against the actual code diff and code context
  2. Treat EXPLICIT requirements as mandatory for formal compliance scoring
  3. Treat INFERRED expectations as advisory (do NOT reduce formal compliance score)
  4. Perform code-flow tracing (factories, upstream controllers, feature flags) before reporting gaps
  5. Never infer scope mismatch based solely on class filenames
"""
from __future__ import annotations

import json
from typing import Any, Optional

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

Your task is to validate whether a code diff correctly and completely implements a set of requirements.

## REQUIREMENT PROVENANCE & SCORING RULES

Requirements are divided into two distinct sources:

### A. EXPLICIT REQUIREMENTS (Source: explicit, IDs like AC-01, AC-02)
- Authoritative requirements from Jira Acceptance Criteria.
- Mandatory pass/fail criteria.
- Validated as: implemented, partial, missing, violated, not_applicable.
- Factor into the `overall_compliance_score` (0–100%).

### B. INFERRED EXPECTATIONS (Source: inferred, IDs like INF-01, INF-02)
- Derived from Jira Summary/Description when formal ACs are missing or incomplete.
- NOT contractual acceptance criteria.
- MUST NOT reduce the `overall_compliance_score`.
- MUST NOT be called "requirement violations".
- MUST NOT be assigned CRITICAL or HIGH severity simply because code is absent.
- Validated as: implemented, potential_gap, not_applicable, cannot_determine.
- Findings MUST use title wording like: "Potential requirement gap" or "Expected behavior inferred from Jira description".

## CRITICAL CODE VERIFICATION RULES

1. **Upstream Code Flow & Feature Flags**:
   - Do NOT assume business logic belongs in the changed exporter or handler file alone.
   - Check if feature flags, currency conversions, or eligibility rules are evaluated upstream in controllers, domain models, or service classes.
   - If `foreignSellPrice` or configuration flags are pre-calculated upstream, the exporter class does NOT need to repeat the check.

2. **No Class Name Scope Mismatches**:
   - Do NOT report scope mismatch based solely on class filenames (e.g. `PricingFileType.CRUNCH_TIME_STD` mapping to `EDIClientPricingCafeZupas`).
   - Mappings, factories, and inheritance hierarchies govern runtime selection. Class filenames alone are NOT evidence of a scope defect.

3. **Distinguish FACT, INFERENCE, and UNVERIFIED RISK**:
   - **FACT**: Supported directly by code in the diff.
   - **INFERENCE**: Reasonable conclusion from available code flow.
   - **UNVERIFIED RISK**: Potential runtime issue that cannot be proven from diff alone.
   - Never report an UNVERIFIED RISK as a confirmed violation or CRITICAL/HIGH finding.

## COMPLIANCE SCORING
- If there are EXPLICIT requirements: `overall_compliance_score` = percentage of EXPLICIT requirements satisfied (0-100).
- If there are NO explicit requirements (i.e. all requirements are source: "inferred"): `overall_compliance_score` MUST BE `null` (None in Python). Set `compliance_explanation` to "Formal requirement compliance: N/A — no explicit acceptance criteria provided in Jira."

## Output Format
Return ONLY a single valid JSON object:

```json
{
  "jira_key": "PROJ-123",
  "overall_compliance_score": 80.0_or_null,
  "has_explicit_ac": true_or_false,
  "compliance_explanation": "...",
  "requirement_results": [
    {
      "requirement_id": "AC-01",
      "requirement_type": "acceptance_criterion",
      "source": "explicit|inferred|verified_inferred",
      "description": "...",
      "status": "implemented|partial|missing|violated|potential_gap|not_applicable|cannot_determine",
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
      "requirement_id": "AC-02",
      "source": "explicit|inferred",
      "description": "...",
      "severity": "critical|high|medium|low|info",
      "impact": "business impact description",
      "suggested_fix": "concrete implementation suggestion"
    }
  ],
  "partial_implementations": [
    {
      "requirement_id": "AC-01",
      "source": "explicit|inferred",
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
""".strip()


# ── LangGraph Node Function ───────────────────────────────────────────────────

async def req_validation_node(state: ReviewState) -> dict:
    """LangGraph node — validates requirements against the PR diff."""
    agent = RequirementValidationAgent(state)
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

        if not requirements:
            logs.append(self._make_log("No requirements to validate — skipping.", "info"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 34}

        if not diff:
            logs.append(self._make_log("No diff available — skipping validation.", "warning"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 34}

        log.info("agent.req_validation.start",
                 review_id=self._review_id,
                 requirements=len(requirements),
                 diff_bytes=len(diff))

        user_prompt = self._build_prompt(requirements, diff, files, pr_context, state)
        class_structs = self._get_class_structures_prompt(state)
        changed_methods = self._get_changed_methods_prompt(state)
        context_chars = len(class_structs) + len(changed_methods)

        try:
            raw_json = await self._invoke_llm_json(
                SYSTEM_PROMPT,
                user_prompt,
                context_mode="full_repository",
                repository_context=True,
                diff_chars=len(diff),
                context_chars=context_chars,
            )
            validation = self._parse_and_validate(
                raw_json, state.get("jira_context", {}).get("jira_key", "UNKNOWN"), requirements
            )
            findings = self._to_findings(validation)
            existing_findings = list(state.get("findings", []))

            score_str = f"{validation.overall_compliance_score:.0f}%" if validation.overall_compliance_score is not None else "N/A (No explicit ACs)"
            logs.append(self._make_log(
                f"Validation complete — formal compliance: {score_str}, "
                f"explicit missing: {validation.missing_count}, explicit partial: {validation.partial_count}, "
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
{diff}
```
{self._get_class_structures_prompt(state)}
{self._get_changed_methods_prompt(state)}

Validate EACH requirement above against this diff and code context. Preserve requirement provenance (explicit vs inferred)."""

    @staticmethod
    def _format_requirements(requirements: list[dict]) -> str:
        lines = []
        for r in requirements[:30]:
            rid   = r.get("id", "?")
            source = r.get("source", "explicit")
            rtype = r.get("type", "functional")
            desc  = r.get("description", "")
            pri   = r.get("priority", "must")
            lines.append(f"[{rid}] (Source: {source}, Type: {rtype}, Priority: {pri}) {desc}")
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

    def _parse_and_validate(self, raw: dict, jira_key: str, requirements: list[dict]) -> ValidationOutput:
        raw["jira_key"] = jira_key

        explicit_reqs = [r for r in requirements if r.get("source") == "explicit" or r.get("mandatory") is True]
        has_explicit = len(explicit_reqs) > 0

        raw["has_explicit_ac"] = has_explicit
        if not has_explicit:
            raw["overall_compliance_score"] = None
            raw["compliance_explanation"] = "Formal requirement compliance: N/A — no explicit acceptance criteria provided in Jira."

        try:
            val = ValidationOutput.model_validate(raw)
            if has_explicit and val.overall_compliance_score is not None:
                val.compliance_explanation = f"Formal requirement compliance: {val.overall_compliance_score:.0f}% (calculated against explicit Jira ACs)."
            return val
        except Exception as e:
            log.warning("agent.req_validation.partial_parse", errors=str(e)[:200])
            return self._build_partial_output(raw, jira_key, has_explicit)

    def _build_partial_output(self, raw: dict, jira_key: str, has_explicit: bool) -> ValidationOutput:
        def safe_list(items, model):
            result = []
            for item in (items or []):
                try:
                    result.append(model.model_validate(item))
                except Exception:
                    pass
            return result

        score = float(raw.get("overall_compliance_score", 50)) if (has_explicit and raw.get("overall_compliance_score") is not None) else None

        return ValidationOutput(
            jira_key=jira_key,
            overall_compliance_score=score,
            has_explicit_ac=has_explicit,
            compliance_explanation="Formal requirement compliance: N/A — no explicit acceptance criteria provided in Jira." if not has_explicit else f"Formal requirement compliance: {score:.0f}%",
            requirement_results=safe_list(raw.get("requirement_results", []), RequirementValidationResult),
            missing_requirements=safe_list(raw.get("missing_requirements", []), MissingRequirement),
            partial_implementations=safe_list(raw.get("partial_implementations", []), PartialImplementation),
            regression_risks=safe_list(raw.get("regression_risks", []), RegressionRisk),
            validation_notes=raw.get("validation_notes", "Partial parse — some data may be missing."),
        )

    # ── Convert ValidationOutput → ReviewFindings ─────────────────────────────

    def _to_findings(self, validation: ValidationOutput) -> list[FindingDict]:
        findings: list[FindingDict] = []

        # 1. Missing requirements
        for mr in validation.missing_requirements:
            is_explicit = mr.source == "explicit" or mr.requirement_id.startswith("AC-")
            sev = mr.severity if is_explicit else "medium"
            if not is_explicit and sev in ("critical", "high"):
                sev = "medium"

            title_prefix = "Missing Implementation:" if is_explicit else "Potential Requirement Gap (Inferred):"
            comment_header = f"**Requirement `{mr.requirement_id}` not implemented.**" if is_explicit else f"**Expected behavior `{mr.requirement_id}` inferred from Jira description:**"

            findings.append(self._make_finding(
                severity=sev,
                title=f"{title_prefix} {mr.requirement_id}",
                description=mr.description,
                recommendation=mr.suggested_fix,
                review_comment=(
                    f"{comment_header}\n\n"
                    f"{mr.description}\n\n"
                    f"**Impact / Context:** {mr.impact}\n\n"
                    f"**Suggested Fix:** {mr.suggested_fix}"
                ),
                evidence=None,
                origin="introduced_by_pr" if is_explicit else "pre_existing",
                classification="finding" if is_explicit else "recommendation",
                affected_by_pr=is_explicit,
                tags=["missing-requirement", mr.requirement_id, "explicit" if is_explicit else "inferred"],
            ))

        # 2. Partial implementations
        for pi in validation.partial_implementations:
            is_explicit = pi.source == "explicit" or pi.requirement_id.startswith("AC-")
            sev = pi.severity if pi.severity in ("critical", "high", "medium", "low", "info") else "medium"
            if not is_explicit and sev in ("critical", "high"):
                sev = "medium"

            title_prefix = "Partial Implementation:" if is_explicit else "Inferred Expectation Partially Met:"
            findings.append(self._make_finding(
                severity=sev,
                title=f"{title_prefix} {pi.requirement_id} ({pi.completion_percent}% complete)",
                description=pi.description,
                recommendation=f"Complete the missing part: {pi.missing_part}",
                review_comment=(
                    f"**Requirement `{pi.requirement_id}` is partially met ({pi.completion_percent}%).**\n\n"
                    f"✅ **Done:** {pi.implemented_part}\n\n"
                    f"❌ **Missing:** {pi.missing_part}"
                ),
                file_path=pi.file_path,
                line_number=pi.line_number,
                origin="modified_by_pr" if is_explicit else "pre_existing",
                classification="finding" if is_explicit else "recommendation",
                affected_by_pr=is_explicit,
                tags=["partial-implementation", pi.requirement_id, "explicit" if is_explicit else "inferred"],
            ))

        # 3. Violated / Potential Gap requirements
        for rr in validation.requirement_results:
            is_explicit = rr.source == "explicit" or rr.requirement_id.startswith("AC-")
            if rr.status == ValidationStatus.violated and is_explicit:
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
                    origin="introduced_by_pr",
                    classification="finding",
                    affected_by_pr=True,
                    tags=["requirement-violated", rr.requirement_id, "explicit"],
                ))
            elif rr.status in (ValidationStatus.potential_gap, ValidationStatus.missing, ValidationStatus.partial) and not is_explicit:
                findings.append(self._make_finding(
                    severity="low",
                    title=f"Expected behavior inferred from Jira description: {rr.requirement_id}",
                    description=rr.gap_description or rr.description,
                    recommendation=rr.suggestion or "Verify whether FX eligibility decision occurs upstream before applying this change.",
                    review_comment=(
                        f"**Advisory Expectation (`{rr.requirement_id}`):**\n\n"
                        f"{rr.description}\n\n"
                        f"**Observation:** {rr.gap_description or 'Verify upstream flow.'}"
                    ),
                    file_path=rr.file_path,
                    line_number=rr.line_number,
                    evidence=rr.evidence,
                    confidence_score=rr.confidence,
                    origin="pre_existing",
                    classification="recommendation",
                    affected_by_pr=False,
                    tags=["inferred-expectation", rr.requirement_id, "inferred"],
                ))

        # 4. Regression risks
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

        # 5. Low compliance score summary finding — ONLY IF EXPLICIT ACs EXIST
        if validation.has_explicit_ac and validation.overall_compliance_score is not None and validation.overall_compliance_score < 60:
            findings.append(self._make_finding(
                severity="high",
                title=f"Low Requirements Compliance: {validation.overall_compliance_score:.0f}%",
                description=(
                    f"Only {validation.overall_compliance_score:.0f}% of explicit requirements are implemented. "
                    f"{validation.missing_count} requirement(s) missing, "
                    f"{validation.partial_count} partial."
                ),
                recommendation="Review and implement all missing and partial requirements before merging.",
                review_comment=(
                    f"**This PR implements only {validation.overall_compliance_score:.0f}% of its explicit requirements.**\n\n"
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
        Filters ONLY for explicit requirements.
        """
        if not validation.has_explicit_ac or validation.overall_compliance_score is None:
            return {
                "score": None,
                "grade": "N/A",
                "summary": "Formal requirement compliance: N/A — no explicit acceptance criteria provided in Jira.",
                "has_explicit_ac": False,
            }

        explicit_results = [r for r in validation.requirement_results if r.source == "explicit"]
        total = len(explicit_results)
        if total == 0:
            return {"score": None, "grade": "N/A", "summary": "No explicit requirements to evaluate.", "has_explicit_ac": False}

        weights = {
            ValidationStatus.implemented:      1.0,
            ValidationStatus.partial:           0.5,
            ValidationStatus.missing:           0.0,
            ValidationStatus.violated:         -0.5,
            ValidationStatus.not_applicable:    1.0,
            ValidationStatus.cannot_determine:  0.5,
        }
        na_count = sum(1 for r in explicit_results if r.status == ValidationStatus.not_applicable)
        effective_total = total - na_count
        if effective_total == 0:
            score = 100.0
        else:
            raw_score = sum(
                weights.get(r.status, 0)
                for r in explicit_results
                if r.status != ValidationStatus.not_applicable
            )
            score = max(0.0, min(100.0, (raw_score / effective_total) * 100))

        high_reg = sum(1 for r in validation.regression_risks if r.risk_level == RegressionRiskLevel.high)
        score = max(0.0, score - (high_reg * 10))

        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

        return {
            "score":             round(score, 1),
            "grade":             grade,
            "has_explicit_ac":   True,
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
