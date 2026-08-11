"""
Unit tests for TestCoverageAgent — excluding TypeScript (.ts) files from test coverage checking.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.agent_test_coverage import TestCoverageAgent
from app.agents.state import ReviewState


@pytest.mark.asyncio
async def test_ts_files_are_ignored_by_test_coverage_agent():
    state: ReviewState = {
        "review_id": "test-ts-coverage-ignored",
        "workspace": "ws",
        "repo_slug": "repo",
        "ai_provider": "openai",
        "ai_key": "sk-test",
        "pr_context": {
            "pr_number": 1,
            "pr_title": "Update product selection component",
            "diff": "diff --git a/product.component.ts b/product.component.ts\n+export class ProductComponent {}",
            "changed_files": [
                {"path": "src/app/product.component.ts", "lines_added": 10, "lines_removed": 0},
            ],
        },
        "findings": [],
        "logs": [],
    }

    agent = TestCoverageAgent(state)
    # LLM should not even be called when only TS files are changed
    with patch.object(agent, "_invoke_llm_json", new=AsyncMock(return_value=[])) as mock_llm:
        result = await agent.run(state)
        mock_llm.assert_not_called()

    assert len(result["findings"]) == 0
    assert any("skipping test coverage check" in l.get("message", "").lower() for l in result["logs"])


@pytest.mark.asyncio
async def test_java_files_are_checked_for_test_coverage():
    state: ReviewState = {
        "review_id": "test-java-coverage",
        "workspace": "ws",
        "repo_slug": "repo",
        "ai_provider": "openai",
        "ai_key": "sk-test",
        "pr_context": {
            "pr_number": 2,
            "pr_title": "Add ProductService",
            "diff": "diff --git a/ProductService.java b/ProductService.java\n+public class ProductService {}",
            "changed_files": [
                {"path": "src/main/java/ProductService.java", "lines_added": 20, "lines_removed": 0},
            ],
        },
        "findings": [],
        "logs": [],
    }

    mock_finding = {
        "title": "Missing unit test for ProductService",
        "description": "No test found for ProductService",
        "severity": "medium",
        "file_path": "src/main/java/ProductService.java",
    }

    agent = TestCoverageAgent(state)
    with patch.object(agent, "_invoke_llm_json", new=AsyncMock(return_value=[mock_finding])) as mock_llm:
        result = await agent.run(state)
        mock_llm.assert_called_once()

    assert len(result["findings"]) == 1
    assert result["findings"][0]["title"] == "Missing unit test for ProductService"
