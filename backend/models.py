from typing import Any, Literal

from pydantic import BaseModel, Field


Scope = Literal["customer_report_type", "customer", "report_type", "global"]


class ValidateRequest(BaseModel):
    customer_id: str
    report_type: str = "daily_generation"
    report_date: str | None = Field(default=None, description="YYYY-MM-DD")
    file_id: str


class CalculateRequest(BaseModel):
    customer_id: str
    report_type: str = "daily_generation"
    report_date: str | None = Field(default=None, description="YYYY-MM-DD")
    file_id: str


class ApproveFormulaRequest(BaseModel):
    metric_name: str
    formula: str | None = None
    unit: str | None = None
    good_range: str | None = None
    poor_threshold: str | None = None
    scope: Scope = "customer_report_type"
    customer_id: str | None = None
    report_type: str | None = None
    output_column: str | None = None
    input_columns: list[str] = Field(default_factory=list)


class ApproveInsightRuleRequest(BaseModel):
    rule_id: int | None = None
    rule_name: str | None = None
    display_name: str | None = None
    condition: str | None = None
    input_columns: list[str] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    severity: str = "medium"
    finding_template: str | None = None
    suggestion_template: str | None = None
    scope: Scope = "customer_report_type"
    customer_id: str | None = None
    report_type: str | None = None


class UploadResponse(BaseModel):
    file_id: str
    filename: str


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[Any] = Field(default_factory=list)
    warnings: list[Any] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class CalculationResponse(BaseModel):
    customer_id: str
    report_date: str | None = None
    kpis: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    pending_approval: list[dict[str, Any]] = Field(default_factory=list)
    chart_specs: list[dict[str, Any]] = Field(default_factory=list)
    answer_plan: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    draft: dict[str, Any] = Field(default_factory=dict)


class ProfileResponse(BaseModel):
    customer_id: str
    report_type: str
    required_source: list[dict[str, Any]] = Field(default_factory=list)
    derivable: list[dict[str, Any]] = Field(default_factory=list)
    optional: list[dict[str, Any]] = Field(default_factory=list)
    insight_rules: list[dict[str, Any]] = Field(default_factory=list)
    customer_questions: list[dict[str, Any]] = Field(default_factory=list)
    pending_approval_count: int = 0
