"""
SQL Performance Review Agent
——————————————————————————————
Node:    sql_performance
Layer 1: SQLGlot + SQLFluff static analysis  (fast, deterministic)
Layer 2: GPT-5 contextual analysis           (catches ORM patterns, index hints)

Detects:
  N+1 queries | SELECT * | Missing pagination | Full table scans
  Missing indexes | Cartesian joins | Large IN clauses

Output: ReviewFindings with severity, evidence, and index suggestions
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_openai import ChatOpenAI

from app.agents.base_agent import BaseAgent
from app.agents.models.sql_models import (
    SqlAntiPattern,
    SqlIssueSource,
    SqlPerformanceIssue,
    SqlPerformanceOutput,
    StaticAnalysisSummary,
)
from app.agents.sql_static_analyser import StaticAnalysisResult, StaticSqlAnalyser
from app.agents.state import FindingDict, ReviewState
from app.core.logging import get_logger

log = get_logger(__name__)


# ── System Prompt (Layer 2 — GPT-5) ──────────────────────────────────────────

SYSTEM_PROMPT = """
You are a Database Performance Engineer and SQL optimisation expert.

Static analysis has already flagged some issues (provided below).
Your job is to perform DEEPER analysis on the code diff — catch issues the static tools missed.

## Focus Areas

### N+1 Queries
- ORM loops: `for item in results: item.related_entity` (lazy loading)
- Spring JPA: missing `@EntityGraph`, `JOIN FETCH` not used
- SQLAlchemy: `session.query()` inside a loop
- Django: `.filter()` inside a loop without `prefetch_related`/`select_related`

### SELECT *
- `findAll()` returning full entities when only 2-3 fields needed → suggest DTO projections
- GraphQL resolvers fetching entire rows

### Missing Pagination
- API endpoints returning lists without page/size parameters
- Repository methods returning `List<Entity>` with no limit
- Cursor-based pagination missing on high-volume endpoints

### Full Table Scans
- WHERE on non-indexed column (infer from column names: status, type, category)
- LIKE '%value' patterns
- Functions on indexed columns: `WHERE YEAR(created_at) = 2024`

### Missing Indexes
- Foreign keys without indexes (e.g. `order.user_id` — common omission)
- Composite index needed: frequent `WHERE a = ? AND b = ?` queries
- ORDER BY on unindexed column

### Cartesian Joins
- Multiple tables in FROM without JOIN: `FROM a, b WHERE a.id = b.id` (old-style)
- Missing ON clause

### Large IN Clauses
- `WHERE id IN (...)` from application code building dynamic lists
- `IN` subquery that could be a JOIN

## Rules
- Reference specific file paths and line numbers visible in the diff
- Provide `index_suggestion` as valid SQL DDL when suggesting indexes
- Do NOT repeat findings already covered in static_issues list
- SEVERITY CALIBRATION:
  * Potential or low-impact optimizations ("Possible N+1 pattern; verify query count under load") -> LOW or MEDIUM severity recommendations.
  * Clear, PR-introduced massive performance defects (e.g., executing DB query in a loop for every invoice/record) -> HIGH.
  * Pre-existing N+1 issues on unchanged code -> recommendation / pre-existing (0 PR risk).

## Output Format
Return ONLY valid JSON:
{
  "issues": [
    {
      "id": "SQL-01",
      "anti_pattern": "n_plus_one|select_star|missing_pagination|full_table_scan|missing_index|cartesian_join|large_in_clause|unbounded_query|implicit_conversion|missing_transaction",
      "severity": "critical|high|medium|low|info",
      "source": "gpt5",
      "file_path": "path/to/file or null",
      "line_number": null,
      "sql_snippet": "relevant code or SQL snippet",
      "title": "concise issue title",
      "description": "detailed explanation",
      "impact": "performance impact description",
      "recommendation": "concrete fix",
      "review_comment": "markdown comment for the PR reviewer",
      "estimated_rows": "estimate or null",
      "index_suggestion": "CREATE INDEX ... or null",
      "confidence": 0.0-1.0
    }
  ],
  "analysis_notes": "overall observations"
}
""".strip()


# ── LangGraph Node Function ───────────────────────────────────────────────────

async def sql_performance_node(state: ReviewState) -> dict:
    """LangGraph node — runs static + LLM SQL performance analysis."""
    agent = SqlPerformanceAgent(state)
    return await agent.run(state)


# ── Agent Implementation ──────────────────────────────────────────────────────

class SqlPerformanceAgent(BaseAgent):
    name     = "sql_performance"
    category = "sql_performance"

    def _get_llm(self, temperature: float = 0.05):
        return super()._get_llm(temperature=temperature, json_mode=True)

    async def run(self, state: ReviewState) -> dict:
        logs      = list(state.get("logs", []))
        pr_ctx    = state.get("pr_context", {})
        diff      = pr_ctx.get("diff", "")
        files     = pr_ctx.get("files_changed", [])

        # Quick relevance check — skip if no SQL signals
        if not self._has_sql_content(diff, files):
            logs.append(self._make_log("No SQL patterns detected — skipping SQL analysis.", "info"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 50}

        log.info("agent.sql_performance.start", review_id=self._review_id, files=len(files))

        # ── Layer 1: Static Analysis ─────────────────────────────────────────
        static_result = self._run_static_analysis(files, diff)
        logs.append(self._make_log(
            f"Static analysis: {static_result.sql_blocks_found} SQL blocks scanned, "
            f"{len(static_result.issues)} static issue(s) found."
        ))

        # ── Layer 2: GPT-5 Contextual Analysis ───────────────────────────────
        llm_issues: list[SqlPerformanceIssue] = []
        try:
            user_prompt = self._build_prompt(diff, files, static_result, state)
            raw_json    = await self._invoke_llm_json(
                SYSTEM_PROMPT,
                user_prompt,
                context_mode="diff_only",
                repository_context=False,
                diff_chars=len(diff),
                context_chars=0,
            )
            llm_issues  = self._parse_llm_output(raw_json, len(static_result.issues))
            logs.append(self._make_log(f"GPT-5 found {len(llm_issues)} additional issue(s)."))
        except Exception as exc:
            log.error("agent.sql_performance.llm_failed", error=str(exc))
            logs.append(self._make_log(f"GPT-5 analysis failed (static results preserved): {exc}", "warning"))

        # ── Merge & deduplicate ───────────────────────────────────────────────
        static_issues = self._static_to_model(static_result)
        all_issues    = self._deduplicate(static_issues + llm_issues)

        output = SqlPerformanceOutput(
            issues=all_issues,
            static_summary=StaticAnalysisSummary(
                files_scanned=static_result.files_scanned,
                sql_blocks_found=static_result.sql_blocks_found,
                select_star_count=static_result.select_star_count,
                missing_limit_count=static_result.missing_limit_count,
                cartesian_count=static_result.cartesian_count,
                large_in_count=static_result.large_in_count,
                sqlfluff_errors=static_result.sqlfluff_errors,
            ),
            sql_files_found=static_result.sql_files,
        )

        findings  = self._to_findings(output)
        existing  = list(state.get("findings", []))

        logs.append(self._make_log(
            f"SQL analysis complete — {len(all_issues)} total issue(s), "
            f"overall severity: {output.overall_severity}."
        ))

        log.info("agent.sql_performance.complete",
                 review_id=self._review_id,
                 total_issues=len(all_issues),
                 severity=output.overall_severity)

        return {
            "findings":        existing + findings,
            "sql_output":      output.model_dump(),
            "logs":            logs,
            "current_agent":   self.name,
            "progress_percent": 50,
        }

    # ── Static analysis ───────────────────────────────────────────────────────

    def _run_static_analysis(self, files: list[dict], diff: str) -> StaticAnalysisResult:
        try:
            analyser = StaticSqlAnalyser()
            return analyser.analyse(files, diff)
        except Exception as exc:
            log.error("agent.sql_performance.static_failed", error=str(exc))
            return StaticAnalysisResult()

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        diff: str,
        files: list[dict],
        static_result: StaticAnalysisResult,
        state: Optional[dict] = None,
    ) -> str:
        static_summary = self._format_static_issues(static_result)
        files_block    = "\n".join(
            f"  {f.get('path')}  (+{f.get('lines_added',0)} / -{f.get('lines_removed',0)})"
            for f in files[:15]
        )

        return f"""## Changed Files
{files_block}

## Static Analysis Already Found These Issues (DO NOT REPEAT):
{static_summary}

## Code Diff (analyse for additional SQL/ORM performance issues):
```diff
{diff}
```

Find SQL performance issues NOT already listed in the static analysis above.
Return JSON only."""

    @staticmethod
    def _format_static_issues(result: StaticAnalysisResult) -> str:
        if not result.issues:
            return "  (none found by static analysis)"
        lines = []
        for i, issue in enumerate(result.issues[:10], 1):
            lines.append(f"  {i}. [{issue.severity.upper()}] {issue.title} — {issue.file_path}")
        return "\n".join(lines)

    # ── Parse LLM output ─────────────────────────────────────────────────────

    def _parse_llm_output(self, raw: dict, id_offset: int) -> list[SqlPerformanceIssue]:
        issues = raw.get("issues", [])
        result = []
        valid_patterns = {p.value for p in SqlAntiPattern}
        valid_severities = {"critical", "high", "medium", "low", "info"}

        for i, item in enumerate(issues[:15]):
            pattern = item.get("anti_pattern", "unbounded_query")
            if pattern not in valid_patterns:
                pattern = "unbounded_query"

            severity = str(item.get("severity", "medium")).lower()
            if severity not in valid_severities:
                severity = "medium"

            try:
                result.append(SqlPerformanceIssue(
                    id=f"SQL-{id_offset + i + 1:02d}",
                    anti_pattern=SqlAntiPattern(pattern),
                    severity=severity,
                    source=SqlIssueSource.llm_gpt5,
                    file_path=item.get("file_path"),
                    line_number=item.get("line_number"),
                    sql_snippet=item.get("sql_snippet"),
                    title=item.get("title", "SQL performance issue"),
                    description=item.get("description", ""),
                    impact=item.get("impact", "Unknown performance impact."),
                    recommendation=item.get("recommendation", ""),
                    review_comment=item.get("review_comment") or item.get("description", ""),
                    estimated_rows=item.get("estimated_rows"),
                    index_suggestion=item.get("index_suggestion"),
                    confidence=float(item.get("confidence", 0.75)),
                ))
            except Exception as exc:
                log.debug("sql_agent.parse_issue_failed", error=str(exc))

        return result

    # ── Convert static issues to model ────────────────────────────────────────

    @staticmethod
    def _static_to_model(result: StaticAnalysisResult) -> list[SqlPerformanceIssue]:
        issues = []
        pattern_map = {
            "select_star":        SqlAntiPattern.select_star,
            "missing_pagination": SqlAntiPattern.missing_pagination,
            "cartesian_join":     SqlAntiPattern.cartesian_join,
            "large_in_clause":    SqlAntiPattern.large_in_clause,
            "n_plus_one":         SqlAntiPattern.n_plus_one,
            "full_table_scan":    SqlAntiPattern.full_table_scan,
        }
        for i, s in enumerate(result.issues):
            pattern = pattern_map.get(s.anti_pattern, SqlAntiPattern.unbounded_query)
            source  = (
                SqlIssueSource.static_sqlfluff
                if "SQLFluff" in s.title
                else SqlIssueSource.static_sqlglot
            )
            issues.append(SqlPerformanceIssue(
                id=f"SQL-{i+1:02d}",
                anti_pattern=pattern,
                severity=s.severity,
                source=source,
                file_path=s.file_path,
                line_number=s.line_number,
                sql_snippet=s.sql_snippet,
                title=s.title,
                description=s.description,
                impact="Direct query performance impact.",
                recommendation=s.recommendation,
                review_comment=(
                    f"**[{source.value.upper()}] {s.title}**\n\n"
                    f"{s.description}\n\n"
                    f"**Fix:** {s.recommendation}"
                    + (f"\n\n```sql\n{s.index_suggestion}\n```" if s.index_suggestion else "")
                ),
                index_suggestion=s.index_suggestion,
                confidence=0.95,  # static tools are deterministic
            ))
        return issues

    # ── Deduplicate ───────────────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(issues: list[SqlPerformanceIssue]) -> list[SqlPerformanceIssue]:
        """Remove LLM issues that duplicate static findings (same file + pattern)."""
        static_keys = {
            (i.file_path, i.anti_pattern)
            for i in issues
            if i.source != SqlIssueSource.llm_gpt5
        }
        result = []
        for issue in issues:
            if issue.source == SqlIssueSource.llm_gpt5:
                key = (issue.file_path, issue.anti_pattern)
                if key in static_keys:
                    continue
            result.append(issue)
        return result

    # ── Convert to ReviewFindings ─────────────────────────────────────────────

    def _to_findings(self, output: SqlPerformanceOutput) -> list[FindingDict]:
        findings = []
        for issue in output.issues:
            findings.append(self._make_finding(
                severity=issue.severity,
                category="sql_performance",
                title=f"[{issue.anti_pattern.value.replace('_',' ').title()}] {issue.title}",
                description=issue.description,
                recommendation=issue.recommendation,
                review_comment=issue.review_comment,
                file_path=issue.file_path,
                line_number=issue.line_number,
                evidence=issue.sql_snippet,
                confidence_score=issue.confidence,
                tags=[issue.anti_pattern.value, issue.source.value],
            ))
        return findings

    # ── Relevance check ───────────────────────────────────────────────────────

    @staticmethod
    def _has_sql_content(diff: str, files: list[dict]) -> bool:
        sql_signals = ["select ", "insert ", "update ", "delete from", "join ", "where ",
                       "findby", "repository", "@query", "createquery", "nativequery",
                       "session.query", ".filter(", "queryset"]
        diff_lower = diff.lower()
        return any(sig in diff_lower for sig in sql_signals)
