"""
Regression test suite for Bitbucket API Integration and Review Pipeline Guarding.
Covering PR diff retrieval, 401 authentication handling, diff completeness validation,
and partial diff protection.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.bitbucket_service import BitbucketService


# ── Fixtures & Mock Data ──────────────────────────────────────────────────────

MULTIFILE_DIFFSTAT = [
    {"new": {"path": "FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java"}},
    {"new": {"path": "FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java"}},
    {"new": {"path": "FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql"}},
]

MULTIFILE_DIFF_TEXT = """diff --git a/FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java b/FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java
index 1111111..2222222 100644
--- a/FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java
+++ b/FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java
@@ -10,6 +10,7 @@ public interface ProductDao {
+    void assignPaProductId(Long productId);
 }
diff --git a/FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java b/FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java
index 3333333..4444444 100644
--- a/FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java
+++ b/FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java
@@ -20,6 +20,7 @@ public class CbUnknownToolService {
+    // tool mapping implementation
 }
diff --git a/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql b/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
index 5555555..6666666 100644
--- a/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
+++ b/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
@@ -1,3 +1,5 @@
+CREATE PROCEDURE assign_pa_product_ids() BEGIN END;
"""

PARTIAL_DIFF_TEXT = """diff --git a/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql b/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
index 5555555..6666666 100644
--- a/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
+++ b/FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql
@@ -1,3 +1,5 @@
+CREATE PROCEDURE assign_pa_product_ids() BEGIN END;
"""

PR_METADATA_MOCK = {
    "title": "FRES-8705 generate pa product ids during mapping",
    "source": {"branch": {"name": "FRES-8705-feature"}, "commit": {"hash": "1a3eba0abfdc"}},
    "destination": {"branch": {"name": "staging"}, "commit": {"hash": "0aa4fc1c22ed"}},
    "author": {"display_name": "Developer"},
}


# ── Test Cases ────────────────────────────────────────────────────────────────

def test_parse_diff_file_paths():
    """Test 3: Diffstat consistency — verify parsed diff file paths match expectation."""
    paths = BitbucketService.parse_diff_file_paths(MULTIFILE_DIFF_TEXT)
    assert len(paths) == 3
    assert "FC-Backend/src/main/java/com/fc/backend/admin/product/dao/ProductDao.java" in paths
    assert "FC-Backend/src/main/java/com/fc/backend/common/invoice/centralbilling/service/CbUnknownToolService.java" in paths
    assert "FC-Backend/src/main/resources/db/migration/V8705_1__add_stored_procedure_to_assign_pa_product_ids.sql" in paths


@pytest.mark.asyncio
async def test_multifile_pr_diff_retrieval():
    """Test 1 & 2: Multi-file & Multi-commit PR context retrieval."""
    svc = BitbucketService(access_token="ATATT3xFf...token", email="test@domain.com")
    
    with patch.object(svc, "get_pull_request", new_callable=AsyncMock) as mock_get_pr, \
         patch.object(svc, "get_pr_diff", new_callable=AsyncMock) as mock_get_diff, \
         patch.object(svc, "get_changed_files", new_callable=AsyncMock) as mock_changed_files, \
         patch.object(svc, "get_commits", new_callable=AsyncMock) as mock_commits, \
         patch.object(svc, "get_existing_comments", new_callable=AsyncMock) as mock_comments:
        
        mock_get_pr.return_value = PR_METADATA_MOCK
        mock_get_diff.return_value = MULTIFILE_DIFF_TEXT
        mock_changed_files.return_value = MULTIFILE_DIFFSTAT
        mock_commits.return_value = [
            {"hash": "1a3eba0abfdc", "message": "FRES-8705 commit 3"},
            {"hash": "a037436adc12", "message": "FRES-8705 commit 2"},
            {"hash": "cc5d2e1641b3", "message": "FRES-8705 commit 1"},
        ]
        mock_comments.return_value = []

        ctx = await svc.build_pr_context("workspace", "repo", 5351)

        assert ctx["pr_number"] == 5351
        assert len(ctx["changed_files"]) == 3
        assert len(ctx["commits"]) == 3
        parsed = BitbucketService.parse_diff_file_paths(ctx["diff"])
        assert len(parsed) == 3
        assert ctx["jira_key"] == "FRES-8705"


@pytest.mark.asyncio
async def test_partial_diff_protection():
    """Test 7: Partial diff protection — raise ValueError when diff is missing files listed in diffstat."""
    svc = BitbucketService(access_token="ATATT3xFf...token", email="test@domain.com")
    
    with patch.object(svc, "get_pull_request", new_callable=AsyncMock) as mock_get_pr, \
         patch.object(svc, "get_pr_diff", new_callable=AsyncMock) as mock_get_diff, \
         patch.object(svc, "get_changed_files", new_callable=AsyncMock) as mock_changed_files, \
         patch.object(svc, "get_commits", new_callable=AsyncMock) as mock_commits, \
         patch.object(svc, "get_existing_comments", new_callable=AsyncMock) as mock_comments:
        
        mock_get_pr.return_value = PR_METADATA_MOCK
        mock_get_diff.return_value = PARTIAL_DIFF_TEXT  # Only 1 file
        mock_changed_files.return_value = MULTIFILE_DIFFSTAT  # 3 files expected
        mock_commits.return_value = [{"hash": "1a3eba0abfdc", "message": "FRES-8705 commit"}]
        mock_comments.return_value = []

        with pytest.raises(ValueError) as exc_info:
            await svc.build_pr_context("workspace", "repo", 5351)

        assert "Incomplete PR diff detected" in str(exc_info.value)
        assert "expected_changed_files=3" in str(exc_info.value)
        assert "diff_changed_files=1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_bitbucket_401_no_infinite_retry():
    """Test 4 & 6: Bitbucket 401 permanent failure — verify retries do not loop infinitely on 401."""
    svc = BitbucketService(access_token="invalid_token")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Client error 401 Unauthorized"
    err = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_resp)

    assert svc._is_transient_error(err) is False

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = err
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await svc._get("/repositories/workspace/repo/pullrequests/5351")
        
        # Verify it attempted exactly once without retrying 401
        assert mock_get.call_count == 1
        assert exc_info.value.response.status_code == 401


def test_auth_header_construction():
    """Test 5: Successful Basic Auth Header Construction for Atlassian Tokens."""
    svc = BitbucketService(access_token="ATATT3xFf...sampletoken", email="user@domain.com")
    auth_header = svc.headers.get("Authorization", "")
    assert auth_header.startswith("Basic ")
    assert "user@domain.com" not in auth_header  # should be base64 encoded
