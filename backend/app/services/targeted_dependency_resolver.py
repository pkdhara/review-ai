"""
Targeted Dependency Resolver for ReviewAI.

Performs deterministic dependency extraction from PR diffs and fetches minimal,
highly-relevant repository code snippets (domain models, DAO SQL queries, getters/setters,
service implementations) to populate `targeted_context` for specialist agents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.logging import get_logger
from app.services.code_parser.java_parser import JavaCodeParser
from app.services.code_parser.typescript_parser import TypeScriptCodeParser

logger = get_logger(__name__)

# Strict Context Budget Limits
MAX_TARGETED_FILES = 5
MAX_TARGETED_SYMBOLS = 10
MAX_TARGETED_CONTEXT_CHARS = 20000

# Common Java/TS standard built-ins to ignore when extracting method calls
COMMON_BUILTINS = {
    "equals", "hashCode", "toString", "length", "size", "isEmpty", "get", "put",
    "add", "remove", "contains", "stream", "collect", "map", "filter", "forEach",
    "format", "substring", "indexOf", "split", "replace", "trim", "append",
    "set", "of", "toList", "toSet", "orElse", "orElseGet", "orElseThrow",
    "log", "info", "error", "warn", "debug", "trace", "print", "println",
}


class TargetedDependencyResolver:
    """
    Analyzes PR diffs deterministically to discover external dependencies and fetches
    the minimum required repository snippets (depth 1 to 3) within strict context budgets.
    """

    def __init__(self, worktree_path: Optional[str] = None):
        self.worktree_path = worktree_path

    def analyze_and_resolve(
        self,
        diff_text: str,
        changed_files: List[Dict[str, Any]],
        code_context_service: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Analyzes the PR diff, identifies dependency triggers, resolves relevant code snippets
        from the local worktree / repository index, and returns structured targeted_context.
        """
        if not diff_text:
            return self._empty_result(0)

        diff_chars = len(diff_text)

        # 1. Deterministically extract added/modified lines from diff
        added_lines, diff_file_paths = self._extract_diff_additions(diff_text)

        # 2. Identify dependency triggers and symbol candidates
        triggers, symbol_candidates = self._detect_dependency_triggers(added_lines)

        if not triggers or not symbol_candidates:
            logger.info("[TargetedContext] No dependency triggers found in diff — returning diff_only context")
            return self._empty_result(diff_chars)

        # 3. Resolve symbols against local worktree / index
        snippets, resolved_files, resolved_symbols, max_depth, truncated = self._resolve_symbol_snippets(
            symbol_candidates=symbol_candidates,
            diff_file_paths=diff_file_paths,
            code_context_service=code_context_service,
        )

        if not snippets:
            logger.info("[TargetedContext] Triggers found but no relevant repository snippets resolved")
            return self._empty_result(diff_chars, triggers=list(triggers))

        # 4. Format context text within context budget
        context_text = self._format_context_text(snippets)
        if len(context_text) > MAX_TARGETED_CONTEXT_CHARS:
            context_text = context_text[:MAX_TARGETED_CONTEXT_CHARS] + "\n...[targeted context truncated to budget limit]"
            truncated = True

        targeted_context_chars = len(context_text)

        result = {
            "has_targeted_context": True,
            "context_text": context_text,
            "targeted_files": resolved_files[:MAX_TARGETED_FILES],
            "targeted_symbols": resolved_symbols[:MAX_TARGETED_SYMBOLS],
            "dependency_triggers": list(triggers),
            "dependency_depth": max_depth,
            "diff_chars": diff_chars,
            "context_chars": targeted_context_chars,
            "targeted_context_chars": targeted_context_chars,
            "truncated": truncated,
        }

        logger.info(
            "[TargetedContext] Built targeted context",
            triggers=list(triggers),
            targeted_files_count=len(result["targeted_files"]),
            targeted_symbols_count=len(result["targeted_symbols"]),
            chars=targeted_context_chars,
            depth=max_depth,
        )
        return result

    def _empty_result(self, diff_chars: int, triggers: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "has_targeted_context": False,
            "context_text": "",
            "targeted_files": [],
            "targeted_symbols": [],
            "dependency_triggers": triggers or [],
            "dependency_depth": 0,
            "diff_chars": diff_chars,
            "context_chars": 0,
            "targeted_context_chars": 0,
            "truncated": False,
        }

    def _extract_diff_additions(self, diff_text: str) -> Tuple[List[str], Set[str]]:
        """Extracts + lines (excluding +++ headers, comments, imports) and file paths from diff."""
        added_lines = []
        file_paths = set()
        current_file = ""

        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    current_file = b_path[2:] if b_path.startswith("b/") else b_path
                    file_paths.add(current_file)
            elif line.startswith("+") and not line.startswith("+++"):
                raw_code = line[1:].strip()
                # Skip comments and imports
                if not raw_code or raw_code.startswith("//") or raw_code.startswith("/*") or raw_code.startswith("*") or raw_code.startswith("import "):
                    continue
                added_lines.append(raw_code)

        return added_lines, file_paths

    def _detect_dependency_triggers(self, added_lines: List[str]) -> Tuple[Set[str], List[Dict[str, Any]]]:
        """
        Scans added lines deterministically to detect trigger categories:
        - newly introduced getters/fields
        - newly introduced method/function calls
        - newly introduced property access
        - newly introduced database/DAO/SQL queries
        - service/controller/repository calls
        - changed constructor params
        - mapping/conversion logic
        - feature flags / configuration dependencies
        """
        triggers = set()
        candidates = []
        seen_candidates = set()

        for line in added_lines:
            # A. Newly introduced getters/fields (.getForeignSellPrice(), .isExchangeRateEnabled(), etc.)
            getter_matches = re.findall(r"\.((?:get|is|has)[A-Z]\w*)\s*\(", line)
            for g in getter_matches:
                if g not in COMMON_BUILTINS and g not in seen_candidates:
                    seen_candidates.add(g)
                    triggers.add("new_getter")
                    candidates.append({"type": "getter", "symbol": g, "line": line})

            # B. Newly introduced method/function calls (resolveSellPrice, calculate, etc.)
            method_matches = re.findall(r"(?:([a-zA-Z_]\w*)\.)?([a-zA-Z_]\w*)\s*\(", line)
            for obj, m in method_matches:
                if m not in COMMON_BUILTINS and not m.startswith("get") and not m.startswith("is") and m not in seen_candidates:
                    # Check if method call is meaningful (e.g. resolveSellPrice, getPricesBetweenDate, etc.)
                    if len(m) > 3 and m[0].islower():
                        seen_candidates.add(m)
                        triggers.add("method_call")
                        candidates.append({"type": "method", "symbol": m, "object": obj, "line": line})

            # C. Newly introduced property access (.foreignSellPrice)
            prop_matches = re.findall(r"\.([a-z][a-zA-Z0-9_]*[A-Z]\w*)", line)
            for p in prop_matches:
                if p not in COMMON_BUILTINS and p not in seen_candidates and "(" not in line[line.find(p):line.find(p)+len(p)+2]:
                    seen_candidates.add(p)
                    triggers.add("property_access")
                    candidates.append({"type": "property", "symbol": p, "line": line})

            # D. Database / DAO / SQL triggers
            if any(k in line for k in ["Dao", "Repository", "DAO", "repository", "ResultSet", "rs.get", "SELECT ", "JOIN ", "WHERE "]):
                triggers.add("dao_dependency")

            # E. Mapping / conversion logic
            if any(k in line for k in ["mapTo", "convert", "toDomain", "toEntity", "fromDto"]):
                triggers.add("mapping_logic")

            # F. Feature Flag / Config dependency
            if any(k in line for k in ["config.", "conf.", "isForeignExchangeEnabled", "useExchangeRatePrice", "featureFlag"]):
                triggers.add("config_dependency")

        return triggers, candidates

    def _resolve_symbol_snippets(
        self,
        symbol_candidates: List[Dict[str, Any]],
        diff_file_paths: Set[str],
        code_context_service: Optional[Any],
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str], int, bool]:
        """
        Resolves symbols against the worktree index to fetch domain definitions, getter/setter pair,
        DAO SQL queries, and same-file unchanged methods within context limits.
        """
        wt_path = Path(self.worktree_path) if self.worktree_path else None
        snippets = []
        resolved_files = []
        resolved_symbols = []
        max_depth = 1
        truncated = False

        if not wt_path or not wt_path.exists():
            return snippets, resolved_files, resolved_symbols, 0, False

        for cand in symbol_candidates[:MAX_TARGETED_SYMBOLS]:
            if len(snippets) >= MAX_TARGETED_FILES or len(resolved_symbols) >= MAX_TARGETED_SYMBOLS:
                truncated = True
                break

            sym = cand["symbol"]

            # Depth 1: If symbol is a getter (e.g. getForeignSellPrice), locate domain field + setter
            if cand["type"] == "getter" or sym.startswith("get"):
                field_name = sym[3:]
                field_name_lc = field_name[0].lower() + field_name[1:] if field_name else ""
                setter_name = "set" + field_name

                # Search domain models / DTOs for field, getter, setter
                domain_snippets = self._find_domain_field_snippets(wt_path, field_name_lc, sym, setter_name)
                for ds in domain_snippets:
                    if ds["file_path"] not in resolved_files:
                        resolved_files.append(ds["file_path"])
                    if sym not in resolved_symbols:
                        resolved_symbols.append(sym)
                    snippets.append(ds)

                # Depth 2: Trace upstream DAO / Repository methods populating this domain
                if field_name_lc:
                    dao_snippets = self._find_dao_population_snippets(wt_path, field_name_lc, cand.get("line", ""))
                    if dao_snippets:
                        max_depth = max(max_depth, 2)
                        for dao_s in dao_snippets:
                            if dao_s["file_path"] not in resolved_files:
                                resolved_files.append(dao_s["file_path"])
                            if dao_s["symbol"] not in resolved_symbols:
                                resolved_symbols.append(dao_s["symbol"])
                            snippets.append(dao_s)

            # Depth 1: If symbol is a method call (e.g. resolveSellPrice, getPricesBetweenDate)
            elif cand["type"] == "method":
                m_snippets = self._find_method_snippets(wt_path, sym)
                for ms in m_snippets:
                    if ms["file_path"] not in resolved_files:
                        resolved_files.append(ms["file_path"])
                    if sym not in resolved_symbols:
                        resolved_symbols.append(sym)
                    snippets.append(ms)

        # Step 5: Same-file unchanged method resolution for modified files
        same_file_snippets = self._find_same_file_unchanged_snippets(wt_path, diff_file_paths, symbol_candidates)
        for sfs in same_file_snippets:
            if sfs["file_path"] not in resolved_files:
                resolved_files.append(sfs["file_path"])
            snippets.append(sfs)

        return snippets[:MAX_TARGETED_FILES], resolved_files, resolved_symbols, max_depth, truncated

    def _find_domain_field_snippets(
        self, wt_path: Path, field_name: str, getter_name: str, setter_name: str
    ) -> List[Dict[str, Any]]:
        """Finds field declaration, getter, and setter in Domain / DTO / Entity classes."""
        snippets = []
        if not field_name:
            return snippets

        for ext in (".java", ".ts"):
            # Search for files ending with Domain, DTO, Entity, Model, or matching getter
            for java_file in wt_path.rglob(f"*{ext}"):
                fname = java_file.name
                if not any(k in fname for k in ["Domain", "DTO", "Dto", "Entity", "Model", "Price", "Export"]):
                    continue
                try:
                    code = java_file.read_text(encoding="utf-8", errors="replace")
                    if field_name in code or getter_name in code:
                        rel_p = str(java_file.relative_to(wt_path))
                        # Extract relevant lines around field/getter/setter
                        lines = code.splitlines()
                        relevant_lines = []
                        for idx, line in enumerate(lines, 1):
                            if field_name in line or getter_name in line or setter_name in line:
                                start = max(0, idx - 3)
                                end = min(len(lines), idx + 4)
                                chunk = "\n".join(lines[start:end])
                                relevant_lines.append(chunk)

                        if relevant_lines:
                            snippets.append({
                                "file_path": rel_p,
                                "symbol": getter_name,
                                "type": "domain_definition",
                                "snippet": f"// Domain / Model field definition in {fname}:\n" + "\n---\n".join(relevant_lines[:3]),
                            })
                            if len(snippets) >= 2:
                                return snippets
                except Exception:
                    pass
        return snippets

    def _find_dao_population_snippets(self, wt_path: Path, field_name: str, call_line: str) -> List[Dict[str, Any]]:
        """Finds DAO / Repository methods and SQL queries that populate or fetch the domain field."""
        snippets = []
        if not field_name:
            return snippets

        snake_field = re.sub(r'(?<!^)(?=[A-Z])', '_', field_name).lower()

        # Look for DAO files or methods called in the call line
        dao_method_match = re.search(r"([a-zA-Z0-9_]+Dao|[a-zA-Z0-9_]+Repository|[a-zA-Z0-9_]+Controller)\.([a-zA-Z0-9_]+)", call_line)
        target_method = dao_method_match.group(2) if dao_method_match else ""

        for java_file in wt_path.rglob("*.java"):
            fname = java_file.name
            if not ("Dao" in fname or "Repository" in fname or "Controller" in fname):
                continue
            try:
                code = java_file.read_text(encoding="utf-8", errors="replace")
                if target_method and target_method in code:
                    rel_p = str(java_file.relative_to(wt_path))
                    impl = JavaCodeParser.extract_method_implementation(code, target_method, rel_p)
                    if impl and impl.get("body"):
                        body = impl["body"]
                        snippets.append({
                            "file_path": rel_p,
                            "symbol": target_method,
                            "type": "dao_method",
                            "snippet": f"// Upstream DAO method definition in {rel_p}:\n{body[:2500]}",
                        })
                        return snippets
                elif (field_name in code or snake_field in code) or ("SELECT" in code or "rs.get" in code or "resultSet.get" in code):
                    rel_p = str(java_file.relative_to(wt_path))
                    lines = code.splitlines()
                    for idx, line in enumerate(lines, 1):
                        line_lower = line.lower()
                        if field_name in line or snake_field in line_lower or "select" in line_lower:
                            start = max(0, idx - 5)
                            end = min(len(lines), idx + 25)
                            chunk = "\n".join(lines[start:end])
                            snippets.append({
                                "file_path": rel_p,
                                "symbol": field_name,
                                "type": "dao_query",
                                "snippet": f"// DAO SQL query / mapping in {rel_p}:\n{chunk[:2000]}",
                            })
                            return snippets
            except Exception:
                pass
        return snippets

    def _find_method_snippets(self, wt_path: Path, method_name: str) -> List[Dict[str, Any]]:
        """Finds definition of a method across Java and TypeScript files in worktree."""
        snippets = []
        if method_name in COMMON_BUILTINS:
            return snippets

        for ext in (".java", ".ts"):
            for code_file in wt_path.rglob(f"*{ext}"):
                try:
                    code = code_file.read_text(encoding="utf-8", errors="replace")
                    if method_name in code and (f" {method_name}(" in code or f" {method_name}:" in code or f"function {method_name}" in code):
                        rel_p = str(code_file.relative_to(wt_path))
                        if ext == ".java":
                            impl = JavaCodeParser.extract_method_implementation(code, method_name, rel_p)
                        else:
                            impl = TypeScriptCodeParser.extract_method_implementation(code, method_name, rel_p)

                        if impl and impl.get("body"):
                            snippets.append({
                                "file_path": rel_p,
                                "symbol": method_name,
                                "type": "method_definition",
                                "snippet": f"// Method implementation in {rel_p}:\n{impl['body'][:2000]}",
                            })
                            if len(snippets) >= 2:
                                return snippets
                except Exception:
                    pass
        return snippets

    def _find_same_file_unchanged_snippets(
        self, wt_path: Path, diff_file_paths: Set[str], symbol_candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extracts unchanged method definitions from modified files when called by changed lines."""
        snippets = []
        for rel_p in diff_file_paths:
            file_p = wt_path / rel_p
            if not file_p.exists():
                continue
            try:
                code = file_p.read_text(encoding="utf-8", errors="replace")
                for cand in symbol_candidates:
                    sym = cand["symbol"]
                    if sym in code and (f" {sym}(" in code or f" {sym}:" in code):
                        if rel_p.endswith(".java"):
                            impl = JavaCodeParser.extract_method_implementation(code, sym, rel_p)
                        else:
                            impl = TypeScriptCodeParser.extract_method_implementation(code, sym, rel_p)
                        if impl and impl.get("body"):
                            snippets.append({
                                "file_path": rel_p,
                                "symbol": sym,
                                "type": "same_file_unchanged_method",
                                "snippet": f"// Same-file unchanged method in {rel_p}:\n{impl['body'][:1500]}",
                            })
                            if len(snippets) >= 2:
                                return snippets
            except Exception:
                pass
        return snippets

    def _format_context_text(self, snippets: List[Dict[str, Any]]) -> str:
        """Formats resolved snippets into clean, structured targeted context string."""
        output = [
            "Review the PR diff first. Additional repository context has been supplied only because the changed code depends on these specific symbols. Use this context only to validate the PR change. Do not search for unrelated issues in the supplied context.\n",
            "--- TARGETED REPOSITORY CONTEXT ---",
        ]

        seen_snippets = set()
        for s in snippets[:MAX_TARGETED_FILES]:
            key = f"{s['file_path']}:{s['symbol']}"
            if key in seen_snippets:
                continue
            seen_snippets.add(key)
            output.append(f"\n[File: {s['file_path']} | Symbol: {s['symbol']}]")
            output.append(s["snippet"])
            output.append("-" * 50)

        return "\n".join(output)
