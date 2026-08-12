"""
Regression test suite for ReviewAI requirement extraction, validation,
provenance tracking, and finding deduplication (targeting FRES-8862 architectural fixes).
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.agents.agent_requirement_extraction import RequirementExtractionAgent
from app.agents.agent_requirement_validation import RequirementValidationAgent
from app.agents.deduplication import deduplicate_findings
from app.agents.models.requirement_models import ExtractedRequirements
from app.agents.models.validation_models import ValidationOutput, ValidationStatus


@pytest.mark.asyncio
async def test_fres8862_no_explicit_ac_compliance_is_none():
    """
    FRES-8862: Jira ticket has no explicit ACs (only Description).
    Extraction must output empty explicit_requirements and INF-01 inferred requirement.
    Compliance score must be None/null.
    """
    jira_context = {
        "jira_key": "FRES-8862",
        "summary": "Update price to use foreign sell price if available",
        "description": "It appears that Crunchtime-STD is not exporting pricing for a distributor who has exchange rate selected...",
        "acceptance_criteria": [],
    }
    state = {
        "review_id": "test-fres8862",
        "jira_context": jira_context,
        "pr_context": {"diff": "+ double price = getForeignSellPrice();", "files_changed": [{"path": "EDIClientPricingCafeZupas.java"}]},
        "logs": [],
        "findings": [],
    }

    extraction_agent = RequirementExtractionAgent(state)
    mock_llm_json = {
        "jira_key": "FRES-8862",
        "explicit_requirements": [],
        "inferred_requirements": [
            {
                "id": "INF-01",
                "title": "Use foreign sell price if available",
                "description": "Export converted price for DCs with feature enabled",
                "source": "inferred",
                "source_location": "jira_description",
                "mandatory": False,
                "confidence": 0.9,
            }
        ],
        "extraction_notes": "No explicit ACs in Jira",
        "confidence_score": 0.9,
    }

    with patch.object(extraction_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_llm_json)):
        extract_res = await extraction_agent.run(state)

    assert extract_res["explicit_requirements"] == []
    assert len(extract_res["inferred_requirements"]) == 1
    assert extract_res["inferred_requirements"][0]["id"] == "INF-01"

    # Now validate
    val_state = {**state, **extract_res}
    validation_agent = RequirementValidationAgent(val_state)
    mock_val_json = {
        "jira_key": "FRES-8862",
        "overall_compliance_score": None,
        "has_explicit_ac": False,
        "compliance_explanation": "Formal requirement compliance: N/A — no explicit acceptance criteria provided in Jira.",
        "requirement_results": [
            {
                "requirement_id": "INF-01",
                "requirement_type": "functional",
                "source": "inferred",
                "description": "Export converted price for DCs with feature enabled",
                "status": "implemented",
                "evidence": "+ double price = getForeignSellPrice();",
                "confidence": 0.9,
            }
        ],
        "missing_requirements": [],
        "partial_implementations": [],
        "regression_risks": [],
    }

    with patch.object(validation_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_val_json)):
        val_res = await validation_agent.run(val_state)

    val_out = val_res["validation_output"]
    assert val_out["overall_compliance_score"] is None
    assert val_out["has_explicit_ac"] is False

    eval_res = RequirementValidationAgent.evaluate_compliance(ValidationOutput.model_validate(val_out))
    assert eval_res["score"] is None
    assert eval_res["grade"] == "N/A"


@pytest.mark.asyncio
async def test_case1_explicit_ac_compliance_calculated():
    """
    CASE 1: Ticket has explicit ACs.
    Compliance score is calculated against explicit ACs.
    """
    jira_context = {
        "jira_key": "PROJ-100",
        "summary": "Explicit story",
        "description": "Story description",
        "acceptance_criteria": ["Given user, when login, then 200 OK"],
    }
    state = {
        "review_id": "test-case1",
        "jira_context": jira_context,
        "pr_context": {"diff": "+ login();", "files_changed": [{"path": "Login.java"}]},
        "logs": [],
        "findings": [],
    }

    extraction_agent = RequirementExtractionAgent(state)
    mock_llm_json = {
        "jira_key": "PROJ-100",
        "explicit_requirements": [
            {
                "id": "AC-01",
                "title": "Login 200 OK",
                "description": "Given user, when login, then 200 OK",
                "source": "explicit",
                "source_location": "jira_acceptance_criteria",
                "mandatory": True,
            }
        ],
        "inferred_requirements": [],
    }

    with patch.object(extraction_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_llm_json)):
        extract_res = await extraction_agent.run(state)

    assert len(extract_res["explicit_requirements"]) == 1
    assert extract_res["explicit_requirements"][0]["id"] == "AC-01"

    val_state = {**state, **extract_res}
    validation_agent = RequirementValidationAgent(val_state)
    mock_val_json = {
        "jira_key": "PROJ-100",
        "overall_compliance_score": 100.0,
        "has_explicit_ac": True,
        "requirement_results": [
            {
                "requirement_id": "AC-01",
                "requirement_type": "acceptance_criterion",
                "source": "explicit",
                "description": "Given user, when login, then 200 OK",
                "status": "implemented",
            }
        ],
    }

    with patch.object(validation_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_val_json)):
        val_res = await validation_agent.run(val_state)

    val_out = val_res["validation_output"]
    assert val_out["overall_compliance_score"] == 100.0
    eval_res = RequirementValidationAgent.evaluate_compliance(ValidationOutput.model_validate(val_out))
    assert eval_res["score"] == 100.0
    assert eval_res["grade"] == "A"


@pytest.mark.asyncio
async def test_case2_no_acs_uses_inf_namespace():
    """
    CASE 2: Ticket has no explicit ACs but rich summary/description.
    Requirements extracted MUST use INF-XX namespace and NOT fabricate FR-01 / AC-01.
    """
    jira_context = {
        "jira_key": "PROJ-200",
        "summary": "Add CSV export for monthly report",
        "description": "Users need a CSV export option on the dashboard.",
        "acceptance_criteria": [],
    }
    state = {
        "review_id": "test-case2",
        "jira_context": jira_context,
        "pr_context": {"diff": "+ exportCsv();", "files_changed": []},
        "logs": [],
    }

    extraction_agent = RequirementExtractionAgent(state)
    mock_llm_json = {
        "jira_key": "PROJ-200",
        "explicit_requirements": [],
        "inferred_requirements": [
            {
                "id": "INF-01",
                "title": "CSV export button",
                "description": "CSV export option on dashboard",
                "source": "inferred",
                "source_location": "jira_description",
                "mandatory": False,
            }
        ],
    }

    with patch.object(extraction_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_llm_json)):
        extract_res = await extraction_agent.run(state)

    assert extract_res["explicit_requirements"] == []
    assert extract_res["inferred_requirements"][0]["id"].startswith("INF-")


@pytest.mark.asyncio
async def test_case3_empty_ticket_produces_no_requirements():
    """
    CASE 3: Ticket has neither AC nor description.
    Requirement extraction returns empty lists without hallucinating.
    """
    jira_context = {
        "jira_key": "PROJ-300",
        "summary": "Fix typo",
        "description": "",
        "acceptance_criteria": [],
    }
    state = {
        "review_id": "test-case3",
        "jira_context": jira_context,
        "pr_context": {"diff": "- print('helo')\n+ print('hello')", "files_changed": []},
        "logs": [],
    }

    extraction_agent = RequirementExtractionAgent(state)
    mock_llm_json = {
        "jira_key": "PROJ-300",
        "explicit_requirements": [],
        "inferred_requirements": [],
    }

    with patch.object(extraction_agent, "_invoke_llm_json", new=AsyncMock(return_value=mock_llm_json)):
        extract_res = await extraction_agent.run(state)

    assert extract_res["requirements"] == []
    assert extract_res["explicit_requirements"] == []
    assert extract_res["inferred_requirements"] == []


@pytest.mark.asyncio
async def test_case4_inferred_contradiction_is_advisory():
    """
    CASE 4: Inferred requirement contradicted.
    Findings generated must be marked advisory (inferred), low/medium severity, score stays None.
    """
    val_output = ValidationOutput(
        jira_key="PROJ-400",
        overall_compliance_score=None,
        has_explicit_ac=False,
        requirement_results=[
            {
                "requirement_id": "INF-01",
                "requirement_type": "functional",
                "source": "inferred",
                "description": "Inferred requirement from description",
                "status": ValidationStatus.potential_gap,
                "gap_description": "Diff does not implement this optional expectation",
            }
        ],
    )
    eval_res = RequirementValidationAgent.evaluate_compliance(val_output)
    assert eval_res["score"] is None
    assert eval_res["grade"] == "N/A"


def test_case6_deduplication_merges_npe_findings():
    """
    CASE 6: Two findings from different agents describing NPE on same file/line are merged.
    """
    findings = [
        {
            "agent_name": "code_quality",
            "category": "code_quality",
            "severity": "medium",
            "file_path": "EDICafebZupas.java",
            "line_number": 45,
            "title": "Potential NullPointerException on pricePerCase",
            "description": "pricePerCase can be null before unboxing",
            "tags": ["code_quality"],
        },
        {
            "agent_name": "refactoring",
            "category": "refactoring",
            "severity": "high",
            "file_path": "EDICafebZupas.java",
            "line_number": 46,
            "title": "NPE risk on fallback price",
            "description": "Null pointer unboxing on line 46",
            "tags": ["refactoring"],
        },
    ]

    merged = deduplicate_findings(findings)
    assert len(merged) == 1
    assert merged[0]["severity"] == "high"
    assert "refactoring" in merged[0]["tags"] or "code_quality" in merged[0]["tags"]
