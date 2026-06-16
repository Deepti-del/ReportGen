import json
import os
from typing import Any

import pandas as pd

from database import get_calculation_profile
from mapper import apply_mapping


REPORT_TYPE = "daily_generation"
DAILY_KPIS_SHEET = "daily_kpis"


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _metric_columns(profile: dict, category: str) -> list[str]:
    return [
        metric["output_column"]
        for metric in profile.get(category, [])
        if metric.get("output_column")
    ]


def _validate_date_column(df: pd.DataFrame, column: str = "date") -> dict:
    if column not in df.columns:
        return {
            "valid": False,
            "errors": [f"Date column '{column}' is missing."],
            "warnings": [],
            "date_range": None,
        }

    parsed = pd.to_datetime(df[column], errors="coerce")
    invalid_count = int(parsed.isna().sum())

    errors = []
    warnings = []
    if invalid_count:
        errors.append(
            f"Date column '{column}' contains {invalid_count} invalid value(s)."
        )

    date_range = None
    if not parsed.dropna().empty:
        date_range = [
            str(parsed.min().date()),
            str(parsed.max().date()),
        ]

    if parsed.dropna().is_monotonic_increasing is False:
        warnings.append(
            f"Date column '{column}' is not sorted in increasing order."
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "date_range": date_range,
    }


def _validate_numeric_columns(df: pd.DataFrame, columns: list[str]) -> dict:
    errors = []
    warnings = []
    details = {}

    for column in columns:
        if column not in df.columns:
            continue
        converted = pd.to_numeric(df[column], errors="coerce")
        invalid_count = int(converted.isna().sum() - df[column].isna().sum())
        missing_count = int(df[column].isna().sum())

        details[column] = {
            "missing_count": missing_count,
            "invalid_numeric_count": invalid_count,
        }

        if invalid_count:
            errors.append(
                f"Column '{column}' contains {invalid_count} non-numeric value(s)."
            )
        elif missing_count:
            warnings.append(
                f"Column '{column}' contains {missing_count} blank value(s)."
            )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def _validate_duplicates(df: pd.DataFrame, keys: list[str]) -> dict:
    keys_present = [key for key in keys if key in df.columns]
    if not keys_present:
        return {
            "valid": True,
            "errors": [],
            "warnings": [],
            "duplicate_count": 0,
            "keys": [],
        }

    duplicate_count = int(df.duplicated(subset=keys_present).sum())
    warnings = []
    if duplicate_count:
        warnings.append(
            f"Found {duplicate_count} duplicate row(s) using keys: "
            + ", ".join(keys_present)
        )

    return {
        "valid": True,
        "errors": [],
        "warnings": warnings,
        "duplicate_count": duplicate_count,
        "keys": keys_present,
    }


def _relevant_mapping_summary(mapping_result: dict, relevant_columns: list[str]) -> dict:
    relevant = set(relevant_columns)
    mapped = [
        mapping for mapping in mapping_result["mapped"]
        if mapping["system_col"] in relevant
    ]
    missing = [
        column for column in relevant_columns
        if column not in {mapping["system_col"] for mapping in mapped}
    ]

    return {
        "confirmed": mapping_result["confirmed"],
        "mapped": mapped,
        "missing": missing,
    }


def validate_daily_kpis_sheet(
    df: pd.DataFrame,
    customer_id: str,
    report_type: str = REPORT_TYPE,
) -> dict:
    profile = get_calculation_profile(customer_id, report_type)
    mapping_result = apply_mapping(df, customer_id)
    mapped_df = mapping_result["df"]

    errors = []
    warnings = []

    if df.empty:
        errors.append(f"Sheet '{DAILY_KPIS_SHEET}' is empty.")

    if not mapping_result["confirmed"]:
        errors.append(
            "Column mappings are not confirmed by analyst. Confirm mappings before validation."
        )

    required_columns = _metric_columns(profile, "required_source")
    missing_required = [
        column for column in required_columns
        if column not in mapped_df.columns
    ]
    if missing_required:
        errors.append(
            "Missing required source columns after mapping: "
            + ", ".join(missing_required)
        )

    optional_columns = _metric_columns(profile, "optional")
    missing_optional = [
        column for column in optional_columns
        if column not in mapped_df.columns
    ]
    if missing_optional:
        warnings.append(
            "Missing optional columns: "
            + ", ".join(missing_optional)
            + ". Report can continue with less detail."
        )

    date_result = _validate_date_column(mapped_df, "date")
    errors.extend(date_result["errors"])
    warnings.extend(date_result["warnings"])

    numeric_columns = [
        column for column in (
            _metric_columns(profile, "required_source")
            + _metric_columns(profile, "derivable")
            + _metric_columns(profile, "optional")
        )
        if column not in {"date", "plant_id"} and column in mapped_df.columns
    ]
    numeric_result = _validate_numeric_columns(mapped_df, numeric_columns)
    errors.extend(numeric_result["errors"])
    warnings.extend(numeric_result["warnings"])

    duplicate_result = _validate_duplicates(mapped_df, ["plant_id", "date"])
    warnings.extend(duplicate_result["warnings"])

    relevant_columns = list(dict.fromkeys(required_columns + optional_columns))
    mapping_summary = _relevant_mapping_summary(mapping_result, relevant_columns)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "sheet_name": DAILY_KPIS_SHEET,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": list(df.columns),
        "mapped_columns": list(mapped_df.columns),
        "date_range": date_result["date_range"],
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "numeric_checks": numeric_result["details"],
        "duplicates": {
            "count": duplicate_result["duplicate_count"],
            "keys": duplicate_result["keys"],
        },
        "mapping": {
            "confirmed": mapping_result["confirmed"],
            "mapped": mapping_summary["mapped"],
            "missing": mapping_summary["missing"],
        },
    }


def validate_workbook(
    excel_path: str,
    customer_id: str,
    report_type: str = REPORT_TYPE,
    required_sheets: list[str] | None = None,
) -> dict:
    required_sheets = required_sheets or [DAILY_KPIS_SHEET]
    errors = []
    warnings = []
    sheet_results = {}

    if not os.path.exists(excel_path):
        return {
            "valid": False,
            "errors": [f"Workbook not found: {excel_path}"],
            "warnings": [],
            "sheets": {},
        }

    try:
        workbook = pd.ExcelFile(excel_path)
    except Exception as exc:
        return {
            "valid": False,
            "errors": [f"Could not open workbook: {exc}"],
            "warnings": [],
            "sheets": {},
        }

    available_sheets = workbook.sheet_names
    missing_sheets = [
        sheet for sheet in required_sheets
        if sheet not in available_sheets
    ]
    if missing_sheets:
        errors.append(
            "Workbook is missing required sheet(s): "
            + ", ".join(missing_sheets)
        )

    for sheet in required_sheets:
        if sheet not in available_sheets:
            continue

        df = pd.read_excel(workbook, sheet_name=sheet)
        if sheet == DAILY_KPIS_SHEET:
            result = validate_daily_kpis_sheet(
                df,
                customer_id=customer_id,
                report_type=report_type,
            )
        else:
            result = {
                "valid": True,
                "errors": [],
                "warnings": [
                    f"No sheet-specific validator implemented for '{sheet}' yet."
                ],
                "sheet_name": sheet,
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "columns": list(df.columns),
            }

        sheet_results[sheet] = result
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "workbook": {
            "path": excel_path,
            "available_sheets": available_sheets,
            "required_sheets": required_sheets,
        },
        "sheets": sheet_results,
    }


if __name__ == "__main__":
    data_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "Alpha_Solar_Dummy_Dataset.xlsx",
    )

    result = validate_workbook(
        data_path,
        customer_id="alpha_solar",
    )
    print(json.dumps(result, indent=2))
