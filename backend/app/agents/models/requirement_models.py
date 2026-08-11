"""
Pydantic v2 models for Requirement Extraction Agent output.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class FunctionalRequirement(BaseModel):
    id:          str           = Field(..., description="Unique ID, e.g. FR-01")
    title:       str           = Field(..., description="Short requirement title")
    description: str           = Field(..., description="Full requirement description")
    priority:    str           = Field(..., description="must | should | could")
    source:      str           = Field(default="jira", description="Where this req was derived from")
    testable:    bool          = Field(default=True)


class AcceptanceCriterion(BaseModel):
    id:          str           = Field(..., description="e.g. AC-01")
    given:       Optional[str] = Field(None, description="Given condition (Gherkin style)")
    when:        Optional[str] = Field(None, description="When action")
    then:        str           = Field(..., description="Then expected outcome")
    description: str           = Field(..., description="Plain-text criterion")
    priority:    str           = Field(default="must")


class BusinessRule(BaseModel):
    id:          str  = Field(..., description="e.g. BR-01")
    description: str  = Field(..., description="Business rule statement")
    rationale:   str  = Field(default="", description="Why this rule exists")
    impact:      str  = Field(default="medium", description="high | medium | low")


class ApiRequirement(BaseModel):
    id:          str           = Field(..., description="e.g. API-01")
    method:      Optional[str] = Field(None, description="GET | POST | PUT | DELETE | PATCH")
    endpoint:    Optional[str] = Field(None, description="e.g. /api/reviews")
    description: str           = Field(..., description="What this endpoint must do")
    request:     Optional[str] = Field(None, description="Request payload description")
    response:    Optional[str] = Field(None, description="Response shape description")
    auth:        str           = Field(default="required", description="required | optional | none")


class UiRequirement(BaseModel):
    id:          str           = Field(..., description="e.g. UI-01")
    component:   Optional[str] = Field(None, description="Angular component or page name")
    description: str           = Field(..., description="UI/UX requirement description")
    user_action: Optional[str] = Field(None, description="What the user does")
    system_response: Optional[str] = Field(None, description="How the system responds")


class PerformanceRequirement(BaseModel):
    id:          str           = Field(..., description="e.g. PERF-01")
    description: str           = Field(..., description="Performance requirement")
    metric:      Optional[str] = Field(None, description="e.g. p95 < 500ms, 99.9% uptime")
    threshold:   Optional[str] = Field(None, description="Acceptable threshold value")
    scope:       str           = Field(default="api", description="api | db | ui | background")


class ExtractedRequirements(BaseModel):
    """Complete structured output of the Requirement Extraction Agent."""
    jira_key:                str  = Field(..., description="Source Jira issue key")
    functional_requirements: list[FunctionalRequirement]  = Field(default_factory=list)
    acceptance_criteria:     list[AcceptanceCriterion]    = Field(default_factory=list)
    business_rules:          list[BusinessRule]           = Field(default_factory=list)
    api_requirements:        list[ApiRequirement]         = Field(default_factory=list)
    ui_requirements:         list[UiRequirement]          = Field(default_factory=list)
    performance_requirements: list[PerformanceRequirement] = Field(default_factory=list)

    # Summary metadata
    total_requirements: int  = Field(default=0)
    extraction_notes:   str  = Field(default="", description="Agent notes on ambiguities")
    confidence_score:   float = Field(default=0.8, ge=0.0, le=1.0)

    def model_post_init(self, __context) -> None:
        self.total_requirements = (
            len(self.functional_requirements)
            + len(self.acceptance_criteria)
            + len(self.business_rules)
            + len(self.api_requirements)
            + len(self.ui_requirements)
            + len(self.performance_requirements)
        )
