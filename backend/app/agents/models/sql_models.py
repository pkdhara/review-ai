"""
Pydantic v2 models for SQL Performance Agent output.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class SqlAntiPattern(str, Enum):
    n_plus_one         = "n_plus_one"
    select_star        = "select_star"
    missing_pagination = "missing_pagination"
    full_table_scan    = "full_table_scan"
    missing_index      = "missing_index"
    cartesian_join     = "cartesian_join"
    large_in_clause    = "large_in_clause"
    unbounded_query    = "unbounded_query"
    implicit_conversion = "implicit_conversion"
    missing_transaction = "missing_transaction"


class SqlIssueSource(str, Enum):
    static_sqlglot  = "sqlglot"
    static_sqlfluff = "sqlfluff"
    llm_gpt5        = "gpt5"


class SqlPerformanceIssue(BaseModel):
    id:           str            = Field(..., description="e.g. SQL-01")
    anti_pattern: SqlAntiPattern
    severity:     str            = Field(..., description="critical | high | medium | low | info")
    source:       SqlIssueSource = Field(..., description="Which tool detected this")
    file_path:    Optional[str]  = None
    line_number:  Optional[int]  = None
    sql_snippet:  Optional[str]  = Field(None, description="Problematic SQL or ORM code")
    title:        str
    description:  str
    impact:       str            = Field(..., description="Query / DB performance impact")
    recommendation: str
    review_comment: str
    estimated_rows: Optional[str] = Field(None, description="e.g. 'full table ~50k rows'")
    index_suggestion: Optional[str] = Field(None, description="e.g. 'CREATE INDEX ON orders(user_id)'")
    confidence:   float          = Field(default=0.8, ge=0.0, le=1.0)


class StaticAnalysisSummary(BaseModel):
    files_scanned:     int = 0
    sql_blocks_found:  int = 0
    select_star_count: int = 0
    missing_limit_count: int = 0
    cartesian_count:   int = 0
    large_in_count:    int = 0
    sqlfluff_errors:   int = 0


class SqlPerformanceOutput(BaseModel):
    issues:           list[SqlPerformanceIssue]   = Field(default_factory=list)
    static_summary:   StaticAnalysisSummary       = Field(default_factory=StaticAnalysisSummary)
    overall_severity: str                         = Field(default="low")
    sql_files_found:  list[str]                   = Field(default_factory=list)
    analysis_notes:   str                         = Field(default="")

    def model_post_init(self, __context) -> None:
        if not self.issues:
            self.overall_severity = "none"
            return
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        self.overall_severity = min(
            self.issues, key=lambda i: order.get(i.severity, 9)
        ).severity
