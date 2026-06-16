import os
import sys

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
DATA_PATH = os.path.join(
    ROOT_DIR,
    "data",
    "Alpha_Solar_Dummy_Dataset.xlsx",
)

sys.path.insert(0, BACKEND_DIR)

from validator import validate_daily_kpis_sheet, validate_workbook


def test_validate_workbook_accepts_alpha_solar_daily_kpis():
    result = validate_workbook(DATA_PATH, customer_id="alpha_solar")

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["sheets"]["daily_kpis"]["row_count"] == 14
    assert result["sheets"]["daily_kpis"]["date_range"] == [
        "2025-06-01",
        "2025-06-14",
    ]
    assert result["sheets"]["daily_kpis"]["mapping"]["missing"] == []


def test_validate_workbook_reports_missing_required_sheet():
    result = validate_workbook(
        DATA_PATH,
        customer_id="alpha_solar",
        required_sheets=["not_a_real_sheet"],
    )

    assert result["valid"] is False
    assert "not_a_real_sheet" in result["errors"][0]


def test_validate_daily_kpis_rejects_non_numeric_required_value():
    df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")
    df.loc[0, "generation_kwh"] = "not numeric"

    result = validate_daily_kpis_sheet(df, customer_id="alpha_solar")

    assert result["valid"] is False
    assert any("generation_kwh" in error for error in result["errors"])


def test_validate_daily_kpis_warns_on_duplicate_plant_date():
    df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)

    result = validate_daily_kpis_sheet(df, customer_id="alpha_solar")

    assert result["valid"] is True
    assert result["duplicates"]["count"] == 1
    assert any("duplicate row" in warning for warning in result["warnings"])
