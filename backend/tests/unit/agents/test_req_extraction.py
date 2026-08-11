"""
Unit tests for RequirementExtractionAgent.
LLM calls are mocked — no real API keys required.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.agent_requirement_extraction import RequirementExtractionAgent, req_extraction_node
from app.agents.models.requirement_models import ExtractedRequirements
from app.agents.state import ReviewState


# ── Fixtures ─────────────────────────────────────────────────────────────────

MOCK_LLM_RESPONSE = {
    "jira_key": "PROJ-42",
    "functionalRequirements": [
        {"id": "FR-01", "title": "User login", "description": "Users must be able to log in with email and password.",
         "priority": "must", "source": "jira", "testable": True},
        {"id": "FR-02", "title": "JWT token", "description": "System must issue a JWT on successful login.",
         "priority": "must", "source": "inferred", "testable": True},
    ],
    "acceptanceCriteria": [
        {"id": "AC-01", "given": "a registered user", "when": "they submit valid credentials",
         "then": "they receive a 200 response with a JWT", "description": "Login success case", "priority": "must"},
        {"id": "AC-02", "given": "any user", "when": "they submit invalid credentials",
         "then": "they receive a 401 with an error message", "description": "Login failure case", "priority": "must"},
    ],
    "businessRules": [
        {"id": "BR-01", "description": "Passwords must be at least 8 characters.", "rationale": "Security policy", "impact": "high"},
    ],
    "apiRequirements": [
        {"id": "API-01", "method": "POST", "endpoint": "/api/auth/login",
         "description": "Authenticate user and return JWT", "request": "{email, password}", "response": "{token, expires_in}", "auth": "none"},
    ],
    "uiRequirements": [
        {"id": "UI-01", "component": "LoginComponent", "description": "Login form with email and password fields.",
         "user_action": "User fills form and clicks Submit", "system_response": "Redirects to dashboard on success"},
    ],
    "performanceRequirements": [
        {"id": "PERF-01", "description": "Login endpoint response time", "metric": "p95 latency", "threshold": "< 300ms", "scope": "api"},
    ],
    "extraction_notes": "Password reset flow not mentioned — assumed out of scope.",
    "confidence_score": 0.88,
}

BASE_STATE: ReviewState = {
    "review_id": "test-review-123",
    "workspace": "myworkspace",
    "repo_slug": "my-repo",
    "ai_provider": "openai",
    "ai_key": "sk-test",
    "jira_context": {
        "jira_key": "PROJ-42",
        "issue_type": "Story",
        "summary": "Implement user login with JWT",
        "description": "As a user, I want to log in using my email and password so that I receive a JWT token.",
        "acceptance_criteria": [
            "Given a registered user, when they submit valid credentials, then they receive a JWT.",
            "Given any user, when they submit invalid credentials, then they receive a 401.",
        ],
        "technical_notes": "Use RS256 JWT signed with private key stored in Vault.",
        "priority": "High",
        "status": "In Progress",
        "labels": ["auth", "security"],
        "story_points": 5,
    },
    "logs": [],
    "findings": [],
    "requirements": [],
}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRequirementExtractionAgent:

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        """Agent returns all 6 categories populated and stores flat requirements."""
        state = dict(BASE_STATE)
        agent = RequirementExtractionAgent(state)

        with patch.object(agent, "_invoke_llm_json", new=AsyncMock(return_value=MOCK_LLM_RESPONSE)):
            result = await agent.run(state)

        assert "requirements" in result
        assert "extracted_requirements" in result
        assert result["progress_percent"] == 26
        assert result["current_agent"] == "req_extraction"

        flat = result["requirements"]
        ids = [r["id"] for r in flat]
        assert "FR-01" in ids
        assert "AC-01" in ids
        assert "BR-01" in ids
        assert "API-01" in ids
        assert "UI-01" in ids
        assert "PERF-01" in ids

    @pytest.mark.asyncio
    async def test_pydantic_validation(self):
        """ExtractedRequirements model_validate works on well-formed output."""
        extracted = ExtractedRequirements.model_validate({
            "jira_key": "PROJ-42",
            "functional_requirements": MOCK_LLM_RESPONSE["functionalRequirements"],
            "acceptance_criteria":     MOCK_LLM_RESPONSE["acceptanceCriteria"],
            "business_rules":          MOCK_LLM_RESPONSE["businessRules"],
            "api_requirements":        MOCK_LLM_RESPONSE["apiRequirements"],
            "ui_requirements":         MOCK_LLM_RESPONSE["uiRequirements"],
            "performance_requirements": MOCK_LLM_RESPONSE["performanceRequirements"],
            "extraction_notes": MOCK_LLM_RESPONSE["extraction_notes"],
            "confidence_score": MOCK_LLM_RESPONSE["confidence_score"],
        })
        assert extracted.total_requirements == 8
        assert extracted.confidence_score == pytest.approx(0.88)
        assert extracted.functional_requirements[0].id == "FR-01"
        assert extracted.acceptance_criteria[0].given == "a registered user"

    @pytest.mark.asyncio
    async def test_no_jira_context(self):
        """Agent skips gracefully when jira_context is missing."""
        state = {**BASE_STATE, "jira_context": {}}
        agent = RequirementExtractionAgent(state)

        result = await agent.run(state)

        assert result["requirements"] == []
        assert any("skipped" in log["message"].lower() for log in result["logs"])

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        """Agent returns empty requirements and logs error on LLM failure."""
        state = dict(BASE_STATE)
        agent = RequirementExtractionAgent(state)

        with patch.object(agent, "_invoke_llm_json", new=AsyncMock(side_effect=Exception("API timeout"))):
            result = await agent.run(state)

        assert result["requirements"] == []
        assert "req_extraction" in result.get("agent_errors", {})
        assert any("failed" in log["message"].lower() for log in result["logs"])

    @pytest.mark.asyncio
    async def test_camelcase_normalisation(self):
        """Agent correctly maps camelCase LLM keys to snake_case Pydantic model."""
        state = dict(BASE_STATE)
        agent = RequirementExtractionAgent(state)

        with patch.object(agent, "_invoke_llm_json", new=AsyncMock(return_value=MOCK_LLM_RESPONSE)):
            result = await agent.run(state)

        extracted = ExtractedRequirements.model_validate(result["extracted_requirements"])
        assert len(extracted.functional_requirements) == 2
        assert len(extracted.acceptance_criteria) == 2

    @pytest.mark.asyncio
    async def test_node_function(self):
        """req_extraction_node wrapper calls the agent and returns state update."""
        state = dict(BASE_STATE)

        with patch(
            "app.agents.agent_requirement_extraction.RequirementExtractionAgent._invoke_llm_json",
            new=AsyncMock(return_value=MOCK_LLM_RESPONSE),
        ):
            result = await req_extraction_node(state)

        assert result["progress_percent"] == 26
        assert len(result["requirements"]) > 0

    @pytest.mark.asyncio
    async def test_partial_llm_output_handled(self):
        """Agent handles LLM omitting some categories without crashing."""
        partial_response = {
            "jira_key": "PROJ-42",
            "functionalRequirements": [
                {"id": "FR-01", "title": "Login", "description": "Users can log in.", "priority": "must", "testable": True}
            ],
            # Missing all other categories
            "confidence_score": 0.5,
        }
        state = dict(BASE_STATE)
        agent = RequirementExtractionAgent(state)

        with patch.object(agent, "_invoke_llm_json", new=AsyncMock(return_value=partial_response)):
            result = await agent.run(state)

        assert len(result["requirements"]) >= 1
        extracted = ExtractedRequirements.model_validate(result["extracted_requirements"])
        assert extracted.acceptance_criteria == []
        assert extracted.business_rules == []

    def test_flat_requirement_list_structure(self):
        """_flatten_to_requirement_list produces dicts with correct keys."""
        extracted = ExtractedRequirements.model_validate({
            "jira_key": "PROJ-1",
            "functional_requirements": [
                {"id": "FR-01", "title": "T", "description": "D", "priority": "must", "testable": True}
            ],
            "acceptance_criteria": [],
            "business_rules": [],
            "api_requirements": [],
            "ui_requirements": [],
            "performance_requirements": [],
        })
        flat = RequirementExtractionAgent._flatten_to_requirement_list(extracted)
        assert flat[0]["type"] == "functional"
        assert flat[0]["id"] == "FR-01"
        assert flat[0]["testable"] is True
