"""
Code Context Service & Local Repository Manager
Provides local repository code context indexing, changed method detection,
on-demand method retrieval, class/component structure extraction, symbol searching,
and per-review shared caching across AI agents for Java and TypeScript/Angular repositories.
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger
from app.services.code_parser.java_parser import JavaCodeParser
from app.services.code_parser.typescript_parser import TypeScriptCodeParser
from app.services.git_worktree_service import GitWorktreeManager

logger = get_logger(__name__)


# Global review-scoped cache storage: review_id -> Dict
_PER_REVIEW_CACHE: Dict[str, Dict[str, Any]] = {}


class CodeContextService:
    """
    Code Context & Local Repository Manager layer for ReviewAI.
    Enables agents to query class/component structures and on-demand method implementations
    from the exact PR source commit worktree without sending full files to LLMs.
    """

    def __init__(self, review_id: str, worktree_manager: Optional[GitWorktreeManager] = None):
        self.review_id = review_id
        self.worktree_manager = worktree_manager or GitWorktreeManager()
        self.audit = ReviewAuditLogger(review_id)

        if review_id not in _PER_REVIEW_CACHE:
            _PER_REVIEW_CACHE[review_id] = {
                "worktree_path": "",
                "source_commit": "",
                "repo_slug": "",
                "changed_files": [],
                "changed_methods": [],
                "class_structures": {},  # file_path / class_name -> structure dict
                "methods_cache": {},     # "ClassName.methodName" -> method dict
                "files_cache": {},       # file_path -> content
                "metrics": {
                    "class_structures_requested": 0,
                    "methods_requested": 0,
                    "search_calls": 0,
                    "reference_calls": 0,
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "total_context_chars": 0,
                },
            }
        self.cache = _PER_REVIEW_CACHE[review_id]

    async def initialize_review_context(
        self,
        workspace: str,
        repo_slug: str,
        source_commit: str,
        diff_text: str,
        changed_files: List[Dict[str, Any]],
        source_branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initializes the local repository worktree, indexes changed files (Java & TypeScript/Angular),
        detects changed methods, and populates initial class structures.
        """
        logger.info(
            "[CodeContext] Initializing local repository context",
            review_id=self.review_id,
            repo_slug=repo_slug,
            commit=source_commit,
            branch=source_branch,
        )

        try:
            worktree_path = await self.worktree_manager.prepare_worktree(
                repo_slug=repo_slug,
                source_commit=source_commit,
                review_id=self.review_id,
                source_branch=source_branch,
            )
            self.cache["worktree_path"] = worktree_path
            self.cache["source_commit"] = source_commit
            self.cache["repo_slug"] = repo_slug
            self.cache["changed_files"] = changed_files

            # Extract changed methods from diff and worktree offloaded to thread
            changed_methods = await asyncio.to_thread(
                self.detect_changed_methods, diff_text, worktree_path, changed_files
            )
            self.cache["changed_methods"] = changed_methods

            # Index class/component structures for changed files offloaded to thread
            def _index_files():
                count = 0
                wt_path = Path(worktree_path)
                for f in changed_files:
                    file_path = (f.get("new") or f.get("old") or {}).get("path", "")
                    if not file_path:
                        continue

                    full_path = wt_path / file_path
                    if full_path.exists():
                        try:
                            code = full_path.read_text(encoding="utf-8", errors="replace")
                            struct = None
                            if file_path.endswith(".java"):
                                struct = JavaCodeParser.parse_class_structure(code, file_path)
                            elif file_path.endswith(".ts") or file_path.endswith(".tsx"):
                                struct = TypeScriptCodeParser.parse_class_structure(code, file_path, worktree_path)
                            elif file_path.endswith(".html"):
                                struct = {
                                    "file_path": file_path,
                                    "class": Path(file_path).name,
                                    "kind": "template",
                                    "template_content": code,
                                }

                            if struct:
                                self.cache["class_structures"][file_path] = struct
                                if struct.get("class"):
                                    self.cache["class_structures"][struct["class"]] = struct
                                count += 1
                        except Exception as e:
                            logger.warning(f"[CodeContext] Failed indexing class structure for {file_path}: {e}")
                return count

            indexed_count = await asyncio.to_thread(_index_files)

            logger.info(
                "[CodeContext] Code Index created",
                review_id=self.review_id,
                indexed_classes=indexed_count,
                changed_methods_count=len(changed_methods),
            )
            self.audit.log_workflow_event(
                "code_index_created",
                data={
                    "indexed_classes": indexed_count,
                    "changed_methods_count": len(changed_methods),
                    "worktree_path": worktree_path,
                },
            )

            return {
                "worktree_path": worktree_path,
                "source_commit": source_commit,
                "repo_slug": repo_slug,
                "indexed_classes_count": indexed_count,
                "changed_methods_count": len(changed_methods),
                "has_local_context": bool(worktree_path and (indexed_count > 0 or len(changed_methods) > 0)),
            }

        except Exception as exc:
            logger.error(
                "[CodeContext] Initialization failed, falling back to diff-only context",
                review_id=self.review_id,
                error=str(exc),
            )
            self.audit.log_workflow_event("code_context_fallback", data={"error": str(exc)})
            return {
                "worktree_path": "",
                "source_commit": source_commit,
                "repo_slug": repo_slug,
                "indexed_classes_count": 0,
                "changed_methods_count": 0,
                "has_local_context": False,
                "error": str(exc),
            }

    def detect_changed_methods(
        self,
        diff_text: str,
        worktree_path: str,
        changed_files: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Parses diff chunks and correlates modified line ranges with method definitions
        in worktree Java/TypeScript files to list modified/added/deleted methods.
        """
        changed_methods = []
        if not diff_text or not worktree_path:
            return changed_methods

        wt_path = Path(worktree_path)

        # Parse diff per file
        current_file = None
        lines = diff_text.splitlines()
        file_hunks: Dict[str, List[tuple[int, int]]] = {}

        for line in lines:
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    current_file = b_path[2:] if b_path.startswith("b/") else b_path
                    file_hunks[current_file] = []
            elif line.startswith("@@ ") and current_file:
                match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if match:
                    start_l = int(match.group(1))
                    count = int(match.group(2)) if match.group(2) else 1
                    file_hunks[current_file].append((start_l, count))

        for file_path, hunks in file_hunks.items():
            is_java = file_path.endswith(".java")
            is_ts = file_path.endswith(".ts") or file_path.endswith(".tsx")

            if not (is_java or is_ts):
                continue

            full_p = wt_path / file_path
            if not full_p.exists():
                continue

            try:
                code = full_p.read_text(encoding="utf-8", errors="replace")
                if is_java:
                    struct = JavaCodeParser.parse_class_structure(code, file_path)
                    parser_fn = JavaCodeParser.extract_method_implementation
                else:
                    struct = TypeScriptCodeParser.parse_class_structure(code, file_path)
                    parser_fn = TypeScriptCodeParser.extract_method_implementation

                class_name = struct.get("class", Path(file_path).stem)

                for method in struct.get("methods", []):
                    m_line = method.get("line_number", 0)
                    m_name = method.get("name", "")

                    # Check if method line range intersects any diff hunk
                    for start_l, count in hunks:
                        if abs(m_line - start_l) <= count or (start_l <= m_line <= start_l + count):
                            method_impl = parser_fn(code, m_name, file_path)
                            changed_methods.append({
                                "file_path": file_path,
                                "class_name": class_name,
                                "method_name": m_name,
                                "return_type": method.get("returnType"),
                                "parameters": method.get("parameters", []),
                                "line_number": m_line,
                                "implementation": method_impl.get("body") if method_impl else None,
                            })
                            break
            except Exception as e:
                logger.warning(f"Error detecting changed methods in {file_path}: {e}")

        return changed_methods

    # ── Context Retrieval Tools ───────────────────────────────────────────────

    def get_class_structure(self, class_or_file: str) -> Optional[Dict[str, Any]]:
        """
        Tool: get_class_structure(class_or_file)
        Returns class/component structure (annotations, fields, methods WITHOUT body).
        Uses per-review cache and tracks usage metrics.
        """
        metrics = self.cache.setdefault("metrics", {
            "class_structures_requested": 0, "methods_requested": 0,
            "search_calls": 0, "reference_calls": 0,
            "cache_hits": 0, "cache_misses": 0, "total_context_chars": 0,
        })
        metrics["class_structures_requested"] += 1

        if class_or_file in self.cache["class_structures"]:
            metrics["cache_hits"] += 1
            res = self.cache["class_structures"][class_or_file]
            metrics["total_context_chars"] += len(str(res))
            logger.info("[CodeContext] Class structure cache HIT", target=class_or_file)
            return res

        metrics["cache_misses"] += 1
        worktree_path = self.cache.get("worktree_path")
        if not worktree_path:
            return None

        wt_path = Path(worktree_path)

        # Attempt to find file in worktree
        target_file = None
        if (wt_path / class_or_file).exists():
            target_file = wt_path / class_or_file
        else:
            for ext in (".java", ".ts", ".tsx"):
                matches = list(wt_path.rglob(f"{class_or_file}{ext}"))
                if matches:
                    target_file = matches[0]
                    break

        if not target_file or not target_file.exists():
            return None

        try:
            code = target_file.read_text(encoding="utf-8", errors="replace")
            rel_path = str(target_file.relative_to(wt_path))
            if target_file.name.endswith(".java"):
                struct = JavaCodeParser.parse_class_structure(code, rel_path)
            elif target_file.name.endswith(".html"):
                struct = {
                    "file_path": rel_path,
                    "class": target_file.name,
                    "kind": "template",
                    "template_content": code,
                }
            else:
                struct = TypeScriptCodeParser.parse_class_structure(code, rel_path, worktree_path)

            self.cache["class_structures"][class_or_file] = struct
            self.cache["class_structures"][rel_path] = struct
            metrics["total_context_chars"] += len(str(struct))
            return struct
        except Exception as e:
            logger.error(f"[CodeContext] Failed reading class structure for {class_or_file}: {e}")
            return None

    def get_template_content(self, class_or_file: str) -> Optional[str]:
        """Tool: get_template_content(class_or_file) - Returns HTML template content for Angular component or HTML file."""
        struct = self.get_class_structure(class_or_file)
        if struct and struct.get("template_content"):
            return struct["template_content"]

        worktree_path = self.cache.get("worktree_path")
        if worktree_path:
            tmpl_url = struct.get("template_url") if struct else class_or_file
            if tmpl_url:
                return TypeScriptCodeParser.extract_template_content(worktree_path, tmpl_url)
        return None

    def get_method(self, class_name: str, method_name: str, signature: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Tool: get_method(class, method, optional_signature)
        On-demand retrieval of exact method implementation.
        Uses per-review cache and tracks usage metrics.
        """
        metrics = self.cache.setdefault("metrics", {
            "class_structures_requested": 0, "methods_requested": 0,
            "search_calls": 0, "reference_calls": 0,
            "cache_hits": 0, "cache_misses": 0, "total_context_chars": 0,
        })
        metrics["methods_requested"] += 1

        cache_key = f"{class_name}.{method_name}"
        if cache_key in self.cache["methods_cache"]:
            metrics["cache_hits"] += 1
            res = self.cache["methods_cache"][cache_key]
            metrics["total_context_chars"] += len(str(res))
            logger.info("[CodeContext] Method cache HIT", key=cache_key)
            return res

        metrics["cache_misses"] += 1
        worktree_path = self.cache.get("worktree_path")
        if not worktree_path:
            return None

        struct = self.get_class_structure(class_name)
        file_path = struct.get("file_path") if struct else None

        wt_path = Path(worktree_path)
        if not file_path:
            for ext in (".java", ".ts", ".tsx"):
                matches = list(wt_path.rglob(f"{class_name}{ext}"))
                if matches:
                    file_path = str(matches[0].relative_to(wt_path))
                    break

        if not file_path or not (wt_path / file_path).exists():
            return None

        try:
            target_p = wt_path / file_path
            code = target_p.read_text(encoding="utf-8", errors="replace")
            if target_p.name.endswith(".java"):
                impl = JavaCodeParser.extract_method_implementation(code, method_name, file_path)
            else:
                impl = TypeScriptCodeParser.extract_method_implementation(code, method_name, file_path)

            if impl:
                self.cache["methods_cache"][cache_key] = impl
                metrics["total_context_chars"] += len(str(impl))
                logger.info("[CodeContext] Retrieved method implementation", key=cache_key)
                return impl
        except Exception as e:
            logger.error(f"[CodeContext] Failed retrieving method {cache_key}: {e}")

        return None

    def search_code(self, query: str) -> List[Dict[str, Any]]:
        """Tool: search_code(query) - Search symbols in Java and TypeScript/Angular files in worktree."""
        metrics = self.cache.setdefault("metrics", {
            "class_structures_requested": 0, "methods_requested": 0,
            "search_calls": 0, "reference_calls": 0,
            "cache_hits": 0, "cache_misses": 0, "total_context_chars": 0,
        })
        metrics["search_calls"] += 1

        worktree_path = self.cache.get("worktree_path")
        if not worktree_path:
            return []

        res_java = JavaCodeParser.find_symbols_in_repo(worktree_path, query)
        res_ts = TypeScriptCodeParser.find_symbols_in_repo(worktree_path, query)
        total = res_java + res_ts
        metrics["total_context_chars"] += len(str(total))
        return total[:50]

    def find_references(self, symbol: str) -> List[Dict[str, Any]]:
        """Tool: find_references(symbol) - Find callers or usages of a symbol."""
        metrics = self.cache.setdefault("metrics", {
            "class_structures_requested": 0, "methods_requested": 0,
            "search_calls": 0, "reference_calls": 0,
            "cache_hits": 0, "cache_misses": 0, "total_context_chars": 0,
        })
        metrics["reference_calls"] += 1

        worktree_path = self.cache.get("worktree_path")
        if not worktree_path:
            return []

        res_java = JavaCodeParser.find_references_in_repo(worktree_path, symbol)
        res_ts = TypeScriptCodeParser.find_references_in_repo(worktree_path, symbol)
        total = res_java + res_ts
        metrics["total_context_chars"] += len(str(total))
        return total[:50]

    def get_imports(self, file_path: str) -> List[str]:
        """Tool: get_imports(file) - Get list of imported packages/modules for a file."""
        struct = self.get_class_structure(file_path)
        return struct.get("imports", []) if struct else []

    def get_usage_metrics(self) -> Dict[str, Any]:
        """Returns a snapshot of CodeContext usage metrics for audit logging."""
        return dict(self.cache.get("metrics", {}))

    async def cleanup(self) -> None:
        """Clean up review worktree and clear per-review cache."""
        repo_slug = self.cache.get("repo_slug", "")
        if self.review_id:
            if repo_slug:
                await self.worktree_manager.cleanup_worktree(repo_slug, self.review_id)
            _PER_REVIEW_CACHE.pop(self.review_id, None)
            logger.info("[CodeContext] Cleaned up code context service", review_id=self.review_id)
