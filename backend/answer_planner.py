import pandas as pd

from database import get_customer_questions


REPORT_TYPE = "daily_generation"

INSIGHT_COMPONENT_HINTS = {
    "pr": ["pr_trend_chart", "inv_pow_gti_chart"],
    "yield": ["specific_yield_trend_chart", "generation_vs_gti_chart"],
    "loss": ["loss_waterfall"],
    "availability": ["data_availability_trend_chart", "kpi_cards"],
    "generation": ["generation_vs_gti_chart", "kpi_cards"],
    "gti": ["generation_vs_gti_chart"],
    "curtailment": ["inv_pow_gti_chart", "loss_waterfall"],
    "inverter": ["inverter_pr_table", "inv_pow_gti_chart"],
}


def _rows_to_dataframe(calculation_result_or_df: dict | pd.DataFrame) -> pd.DataFrame:
    if isinstance(calculation_result_or_df, pd.DataFrame):
        return calculation_result_or_df.copy()

    clean_rows = []
    for row in calculation_result_or_df.get("rows", []):
        clean_rows.append({
            key: value
            for key, value in row.items()
            if key not in ("metric_sources", "changes")
        })
    return pd.DataFrame(clean_rows)


def _missing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return sorted([column for column in columns if column not in df.columns])


def _components_for_finding(finding: dict) -> list[str]:
    text = " ".join([
        str(finding.get("rule_name") or ""),
        str(finding.get("message") or ""),
        " ".join((finding.get("evidence") or {}).keys()),
    ]).lower()

    components = []
    for keyword, hinted_components in INSIGHT_COMPONENT_HINTS.items():
        if keyword in text:
            components.extend(hinted_components)

    return list(dict.fromkeys(components or ["kpi_cards"]))


def _question_plan_item(question: dict, df: pd.DataFrame) -> dict:
    required_metrics = question.get("required_metrics") or []
    missing = _missing_columns(df, required_metrics)
    status = "answerable" if not missing else "needs_data"

    return {
        "source": "standing_customer_question",
        "question_text": question.get("question_text"),
        "answer_purpose": question.get("answer_purpose"),
        "status": status,
        "required_metrics": required_metrics,
        "missing_metrics": missing,
        "components": question.get("preferred_components") or [],
        "approved_by_analyst": bool(question.get("approved_by_analyst")),
        "scope": question.get("scope"),
    }


def _insight_plan_item(finding: dict, df: pd.DataFrame) -> dict:
    evidence_columns = [
        column
        for column in (finding.get("evidence") or {}).keys()
        if column not in ("thresholds", "row_index", "date")
    ]
    missing = _missing_columns(df, evidence_columns)
    status = "answerable" if not missing else "needs_data"

    return {
        "source": "triggered_insight",
        "question_text": f"Explain: {finding.get('rule_name')}",
        "answer_purpose": finding.get("message"),
        "status": status,
        "severity": finding.get("severity"),
        "required_metrics": evidence_columns,
        "missing_metrics": missing,
        "components": _components_for_finding(finding),
        "finding": finding,
    }


def build_answer_plan(
    calculation_result_or_df: dict | pd.DataFrame,
    customer_id: str,
    report_type: str = REPORT_TYPE,
    insights_result: dict | None = None,
    approved_questions_only: bool = True,
) -> dict:
    """
    Plans the evidence needed for a report draft.

    The planner combines:
    - standing customer questions approved for this report type
    - triggered findings from insights.py

    It does not generate charts or prose. It returns a plan that charts.py and
    report_draft.py can execute.
    """
    df = _rows_to_dataframe(calculation_result_or_df)
    question_profile = get_customer_questions(
        customer_id=customer_id,
        report_type=report_type,
        include_unapproved=not approved_questions_only,
    )
    questions = [
        question for question in question_profile["questions"]
        if question.get("active")
        and (question.get("approved_by_analyst") or not approved_questions_only)
    ]

    plan_items = [_question_plan_item(question, df) for question in questions]

    findings = (insights_result or {}).get("findings", [])
    plan_items.extend(_insight_plan_item(finding, df) for finding in findings)

    requested_components = []
    for item in plan_items:
        if item["status"] != "answerable":
            continue
        requested_components.extend(item.get("components") or [])

    action_required = []
    if not questions:
        action_required.append({
            "type": "approve_customer_questions",
            "message": (
                "Approve standing customer questions before generating the daily "
                "answer plan."
            ),
        })

    missing_items = [item for item in plan_items if item["status"] == "needs_data"]
    for item in missing_items:
        action_required.append({
            "type": "missing_answer_data",
            "question_text": item["question_text"],
            "missing_metrics": item["missing_metrics"],
            "message": (
                f"Cannot fully answer '{item['question_text']}' because "
                f"{', '.join(item['missing_metrics'])} is missing."
            ),
        })

    status = "ready"
    if action_required:
        status = "needs_analyst_input"

    return {
        "valid": status == "ready",
        "status": status,
        "customer_id": customer_id,
        "report_type": report_type,
        "plan_items": plan_items,
        "requested_components": list(dict.fromkeys(requested_components)),
        "action_required": action_required,
        "warnings": [],
    }
