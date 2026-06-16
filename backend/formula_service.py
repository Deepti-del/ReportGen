from database import approve_formula, get_calculation_profile
from formula_utils import validate_formula


VALID_SCOPES = {
    "customer_report_type",
    "customer",
    "report_type",
    "global",
}


def _scope_targets(scope: str, customer_id: str, report_type: str) -> tuple[str | None, str | None]:
    if scope == "customer_report_type":
        return customer_id, report_type
    if scope == "customer":
        return customer_id, None
    if scope == "report_type":
        return None, report_type
    if scope == "global":
        return None, None
    raise ValueError(
        f"Unsupported scope '{scope}'. Use one of: {', '.join(sorted(VALID_SCOPES))}."
    )


def _find_profile_metric(profile: dict, output_column: str | None, metric_name: str | None) -> dict | None:
    for category in ("required_source", "derivable", "optional", "reference"):
        for metric in profile.get(category, []):
            if output_column and metric.get("output_column") == output_column:
                return metric
            if metric_name and metric.get("metric_name") == metric_name:
                return metric
    return None


def approve_suggested_formula(
    customer_id: str,
    report_type: str,
    output_column: str | None = None,
    metric_name: str | None = None,
    scope: str = "customer_report_type",
    available_columns: list[str] | None = None,
    created_by: str = "analyst",
) -> dict:
    """
    Approves a system-suggested formula from the calculation profile.

    This is the backend equivalent of the analyst clicking:
    "Use suggested formula".
    """
    profile = get_calculation_profile(customer_id, report_type)
    metric = _find_profile_metric(profile, output_column, metric_name)

    if not metric:
        return {
            "ok": False,
            "reason": "metric_not_found",
            "message": "Could not find the requested metric in the calculation profile.",
        }

    if metric.get("column_category") != "derivable":
        return {
            "ok": False,
            "reason": "not_derivable",
            "message": f"{metric.get('metric_name')} is not configured as a derivable metric.",
        }

    input_columns = metric.get("input_columns") or []
    validation = validate_formula(
        metric.get("formula") or "",
        available_columns=available_columns or input_columns,
        input_columns=input_columns,
        metric_name=metric.get("metric_name"),
    )
    if not validation["valid"]:
        return {
            "ok": False,
            "reason": validation["reason"],
            "validation": validation,
            "message": validation["message"],
        }

    target_customer_id, target_report_type = _scope_targets(
        scope,
        customer_id,
        report_type,
    )

    approve_formula(
        metric_name=metric["metric_name"],
        output_column=metric.get("output_column"),
        column_category=metric.get("column_category", "derivable"),
        formula=metric.get("formula") or "",
        input_columns=input_columns,
        unit=metric.get("unit"),
        good_range=metric.get("good_range"),
        poor_threshold=metric.get("poor_threshold"),
        scope=scope,
        customer_id=target_customer_id,
        report_type=target_report_type,
        created_by=created_by,
    )

    return {
        "ok": True,
        "action": "approved_suggested_formula",
        "scope": scope,
        "metric_name": metric.get("metric_name"),
        "output_column": metric.get("output_column"),
        "formula": metric.get("formula"),
        "input_columns": input_columns,
        "message": f"Approved formula for {metric.get('metric_name')}.",
    }


def add_custom_formula(
    customer_id: str,
    report_type: str,
    metric_name: str,
    output_column: str,
    formula: str,
    input_columns: list[str],
    available_columns: list[str],
    unit: str | None = None,
    good_range: str | None = None,
    poor_threshold: str | None = None,
    column_category: str = "derivable",
    scope: str = "customer_report_type",
    created_by: str = "analyst",
) -> dict:
    """
    Adds or edits an analyst-defined KPI formula.

    This is the backend equivalent of the analyst entering:
    "Here is a KPI, here is the formula, use it for this scope."
    """
    validation = validate_formula(
        formula,
        available_columns=available_columns,
        input_columns=input_columns,
        metric_name=metric_name,
    )
    if not validation["valid"]:
        return {
            "ok": False,
            "reason": validation["reason"],
            "validation": validation,
            "message": validation["message"],
        }

    target_customer_id, target_report_type = _scope_targets(
        scope,
        customer_id,
        report_type,
    )

    approve_formula(
        metric_name=metric_name,
        output_column=output_column,
        column_category=column_category,
        formula=formula,
        input_columns=input_columns,
        unit=unit,
        good_range=good_range,
        poor_threshold=poor_threshold,
        scope=scope,
        customer_id=target_customer_id,
        report_type=target_report_type,
        created_by=created_by,
    )

    return {
        "ok": True,
        "action": "saved_custom_formula",
        "scope": scope,
        "metric_name": metric_name,
        "output_column": output_column,
        "formula": formula,
        "input_columns": input_columns,
        "message": f"Saved analyst-approved formula for {metric_name}.",
    }
