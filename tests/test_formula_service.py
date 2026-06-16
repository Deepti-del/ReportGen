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

import database
from calculator import calculate_daily_kpis
from formula_service import add_custom_formula, approve_suggested_formula


def _setup_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "reportgen.db"))
    database.create_tables()
    database.seed_default_data()


def test_approve_suggested_formula_allows_missing_kpi_calculation(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")

    first_result = calculate_daily_kpis(df, customer_id="alpha_solar")
    assert first_result["status"] == "needs_analyst_input"
    assert first_result["action_required"][0]["metric_name"] == "Specific Yield"

    approval = approve_suggested_formula(
        customer_id="alpha_solar",
        report_type="daily_generation",
        output_column="specific_yield_kwh_per_kwp",
        scope="customer_report_type",
        available_columns=list(df.columns),
    )

    assert approval["ok"] is True

    second_result = calculate_daily_kpis(df, customer_id="alpha_solar")
    assert second_result["status"] == "ready"
    assert second_result["valid"] is True
    assert second_result["summary"]["latest"]["specific_yield_kwh_per_kwp"] == 3.805185
    assert (
        second_result["summary"]["latest"]["metric_sources"]["specific_yield_kwh_per_kwp"]
        == "calculated"
    )


def test_add_custom_formula_adds_new_calculated_kpi(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")

    approve_suggested_formula(
        customer_id="alpha_solar",
        report_type="daily_generation",
        output_column="specific_yield_kwh_per_kwp",
        scope="customer_report_type",
        available_columns=list(df.columns),
    )

    result = add_custom_formula(
        customer_id="alpha_solar",
        report_type="daily_generation",
        metric_name="Loss Percentage",
        output_column="loss_percent",
        formula="total_loss_kwh / expected_generation_kwh * 100",
        input_columns=["total_loss_kwh", "expected_generation_kwh"],
        available_columns=list(df.columns),
        unit="%",
        scope="customer_report_type",
    )

    assert result["ok"] is True

    calculated = calculate_daily_kpis(df, customer_id="alpha_solar")
    assert calculated["status"] == "ready"
    assert calculated["summary"]["latest"]["loss_percent"] == 42.268704
    assert calculated["summary"]["latest"]["metric_sources"]["loss_percent"] == "calculated"


def test_custom_formula_returns_mapping_friendly_error(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")

    result = add_custom_formula(
        customer_id="alpha_solar",
        report_type="daily_generation",
        metric_name="Broken KPI",
        output_column="broken_kpi",
        formula="missing_column / generation_kwh",
        input_columns=["missing_column", "generation_kwh"],
        available_columns=list(df.columns),
        unit="%",
        scope="customer_report_type",
    )

    assert result["ok"] is False
    assert result["reason"] == "missing_input_columns"
    assert "Please check your column mappings" in result["message"]
