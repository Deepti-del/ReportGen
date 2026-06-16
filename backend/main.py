import json
import math
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile

from answer_planner import build_answer_plan
from calculator import calculate_daily_kpis_from_excel
from charts import build_chart_specs
from database import (
    approve_insight_rule,
    get_calculation_profile,
    get_connection,
    get_customer_questions,
    get_insight_rules,
)
from formula_service import add_custom_formula, approve_suggested_formula
from insights import generate_insights
from models import (
    ApproveFormulaRequest,
    ApproveInsightRuleRequest,
    CalculateRequest,
    CalculationResponse,
    ProfileResponse,
    UploadResponse,
    ValidateRequest,
    ValidationResponse,
)
from report_draft import assemble_report_draft
from storage import get_upload_path, save_upload
from validator import validate_workbook


app = FastAPI(title="ReportGen API", version="0.1.0")


def _http_error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _sheet_if_exists(workbook: dict[str, pd.DataFrame], sheet_name: str) -> pd.DataFrame | None:
    return workbook.get(sheet_name)


def _filter_by_report_date(
    df: pd.DataFrame | None,
    report_date: str | None,
    date_column: str = "date",
) -> pd.DataFrame | None:
    if df is None or not report_date or date_column not in df.columns:
        return df
    dates = pd.to_datetime(df[date_column], errors="coerce").dt.strftime("%Y-%m-%d")
    return df[dates == report_date].copy()


def _supplementary_data(path: str, report_date: str | None) -> dict[str, pd.DataFrame]:
    try:
        workbook = pd.read_excel(path, sheet_name=None)
    except Exception:
        return {}

    data = {}
    daily_timeseries = _sheet_if_exists(workbook, "daily_timeseries")
    if daily_timeseries is not None:
        if report_date and "timestamp" in daily_timeseries.columns:
            timestamps = pd.to_datetime(
                daily_timeseries["timestamp"],
                errors="coerce",
            ).dt.strftime("%Y-%m-%d")
            daily_timeseries = daily_timeseries[timestamps == report_date].copy()
        data["daily_timeseries"] = daily_timeseries

    inverter_performance = _filter_by_report_date(
        _sheet_if_exists(workbook, "inverter_performance"),
        report_date,
    )
    if inverter_performance is not None:
        data["inverter_performance"] = inverter_performance

    return data


def _pending_profile_count(profile: dict, rules: list[dict], questions: list[dict]) -> int:
    pending = 0
    for category in ("required_source", "derivable", "optional", "reference"):
        pending += sum(
            1 for metric in profile.get(category, [])
            if not metric.get("approved_by_analyst")
        )
    pending += sum(1 for rule in rules if not rule.get("approved_by_analyst"))
    pending += sum(1 for question in questions if not question.get("approved_by_analyst"))
    return pending


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if pd.isna(value) if not isinstance(value, (dict, list, tuple)) else False:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (ValueError, TypeError):
            pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    try:
        file_id = save_upload(await file.read(), file.filename or "upload.xlsx")
    except ValueError as exc:
        raise _http_error(400, str(exc)) from exc

    return {
        "file_id": file_id,
        "filename": file.filename or "",
    }


@app.post("/validate", response_model=ValidationResponse)
def validate(request: ValidateRequest):
    try:
        path = get_upload_path(request.file_id)
    except FileNotFoundError as exc:
        raise _http_error(404, str(exc)) from exc

    result = validate_workbook(
        path,
        customer_id=request.customer_id,
        report_type=request.report_type,
    )

    return {
        "valid": result["valid"],
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
        "summary": result,
    }


@app.post("/calculate", response_model=CalculationResponse)
def calculate(request: CalculateRequest):
    try:
        path = get_upload_path(request.file_id)
    except FileNotFoundError as exc:
        raise _http_error(404, str(exc)) from exc

    validation = validate_workbook(
        path,
        customer_id=request.customer_id,
        report_type=request.report_type,
    )
    calculation = calculate_daily_kpis_from_excel(
        path,
        customer_id=request.customer_id,
        report_type=request.report_type,
    )
    insights = generate_insights(
        calculation,
        customer_id=request.customer_id,
        report_type=request.report_type,
    )
    answer_plan = build_answer_plan(
        calculation,
        customer_id=request.customer_id,
        report_type=request.report_type,
        insights_result=insights,
    )
    charts = build_chart_specs(
        calculation,
        answer_plan=answer_plan,
        supplementary_data=_supplementary_data(path, request.report_date),
    )
    draft = assemble_report_draft(
        customer_id=request.customer_id,
        report_type=request.report_type,
        report_date=request.report_date,
        validation_result=validation,
        mapping_result=calculation.get("mapping"),
        calculation_result=calculation,
        insights_result=insights,
        answer_plan=answer_plan,
        chart_result=charts,
    )

    return _jsonable({
        "customer_id": request.customer_id,
        "report_date": draft.get("report_date"),
        "kpis": draft.get("latest_kpis", {}),
        "findings": draft.get("triggered_findings", []),
        "pending_approval": draft.get("pending_approvals", []),
        "chart_specs": draft.get("chart_specs", []),
        "answer_plan": answer_plan,
        "warnings": draft.get("warnings", []),
        "draft": draft,
    })


@app.get("/profile/{customer_id}/{report_type}", response_model=ProfileResponse)
def profile(customer_id: str, report_type: str):
    calc_profile = get_calculation_profile(customer_id, report_type)
    insight_profile = get_insight_rules(
        customer_id,
        report_type,
        include_unapproved=True,
    )
    question_profile = get_customer_questions(
        customer_id,
        report_type,
        include_unapproved=True,
    )

    rules = insight_profile["rules"]
    questions = question_profile["questions"]

    return {
        "customer_id": customer_id,
        "report_type": report_type,
        "required_source": calc_profile["required_source"],
        "derivable": calc_profile["derivable"],
        "optional": calc_profile["optional"],
        "insight_rules": rules,
        "customer_questions": questions,
        "pending_approval_count": _pending_profile_count(
            calc_profile,
            rules,
            questions,
        ),
    }


@app.get("/customers")
def customers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            c.customer_id,
            c.customer_name,
            c.status,
            COUNT(r.report_id) AS report_count,
            MAX(r.report_date) AS last_report_date
        FROM customers c
        LEFT JOIN report_history r ON r.customer_id = c.customer_id
        GROUP BY c.customer_id, c.customer_name, c.status
        ORDER BY c.customer_name
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"customers": rows}


@app.post("/approve/formula")
def approve_formula_endpoint(request: ApproveFormulaRequest):
    customer_id = request.customer_id
    report_type = request.report_type
    if not customer_id or not report_type:
        raise _http_error(400, "customer_id and report_type are required.")

    if request.formula:
        if not request.output_column:
            raise _http_error(400, "output_column is required for a custom formula.")
        result = add_custom_formula(
            customer_id=customer_id,
            report_type=report_type,
            metric_name=request.metric_name,
            output_column=request.output_column,
            formula=request.formula,
            input_columns=request.input_columns,
            available_columns=request.input_columns,
            unit=request.unit,
            good_range=request.good_range,
            poor_threshold=request.poor_threshold,
            scope=request.scope,
        )
    else:
        result = approve_suggested_formula(
            customer_id=customer_id,
            report_type=report_type,
            output_column=request.output_column,
            metric_name=request.metric_name,
            scope=request.scope,
            available_columns=request.input_columns or None,
        )

    if not result.get("ok"):
        raise _http_error(400, result.get("message", "Formula approval failed."))

    return result


def _load_rule_by_id(rule_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM insight_rules WHERE rule_id = ?", (rule_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _json_or_value(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


@app.post("/approve/insight-rule")
def approve_insight_rule_endpoint(request: ApproveInsightRuleRequest):
    rule_data = _load_rule_by_id(request.rule_id) if request.rule_id else None

    rule_name = request.rule_name or request.display_name or (
        rule_data.get("rule_name") if rule_data else None
    )
    condition = request.condition or (rule_data.get("condition") if rule_data else None)
    customer_id = request.customer_id
    report_type = request.report_type

    if not rule_name or not condition:
        raise _http_error(400, "rule_name and condition are required.")
    if not customer_id or not report_type:
        raise _http_error(400, "customer_id and report_type are required.")

    result = approve_insight_rule(
        rule_name=rule_name,
        condition=condition,
        input_columns=(
            request.input_columns
            or _json_or_value(rule_data.get("input_columns") if rule_data else None, [])
        ),
        thresholds=(
            request.thresholds
            or _json_or_value(rule_data.get("thresholds") if rule_data else None, {})
        ),
        severity=request.severity or (rule_data.get("severity") if rule_data else "medium"),
        message_template=request.finding_template
        or (rule_data.get("message_template") if rule_data else None),
        suggestion_template=request.suggestion_template
        or (rule_data.get("suggestion_template") if rule_data else None),
        scope=request.scope,
        customer_id=customer_id,
        report_type=report_type,
    )
    return result
