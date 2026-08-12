"""
Pydantic v2 models for Requirement Extraction Agent output.
Includes explicit source tracking (explicit vs inferred vs verified_inferred) and provenance.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class RequirementSource(str, Enum):
    explicit = "explicit"
    inferred = "inferred"
    verified_inferred = "verified_inferred"
    jira = "jira"  # Legacy alias for explicit


class RequirementSourceLocation(str, Enum):
    jira_acceptance_criteria = "jira_acceptance_criteria"
    jira_summary = "jira_summary"
    jira_description = "jira_description"
    jira_comment = "jira_comment"
    pr_description = "pr_description"
    code_verification = "code_verification"


class RequirementItem(BaseModel):
    """Unified requirement item model with provenance and source tracking."""
    id: str = Field(..., description="Unique ID, e.g. AC-01 for explicit, INF-01 for inferred")
    title: str = Field(..., description="Short requirement title")
    description: str = Field(..., description="Full requirement description")
    source: RequirementSource = Field(default=RequirementSource.explicit, description="explicit | inferred | verified_inferred")
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_acceptance_criteria)
    mandatory: bool = Field(default=True, description="True for explicit ACs, False for inferred expectations")
    priority: str = Field(default="must", description="must | should | could")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    evidence: Optional[str] = Field(None, description="Optional supporting text from Jira or code")
    given: Optional[str] = Field(None, description="Given condition (Gherkin style)")
    when: Optional[str] = Field(None, description="When action")
    then: Optional[str] = Field(None, description="Then expected outcome")
    type: str = Field(default="acceptance_criterion", description="acceptance_criterion | functional | business_rule | api | ui | performance")


class FunctionalRequirement(BaseModel):
    id: str = Field(..., description="Unique ID, e.g. FR-01 or INF-01")
    title: str = Field(..., description="Short requirement title")
    description: str = Field(..., description="Full requirement description")
    priority: str = Field(default="must", description="must | should | could")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_description)
    mandatory: bool = Field(default=False)
    testable: bool = Field(default=True)


class AcceptanceCriterion(BaseModel):
    id: str = Field(..., description="e.g. AC-01")
    given: Optional[str] = Field(None, description="Given condition (Gherkin style)")
    when: Optional[str] = Field(None, description="When action")
    then: str = Field(..., description="Then expected outcome")
    description: str = Field(..., description="Plain-text criterion")
    priority: str = Field(default="must")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_acceptance_criteria)
    mandatory: bool = Field(default=True)


class BusinessRule(BaseModel):
    id: str = Field(..., description="e.g. BR-01 or INF-BR-01")
    description: str = Field(..., description="Business rule statement")
    rationale: str = Field(default="", description="Why this rule exists")
    impact: str = Field(default="medium", description="high | medium | low")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_description)
    mandatory: bool = Field(default=False)


class ApiRequirement(BaseModel):
    id: str = Field(..., description="e.g. API-01")
    method: Optional[str] = Field(None, description="GET | POST | PUT | DELETE | PATCH")
    endpoint: Optional[str] = Field(None, description="e.g. /api/reviews")
    description: str = Field(..., description="What this endpoint must do")
    request: Optional[str] = Field(None, description="Request payload description")
    response: Optional[str] = Field(None, description="Response shape description")
    auth: str = Field(default="required", description="required | optional | none")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_description)
    mandatory: bool = Field(default=False)


class UiRequirement(BaseModel):
    id: str = Field(..., description="e.g. UI-01")
    component: Optional[str] = Field(None, description="Angular component or page name")
    description: str = Field(..., description="UI/UX requirement description")
    user_action: Optional[str] = Field(None, description="What the user does")
    system_response: Optional[str] = Field(None, description="How the system responds")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_description)
    mandatory: bool = Field(default=False)


class PerformanceRequirement(BaseModel):
    id: str = Field(..., description="e.g. PERF-01")
    description: str = Field(..., description="Performance requirement")
    metric: Optional[str] = Field(None, description="e.g. p95 < 500ms, 99.9% uptime")
    threshold: Optional[str] = Field(None, description="Acceptable threshold value")
    scope: str = Field(default="api", description="api | db | ui | background")
    source: RequirementSource = Field(default=RequirementSource.explicit)
    source_location: RequirementSourceLocation = Field(default=RequirementSourceLocation.jira_description)
    mandatory: bool = Field(default=False)


class ExtractedRequirements(BaseModel):
    """Complete structured output of the Requirement Extraction Agent."""
    jira_key: str = Field(..., description="Source Jira issue key")
    explicit_requirements: List[RequirementItem] = Field(default_factory=list, description="Authoritative Jira AC requirements")
    inferred_requirements: List[RequirementItem] = Field(default_factory=list, description="Expectations derived from Summary/Description")
    
    # Backwards-compatible category lists
    functional_requirements: List[FunctionalRequirement] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(default_factory=list)
    business_rules: List[BusinessRule] = Field(default_factory=list)
    api_requirements: List[ApiRequirement] = Field(default_factory=list)
    ui_requirements: List[UiRequirement] = Field(default_factory=list)
    performance_requirements: List[PerformanceRequirement] = Field(default_factory=list)

    # Summary metadata
    total_requirements: int = Field(default=0)
    has_explicit_ac: bool = Field(default=False, description="True if Jira provided explicit ACs")
    extraction_notes: str = Field(default="", description="Agent notes on ambiguities")
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)

    def model_post_init(self, __context) -> None:
        self.has_explicit_ac = len(self.explicit_requirements) > 0 or len(self.acceptance_criteria) > 0
        self.total_requirements = (
            len(self.explicit_requirements)
            + len(self.inferred_requirements)
            + len(self.functional_requirements)
            + len(self.acceptance_criteria)
            + len(self.business_rules)
            + len(self.api_requirements)
            + len(self.ui_requirements)
            + len(self.performance_requirements)
        )
