"""
Static SQL analyser — Layer 1 of the SQL Performance Agent.

Uses:
  - SQLGlot  : parse SQL ASTs and detect structural anti-patterns
  - SQLFluff : lint raw SQL for style and correctness issues

Detects without any LLM call:
  SELECT *  |  Missing LIMIT  |  Cartesian JOIN  |  Large IN clauses
  SQLFluff rule violations (L019, L036, etc.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.logging import get_logger

log = get_logger(__name__)

# ── SQL block extraction ──────────────────────────────────────────────────────

# Matches SQL in Java/Python string literals and annotations
_SQL_PATTERNS = [
    # Spring @Query / @NativeQuery annotations
    r'@(?:Query|NativeQuery)\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    # Java/Python triple-quoted or concatenated strings containing SELECT
    r'["\']([^"\']*\bSELECT\b[^"\']+)["\']',
    # Python f-strings / format strings
    r'f["\']([^"\']*\bSELECT\b[^"\']+)["\']',
    # Pure .sql file content (whole block)
    r'(SELECT\b.+?)(?:;|$)',
]

_LARGE_IN_THRESHOLD = 20  # flag IN clauses with more than this many literals


@dataclass
class StaticIssue:
    anti_pattern: str
    severity:     str
    file_path:    str
    line_number:  Optional[int]
    sql_snippet:  str
    title:        str
    description:  str
    recommendation: str
    index_suggestion: Optional[str] = None


@dataclass
class StaticAnalysisResult:
    issues:            list[StaticIssue] = field(default_factory=list)
    files_scanned:     int = 0
    sql_blocks_found:  int = 0
    select_star_count: int = 0
    missing_limit_count: int = 0
    cartesian_count:   int = 0
    large_in_count:    int = 0
    sqlfluff_errors:   int = 0
    sql_files:         list[str] = field(default_factory=list)


class StaticSqlAnalyser:
    """
    Runs SQLGlot AST analysis + SQLFluff linting on all SQL blocks
    found in the changed files of a PR diff.
    """

    def analyse(self, files_changed: list[dict], diff: str) -> StaticAnalysisResult:
        result = StaticAnalysisResult()
        sql_files = self._identify_sql_files(files_changed)
        result.sql_files = [f["path"] for f in sql_files]
        result.files_scanned = len(sql_files)

        for file_info in sql_files:
            file_diff = file_info.get("diff", "")
            file_path = file_info.get("path", "unknown")

            blocks = self._extract_sql_blocks(file_diff, file_path)
            result.sql_blocks_found += len(blocks)

            for sql, line_num in blocks:
                self._analyse_with_sqlglot(sql, file_path, line_num, result)
                self._analyse_with_sqlfluff(sql, file_path, line_num, result)

        # Also scan full diff for ORM-level N+1 signals & leading wildcard LIKE
        self._detect_orm_patterns(diff, files_changed, result)
        self._detect_leading_wildcard_like(diff, files_changed, result)

        return result

    # ── File identification ───────────────────────────────────────────────────

    @staticmethod
    def _identify_sql_files(files_changed: list[dict]) -> list[dict]:
        sql_extensions  = {".sql", ".hql", ".ddl"}
        sql_name_hints  = {"dao", "repository", "mapper", "query", "jpa", "jdbc", "repository"}
        result = []
        for f in files_changed:
            path = f.get("path", "").lower()
            if any(path.endswith(ext) for ext in sql_extensions):
                result.append(f)
            elif any(hint in path for hint in sql_name_hints):
                result.append(f)
            elif "select" in f.get("diff", "").lower():
                result.append(f)
        return result

    # ── SQL block extraction ──────────────────────────────────────────────────

    def _extract_sql_blocks(self, text: str, file_path: str) -> list[tuple[str, Optional[int]]]:
        blocks: list[tuple[str, Optional[int]]] = []
        lines = text.splitlines()

        if file_path.endswith(".sql"):
            # Whole file is SQL — split on semicolons
            full = "\n".join(l.lstrip("+- ") for l in lines)
            for stmt in full.split(";"):
                stmt = stmt.strip()
                if any(stmt.upper().startswith(kw) for kw in ("SELECT", "UPDATE", "DELETE", "INSERT", "CREATE", "ALTER")):
                    blocks.append((stmt, None))
            return blocks

        # Extract from code strings
        cleaned = "\n".join(l.lstrip("+- ") for l in lines)
        for pattern in _SQL_PATTERNS:
            for match in re.finditer(pattern, cleaned, re.IGNORECASE | re.DOTALL):
                sql = match.group(1).strip()
                if len(sql) > 10 and any(kw in sql.upper() for kw in ("SELECT", "UPDATE", "DELETE")):
                    blocks.append((sql[:2000], None))

        return blocks

    # ── SQLGlot analysis ──────────────────────────────────────────────────────

    def _analyse_with_sqlglot(
        self,
        sql: str,
        file_path: str,
        line_number: Optional[int],
        result: StaticAnalysisResult,
    ) -> None:
        try:
            import sqlglot
            import sqlglot.expressions as exp

            tree = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.WARN)
            if tree is None:
                return

            # ── SELECT * ─────────────────────────────────────────────────────
            for star in tree.find_all(exp.Star):
                result.select_star_count += 1
                result.issues.append(StaticIssue(
                    anti_pattern="select_star",
                    severity="medium",
                    file_path=file_path,
                    line_number=line_number,
                    sql_snippet=sql[:200],
                    title="SELECT * used",
                    description="SELECT * retrieves all columns including unused ones, increasing I/O and breaking refactoring safety.",
                    recommendation="Specify only the columns you need: SELECT id, name, created_at FROM ...",
                ))

            # ── Missing LIMIT / FETCH ────────────────────────────────────────
            has_limit = bool(tree.find(exp.Limit)) or bool(tree.find(exp.Fetch))
            has_where = bool(tree.find(exp.Where))
            is_select = isinstance(tree, exp.Select)
            if is_select and not has_limit and not has_where:
                result.missing_limit_count += 1
                result.issues.append(StaticIssue(
                    anti_pattern="missing_pagination",
                    severity="high",
                    file_path=file_path,
                    line_number=line_number,
                    sql_snippet=sql[:200],
                    title="Unbounded query — no LIMIT or WHERE clause",
                    description="This SELECT has no LIMIT and no WHERE, which will scan the entire table as the dataset grows.",
                    recommendation="Add LIMIT/OFFSET for pagination or a selective WHERE clause.",
                ))

            # ── Cartesian JOIN (JOIN without ON) ─────────────────────────────
            for join in tree.find_all(exp.Join):
                if join.args.get("on") is None and join.args.get("using") is None:
                    join_type = join.args.get("kind", "")
                    if str(join_type).upper() not in ("CROSS",):
                        result.cartesian_count += 1
                        result.issues.append(StaticIssue(
                            anti_pattern="cartesian_join",
                            severity="critical",
                            file_path=file_path,
                            line_number=line_number,
                            sql_snippet=sql[:200],
                            title="Implicit Cartesian JOIN detected",
                            description="A JOIN without ON/USING produces a Cartesian product (M × N rows), catastrophic for large tables.",
                            recommendation="Add an explicit ON clause: JOIN table ON a.id = b.a_id",
                        ))

            # ── Large IN clause ───────────────────────────────────────────────
            for in_expr in tree.find_all(exp.In):
                expressions = in_expr.args.get("expressions", [])
                if len(expressions) > _LARGE_IN_THRESHOLD:
                    result.large_in_count += 1
                    result.issues.append(StaticIssue(
                        anti_pattern="large_in_clause",
                        severity="medium",
                        file_path=file_path,
                        line_number=line_number,
                        sql_snippet=f"IN ({len(expressions)} values)",
                        title=f"Large IN clause ({len(expressions)} literals)",
                        description=f"IN clauses with {len(expressions)} values cause full index scans and increase parse time.",
                        recommendation="Use a temporary table / JOIN against a values table, or batch the IDs.",
                    ))

            # ── Full table scan via LIKE '%...' ───────────────────────────────
            for like in tree.find_all(exp.Like):
                right = str(like.args.get("expression", ""))
                if right.startswith("'%"):
                    result.issues.append(StaticIssue(
                        anti_pattern="full_table_scan",
                        severity="medium",
                        file_path=file_path,
                        line_number=line_number,
                        sql_snippet=f"LIKE {right[:50]}",
                        title="Leading wildcard LIKE — index unusable",
                        description="LIKE '%value' cannot use a B-tree index and forces a full table scan.",
                        recommendation="Use LIKE 'value%' (trailing wildcard), full-text search, or a search index.",
                    ))

        except Exception as exc:
            log.debug("sqlglot.parse_failed", file=file_path, error=str(exc))

    # ── SQLFluff linting ──────────────────────────────────────────────────────

    def _analyse_with_sqlfluff(
        self,
        sql: str,
        file_path: str,
        line_number: Optional[int],
        result: StaticAnalysisResult,
    ) -> None:
        try:
            from sqlfluff.core import Linter

            linter  = Linter(dialect="ansi")
            parsed  = linter.parse_string(sql)
            linted  = linter.lint_string(sql)

            # Map SQLFluff rule codes to anti-patterns
            rule_map = {
                "L019": ("select_star",        "medium", "SELECT * detected by SQLFluff"),
                "L036": ("select_star",        "medium", "Single column select should not use *"),
                "L008": ("missing_pagination", "low",    "Trailing whitespace in SQL"),
                "AM04": ("select_star",        "medium", "Wildcard in SELECT"),
                "ST09": ("cartesian_join",     "high",   "Implicit cross-join detected"),
            }

            for violation in linted:
                code = getattr(violation, "rule_code", None) or str(violation)[:6]
                if code in rule_map:
                    pattern, severity, title = rule_map[code]
                    result.sqlfluff_errors += 1
                    result.issues.append(StaticIssue(
                        anti_pattern=pattern,
                        severity=severity,
                        file_path=file_path,
                        line_number=line_number,
                        sql_snippet=sql[:150],
                        title=f"[SQLFluff {code}] {title}",
                        description=str(violation),
                        recommendation="Fix the SQLFluff violation as described.",
                    ))

        except ImportError:
            log.debug("sqlfluff.not_installed — skipping lint step")
        except Exception as exc:
            log.debug("sqlfluff.lint_failed", file=file_path, error=str(exc))

    # ── ORM / code-level pattern detection ───────────────────────────────────

    def _detect_orm_patterns(
        self, diff: str, files_changed: list[dict], result: StaticAnalysisResult
    ) -> None:
        """
        Heuristic detection of N+1 and loop-based query patterns in ORM code
        (JPA, SQLAlchemy, Django ORM) — no SQL parser needed.
        """
        lines = diff.splitlines()

        # Pattern: repository call inside a for/while loop
        in_loop     = False
        loop_indent = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip("+ ")
            indent   = len(line) - len(line.lstrip())

            # Detect loop entry
            if re.search(r"\b(for|while|forEach|stream\(\))\b", stripped):
                in_loop     = True
                loop_indent = indent
                continue

            # Reset when indentation returns to loop level
            if in_loop and indent <= loop_indent and stripped and not stripped.startswith(("#", "//")):
                in_loop = False

            # DB call inside loop
            if in_loop and re.search(
                r"\b(findBy|findAll|getOne|fetch|execute|query|\.get\(|\.load\(|session\.)\b",
                stripped,
                re.IGNORECASE,
            ):
                file_path = self._guess_file(files_changed, i)
                result.issues.append(StaticIssue(
                    anti_pattern="n_plus_one",
                    severity="high",
                    file_path=file_path,
                    line_number=i + 1,
                    sql_snippet=stripped[:150],
                    title="Potential N+1 query inside loop",
                    description=(
                        "A repository/database call appears inside a loop. "
                        "This typically causes N+1 queries — one query per iteration."
                    ),
                    recommendation=(
                        "Use batch loading: findAllById(ids), JOIN FETCH, or eager loading. "
                        "For JPA: @EntityGraph or a single query returning all needed data."
                    ),
                    index_suggestion=None,
                ))

    def _detect_leading_wildcard_like(
        self, diff: str, files_changed: list[dict], result: StaticAnalysisResult
    ) -> None:
        """
        Scan diff text for leading wildcard LIKE expressions (e.g. LIKE '%-null' or LIKE '%-').
        """
        lines = diff.splitlines()
        like_pattern = r"\bLIKE\s+['\"]%[^'\"]+['\"]"
        for i, line in enumerate(lines):
            if line.startswith("+") and not line.startswith("+++"):
                stripped = line[1:].strip()
                for match in re.finditer(like_pattern, stripped, re.IGNORECASE):
                    file_path = self._guess_file(files_changed, i)
                    snippet = match.group(0)
                    result.issues.append(StaticIssue(
                        anti_pattern="full_table_scan",
                        severity="medium",
                        file_path=file_path,
                        line_number=i + 1,
                        sql_snippet=snippet,
                        title="Leading wildcard LIKE expression detected",
                        description=f"Expression `{snippet}` uses a leading wildcard, preventing B-tree index usage and causing a full table scan.",
                        recommendation="Use trailing wildcards (LIKE 'val%'), generated columns with reverse indexes, or full-text indexing.",
                        index_suggestion=None,
                    ))

    @staticmethod
    def _guess_file(files_changed: list[dict], line_idx: int) -> str:
        if files_changed:
            return files_changed[0].get("path", "unknown")
        return "unknown"
