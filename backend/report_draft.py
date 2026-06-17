from typing import Any

import pandas as pd

from narrator import generate_narrative_blocks


REPORT_TYPE = "daily_generation"


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _latest_row(calculation_result: dict) -> dict:
    summary = calculation_result.get("summary") or {}
    latest = summary.get("latest") or {}
    return {
        key: value
        for key, value in latest.items()
        if key not in ("metric_sources", "changes")
    }


def _infer_report_date(calculation_result: dict, report_date: str | None) -> str | None:
    if report_date:
        return report_date

    latest = _latest_row(calculation_result)
    if latest.get("date"):
        return str(latest["date"])

    summary = calculation_result.get("summary") or {}
    return summary.get("last_date")


def _collect_action_required(*results: dict | None) -> list[dict]:
    actions = []
    for result in results:
        if not result:
            continue
        actions.extend(result.get("action_required") or [])
    return actions


def _collect_warnings(*results: dict | None) -> list[str]:
    warnings = []
    for result in results:
        if not result:
            continue
        warnings.extend(result.get("warnings") or [])
    return warnings


def _draft_status(pending_approvals: list[dict], validation_result: dict | None) -> str:
    if validation_result and not validation_result.get("valid", False):
        return "blocked"
    if pending_approvals:
        return "needs_analyst_input"
    return "draft_ready"


def _extract_kpi_cards(chart_result: dict | None) -> list[dict]:
    for component in (chart_result or {}).get("chart_specs", []):
        if component.get("component_id") == "kpi_cards":
            return component.get("cards") or []
    return []


def _extract_tables(chart_result: dict | None) -> list[dict]:
    return [
        component
        for component in (chart_result or {}).get("chart_specs", [])
        if component.get("type") == "table"
    ]


def _extract_charts(chart_result: dict | None) -> list[dict]:
    return [
        component
        for component in (chart_result or {}).get("chart_specs", [])
        if component.get("type") not in {"kpi_cards", "table"}
    ]


def _answered_questions(answer_plan: dict | None) -> list[dict]:
    questions = []
    for item in (answer_plan or {}).get("plan_items", []):
        if item.get("source") != "standing_customer_question":
            continue
        questions.append({
            "question_text": item.get("question_text"),
            "answer_purpose": item.get("answer_purpose"),
            "status": item.get("status"),
            "required_metrics": item.get("required_metrics") or [],
            "missing_metrics": item.get("missing_metrics") or [],
            "components": item.get("components") or [],
            "approved_by_analyst": bool(item.get("approved_by_analyst")),
        })
    return questions


def _triggered_findings(insights_result: dict | None) -> list[dict]:
    return (insights_result or {}).get("findings") or []


def assemble_report_draft(
    customer_id: str,
    report_type: str = REPORT_TYPE,
    report_date: str | None = None,
    validation_result: dict | None = None,
    mapping_result: dict | None = None,
    calculation_result: dict | None = None,
    insights_result: dict | None = None,
    answer_plan: dict | None = None,
    chart_result: dict | None = None,
    narrative_result: dict | None = None,
) -> dict:
    """
    Assembles frontend-ready draft JSON from deterministic backend outputs.

    This function does not validate, calculate, run insights, or generate
    charts. It only packages already-computed outputs into a stable draft shape.
    """
    calculation_result = calculation_result or {}
    report_date = _infer_report_date(calculation_result, report_date)
    pending_approvals = _collect_action_required(
        calculation_result,
        insights_result,
        answer_plan,
        chart_result,
    )
    warnings = _collect_warnings(
        validation_result,
        mapping_result,
        calculation_result,
        insights_result,
        answer_plan,
        chart_result,
    )

    draft = {
        "customer_id": customer_id,
        "report_type": report_type,
        "report_date": report_date,
        "status": _draft_status(pending_approvals, validation_result),
        "metadata": {
            "validation_valid": (
                validation_result.get("valid") if validation_result else None
            ),
            "mapping_confirmed": (
                mapping_result.get("confirmed") if mapping_result else None
            ),
            "calculation_status": calculation_result.get("status"),
            "insights_status": (insights_result or {}).get("status"),
            "answer_plan_status": (answer_plan or {}).get("status"),
            "chart_status": (chart_result or {}).get("status"),
            "row_count": (calculation_result.get("summary") or {}).get("row_count"),
        },
        "latest_kpis": {
            key: _json_value(value)
            for key, value in _latest_row(calculation_result).items()
        },
        "kpi_cards": _extract_kpi_cards(chart_result),
        "answered_questions": _answered_questions(answer_plan),
        "triggered_findings": _triggered_findings(insights_result),
        "chart_specs": _extract_charts(chart_result),
        "tables": _extract_tables(chart_result),
        "pending_approvals": pending_approvals,
        "warnings": warnings,
        "skipped_charts": (chart_result or {}).get("skipped_charts") or [],
        "source_summary": {
            "validation": validation_result or {},
            "mapping": mapping_result or {},
            "calculation": {
                "valid": calculation_result.get("valid"),
                "status": calculation_result.get("status"),
                "summary": calculation_result.get("summary") or {},
            },
            "insights": {
                "valid": (insights_result or {}).get("valid"),
                "status": (insights_result or {}).get("status"),
                "rules_evaluated": (insights_result or {}).get("rules_evaluated"),
                "skipped_rules": (insights_result or {}).get("skipped_rules") or [],
            },
            "answer_plan": {
                "valid": (answer_plan or {}).get("valid"),
                "status": (answer_plan or {}).get("status"),
                "requested_components": (
                    (answer_plan or {}).get("requested_components") or []
                ),
            },
            "charts": {
                "valid": (chart_result or {}).get("valid"),
                "status": (chart_result or {}).get("status"),
                "chart_count": len((chart_result or {}).get("chart_specs") or []),
                "skipped_count": len((chart_result or {}).get("skipped_charts") or []),
            },
        },
    }

    if narrative_result is None:
        narrative_result = generate_narrative_blocks(draft)

    draft["narrative_blocks"] = narrative_result.get("narrative_blocks") or []
    draft["source_summary"]["narrative"] = {
        "valid": narrative_result.get("valid"),
        "status": narrative_result.get("status"),
        "block_count": len(draft["narrative_blocks"]),
    }

    return draft
