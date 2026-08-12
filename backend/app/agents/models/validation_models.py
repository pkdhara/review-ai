"""
Pydantic v2 models for Requirement Validation Agent output.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    implemented      = "implemented"
    partial          = "partial"
    missing          = "missing"
    violated         = "violated"
    potential_gap    = "potential_gap"
    not_applicable   = "not_applicable"
    cannot_determine = "cannot_determine"


class RegressionRiskLevel(str, Enum):
    high   = "high"
    medium = "medium"
    low    = "low"
    none   = "none"


# ── Per-requirement validation result ────────────────────────────────────────

class RequirementValidationResult(BaseModel):
    requirement_id:   str             = Field(..., description="e.g. AC-01 or INF-01")
    requirement_type: str             = Field(default="acceptance_criterion", description="functional | acceptance_criterion | business_rule | api | ui | performance")
    source:           str             = Field(default="explicit", description="explicit | inferred | verified_inferred")
    description:      str             = Field(..., description="Requirement text")
    status:           ValidationStatus = Field(..., description="Implementation status")
    evidence:         Optional[str]   = Field(None,  description="Code snippet or line proving status")
    file_path:        Optional[str]   = Field(None,  description="Relevant file")
    line_number:      Optional[int]   = Field(None)
    gap_description:  Optional[str]   = Field(None,  description="What is missing or violated")
    suggestion:       Optional[str]   = Field(None,  description="How to fix the gap")
    confidence:       float           = Field(default=0.8, ge=0.0, le=1.0)


# ── Regression risk ──────────────────────────────────────────────────────────

class RegressionRisk(BaseModel):
    id:            str                = Field(..., description="e.g. REG-01")
    risk_level:    RegressionRiskLevel
    area:          str                = Field(..., description="Feature area at risk")
    description:   str                = Field(..., description="What could regress and why")
    affected_files: List[str]         = Field(default_factory=list)
    mitigation:    str                = Field(..., description="Recommended mitigation")


# ── Missing requirement ───────────────────────────────────────────────────────

class MissingRequirement(BaseModel):
    requirement_id: str  = Field(..., description="e.g. AC-03 or INF-01")
    source:         str  = Field(default="explicit", description="explicit | inferred | verified_inferred")
    description:    str  = Field(..., description="What is missing")
    severity:       str  = Field(default="high", description="critical | high | medium | low | info")
    impact:         str  = Field(..., description="Business impact description")
    suggested_fix:  str  = Field(..., description="Code-level suggestion to implement this")


# ── Partial implementation ────────────────────────────────────────────────────

class PartialImplementation(BaseModel):
    requirement_id:     str           = Field(..., description="e.g. AC-01 or INF-01")
    source:             str           = Field(default="explicit", description="explicit | inferred | verified_inferred")
    description:        str           = Field(..., description="What is partially done")
    implemented_part:   str           = Field(..., description="What IS implemented")
    missing_part:       str           = Field(..., description="What is NOT implemented")
    file_path:          Optional[str] = None
    line_number:        Optional[int] = None
    severity:           str           = Field(default="medium")
    completion_percent: int           = Field(default=50, ge=0, le=100)


# ── Complete validation output ────────────────────────────────────────────────

class ValidationOutput(BaseModel):
    jira_key:                    str   = Field(...)
    overall_compliance_score:    Optional[float] = Field(None, ge=0.0, le=100.0,
                                                       description="Compliance score for EXPLICIT requirements (0-100), or None/null if no explicit ACs exist")
    has_explicit_ac:             bool  = Field(default=True, description="False if no explicit Jira ACs exist")
    compliance_explanation:      str   = Field(default="", description="Explanation of compliance score or N/A state")
    requirement_results:         List[RequirementValidationResult] = Field(default_factory=list)
    missing_requirements:        List[MissingRequirement]          = Field(default_factory=list)
    partial_implementations:     List[PartialImplementation]       = Field(default_factory=list)
    regression_risks:            List[RegressionRisk]              = Field(default_factory=list)
    validation_notes:            str   = Field(default="")

    # Computed summary counts for explicit requirements
    explicit_count:        int = Field(default=0)
    inferred_count:        int = Field(default=0)
    implemented_count:     int = Field(default=0)
    partial_count:         int = Field(default=0)
    missing_count:         int = Field(default=0)
    violated_count:        int = Field(default=0)
    high_regression_count: int = Field(default=0)

    def model_post_init(self, __context) -> None:
        self.explicit_count = sum(1 for r in self.requirement_results if r.source == "explicit")
        self.inferred_count = sum(1 for r in self.requirement_results if r.source != "explicit")
        
        self.implemented_count = sum(
            1 for r in self.requirement_results if r.status == ValidationStatus.implemented and r.source == "explicit"
        )
        self.partial_count = sum(
            1 for r in self.requirement_results if r.status == ValidationStatus.partial and r.source == "explicit"
        ) + sum(1 for p in self.partial_implementations if p.source == "explicit")
        
        self.missing_count = sum(
            1 for r in self.requirement_results if r.status == ValidationStatus.missing and r.source == "explicit"
        ) + sum(1 for m in self.missing_requirements if m.source == "explicit")
        
        self.violated_count = sum(
            1 for r in self.requirement_results if r.status == ValidationStatus.violated and r.source == "explicit"
        )
        self.high_regression_count = sum(
            1 for r in self.regression_risks if r.risk_level == RegressionRiskLevel.high
        )
