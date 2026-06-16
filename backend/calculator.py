import json
import os
from typing import Any

import pandas as pd

from database import get_calculation_profile
from formula_utils import validate_formula
from mapper import apply_mapping


REPORT_TYPE = "daily_generation"
DAILY_KPIS_SHEET = "daily_kpis"


def _clean_number(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _round_or_none(value: Any, digits: int = 2) -> float | None:
    number = _clean_number(value)
    if number is None:
        return None
    return round(number, digits)


def _pct_change(current: Any, previous: Any) -> float | None:
    current_num = _clean_number(current)
    previous_num = _clean_number(previous)

    if current_num is None or previous_num in (None, 0):
        return None

    return round(((current_num - previous_num) / previous_num) * 100, 2)


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


def _metric_label(metric: dict) -> str:
    return metric.get("metric_name") or metric.get("output_column") or "metric"


def _profile_metric_metadata(profile: dict) -> dict:
    metadata = {}
    for category in ("required_source", "derivable", "optional", "reference"):
        for metric in profile.get(category, []):
            output_column = metric.get("output_column") or metric.get("metric_name")
            metadata[output_column] = {
                "metric_name": metric.get("metric_name"),
                "output_column": output_column,
                "column_category": metric.get("column_category"),
                "formula": metric.get("formula"),
                "input_columns": metric.get("input_columns") or [],
                "unit": metric.get("unit"),
                "good_range": metric.get("good_range"),
                "poor_threshold": metric.get("poor_threshold"),
                "approved_by_analyst": bool(metric.get("approved_by_analyst")),
                "scope": metric.get("scope"),
                "created_by": metric.get("created_by"),
            }
    return metadata


def _validate_required_sources(df: pd.DataFrame, profile: dict) -> list[dict]:
    actions = []
    for metric in profile.get("required_source", []):
        output_column = metric.get("output_column")
        if output_column and output_column not in df.columns:
            actions.append({
                "type": "missing_required_source",
                "metric_name": _metric_label(metric),
                "output_column": output_column,
                "message": (
                    f"Cannot calculate report because required source column "
                    f"{output_column} is missing. Please check your column mappings."
                ),
            })
    return actions


def _apply_derivable_metrics(
    df: pd.DataFrame,
    profile: dict,
) -> tuple[pd.DataFrame, dict, list[dict], list[str], dict]:
    working_df = df.copy()
    metric_sources = {}
    actions = []
    warnings = []
    formula_checks = {}

    for metric in profile.get("derivable", []):
        output_column = metric.get("output_column")
        formula = metric.get("formula") or ""
        input_columns = metric.get("input_columns") or []
        metric_name = _metric_label(metric)
        approved = bool(metric.get("approved_by_analyst"))

        if not output_column:
            actions.append({
                "type": "metric_definition_error",
                "metric_name": metric_name,
                "message": f"{metric_name} has no output column configured.",
            })
            continue

        validation = validate_formula(
            formula,
            available_columns=working_df.columns,
            input_columns=input_columns,
            metric_name=metric_name,
        ) if formula else {
            "valid": False,
            "reason": "missing_formula",
            "message": f"Cannot calculate {metric_name} because no formula was provided.",
        }

        if output_column in working_df.columns:
            metric_sources[output_column] = "provided"
            if formula:
                if validation["valid"]:
                    check_column = working_df.eval(formula)
                    formula_checks[output_column] = {
                        "metric_name": metric_name,
                        "formula": formula,
                        "approved_by_analyst": approved,
                        "values": [
                            _round_or_none(value, 6)
                            for value in check_column.tolist()
                        ],
                    }
                    if not approved:
                        warnings.append(
                            f"{metric_name} formula is not analyst-approved. "
                            "Provided values were used; formula check is advisory only."
                        )
                else:
                    warnings.append(validation["message"])
            continue

        if not formula:
            actions.append({
                "type": "needs_formula",
                "metric_name": metric_name,
                "output_column": output_column,
                "message": (
                    f"{metric_name} is missing from the data and no formula is configured. "
                    "Please provide a formula or mark this KPI as optional."
                ),
            })
            continue

        if not validation["valid"]:
            actions.append({
                "type": "needs_mapping_fix",
                "metric_name": metric_name,
                "output_column": output_column,
                "formula": formula,
                "input_columns": input_columns,
                "reason": validation["reason"],
                "message": validation["message"],
            })
            continue

        if not approved:
            actions.append({
                "type": "needs_formula_approval",
                "metric_name": metric_name,
                "output_column": output_column,
                "suggested_formula": formula,
                "input_columns": input_columns,
                "unit": metric.get("unit"),
                "scope": metric.get("scope"),
                "message": (
                    f"{metric_name} is missing from the data. A suggested formula is "
                    "available, but the analyst must approve or edit it before use."
                ),
            })
            continue

        working_df[output_column] = working_df.eval(formula)
        metric_sources[output_column] = "calculated"
        warnings.append(
            f"{metric_name} was missing and was calculated using an analyst-approved formula."
        )

    return working_df, metric_sources, actions, warnings, formula_checks


def _optional_warnings(df: pd.DataFrame, profile: dict) -> list[str]:
    missing = [
        metric.get("output_column")
        for metric in profile.get("optional", [])
        if metric.get("output_column") and metric.get("output_column") not in df.columns
    ]
    if not missing:
        return []
    return [
        "Missing optional columns: "
        + ", ".join(missing)
        + ". Report can continue with less detail."
    ]


def _row_changes(row: pd.Series) -> dict:
    changes = {}
    for column in row.index:
        if not column.startswith("prev_day_"):
            continue
        base_column = column.replace("prev_day_", "", 1)
        if base_column in row.index:
            changes[base_column] = _pct_change(row[base_column], row[column])
    return changes


def _build_rows(df: pd.DataFrame, metric_sources: dict) -> list[dict]:
    rows = []
    for _, row in df.iterrows():
        row_result = {
            column: _json_value(row[column])
            for column in df.columns
        }
        row_result["metric_sources"] = {
            column: metric_sources.get(column, "provided")
            for column in df.columns
        }
        row_result["changes"] = _row_changes(row)
        rows.append(row_result)
    return rows


def _summary(df: pd.DataFrame, rows: list[dict]) -> dict:
    numeric_df = df.select_dtypes(include="number")
    total_columns = [
        column for column in numeric_df.columns
        if column.endswith("_kwh")
    ]
    average_columns = [
        column for column in numeric_df.columns
        if column not in total_columns
    ]

    date_column = "date" if "date" in df.columns else None

    return {
        "row_count": len(rows),
        "first_date": str(df[date_column].iloc[0]) if date_column and len(df) else None,
        "last_date": str(df[date_column].iloc[-1]) if date_column and len(df) else None,
        "latest": rows[-1] if rows else {},
        "totals": {
            column: _round_or_none(numeric_df[column].sum(), 2)
            for column in total_columns
        },
        "averages": {
            column: _round_or_none(numeric_df[column].mean(), 2)
            for column in average_columns
        },
    }


def calculate_daily_kpis(
    df: pd.DataFrame,
    customer_id: str,
    report_type: str = REPORT_TYPE,
) -> dict:
    """
    Executes the analyst/customer calculation profile against mapped data.

    The calculator does not own hardcoded KPI definitions. It uses the database
    profile to decide required source fields, optional fields, and derivable
    metrics. Missing derivable metrics are calculated only when their formula is
    analyst-approved.
    """
    profile = get_calculation_profile(customer_id, report_type)
    working_df = df.copy()

    if "date" in working_df.columns:
        working_df["date"] = pd.to_datetime(working_df["date"]).dt.date

    required_actions = _validate_required_sources(working_df, profile)
    if required_actions:
        return {
            "valid": False,
            "status": "blocked",
            "errors": [action["message"] for action in required_actions],
            "warnings": [],
            "action_required": required_actions,
            "rows": [],
            "summary": {},
            "metric_metadata": _profile_metric_metadata(profile),
            "profile": profile,
        }

    working_df, metric_sources, derivable_actions, derivable_warnings, checks = (
        _apply_derivable_metrics(working_df, profile)
    )

    warnings = _optional_warnings(working_df, profile) + derivable_warnings
    rows = _build_rows(working_df, metric_sources)
    status = "needs_analyst_input" if derivable_actions else "ready"

    return {
        "valid": status == "ready",
        "status": status,
        "errors": [],
        "warnings": warnings,
        "action_required": derivable_actions,
        "rows": rows,
        "summary": _summary(working_df, rows),
        "metric_metadata": _profile_metric_metadata(profile),
        "formula_checks": checks,
        "profile": profile,
    }


def calculate_daily_kpis_from_excel(
    excel_path: str,
    customer_id: str,
    sheet_name: str = DAILY_KPIS_SHEET,
    report_type: str = REPORT_TYPE,
) -> dict:
    raw_df = pd.read_excel(excel_path, sheet_name=sheet_name)
    mapping_result = apply_mapping(raw_df, customer_id)

    if not mapping_result["confirmed"]:
        return {
            "valid": False,
            "status": "blocked",
            "errors": [
                "Column mappings are not confirmed by analyst. "
                "Confirm mappings before calculating KPIs."
            ],
            "warnings": mapping_result["warnings"],
            "action_required": [{
                "type": "confirm_mappings",
                "message": "Confirm column mappings before calculating KPIs.",
            }],
            "mapping": {
                "mapped": mapping_result["mapped"],
                "missing": mapping_result["missing"],
                "confirmed": mapping_result["confirmed"],
            },
            "rows": [],
            "summary": {},
            "metric_metadata": {},
        }

    calculation = calculate_daily_kpis(
        mapping_result["df"],
        customer_id,
        report_type=report_type,
    )
    calculation["mapping"] = {
        "mapped": mapping_result["mapped"],
        "missing": mapping_result["missing"],
        "confirmed": mapping_result["confirmed"],
    }
    calculation["warnings"] = mapping_result["warnings"] + calculation["warnings"]
    return calculation


if __name__ == "__main__":
    data_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "Alpha_Solar_Dummy_Dataset.xlsx",
    )

    result = calculate_daily_kpis_from_excel(
        data_path,
        customer_id="alpha_solar",
    )

    print(json.dumps(result, indent=2))
