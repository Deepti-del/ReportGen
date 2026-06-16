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

from calculator import calculate_daily_kpis, calculate_daily_kpis_from_excel
from mapper import apply_mapping


def test_calculate_daily_kpis_from_excel_returns_profile_driven_rows():
    result = calculate_daily_kpis_from_excel(
        DATA_PATH,
        customer_id="alpha_solar",
    )

    assert result["status"] == "needs_analyst_input"
    assert result["valid"] is False
    assert result["errors"] == []
    assert result["mapping"]["confirmed"] is True
    assert result["summary"]["row_count"] == 14
    assert result["summary"]["latest"]["date"] == "2025-06-14"
    assert result["summary"]["latest"]["pr_percent"] == 50.88
    assert result["summary"]["latest"]["changes"]["pr_percent"] == -25.29


def test_missing_derivable_kpi_requires_formula_approval():
    result = calculate_daily_kpis_from_excel(
        DATA_PATH,
        customer_id="alpha_solar",
    )

    approval_actions = [
        action for action in result["action_required"]
        if action["type"] == "needs_formula_approval"
    ]

    assert approval_actions
    assert approval_actions[0]["metric_name"] == "Specific Yield"
    assert approval_actions[0]["output_column"] == "specific_yield_kwh_per_kwp"
    assert approval_actions[0]["suggested_formula"] == "generation_kwh / dc_capacity_kwp"


def test_provided_values_are_used_and_formula_checks_are_advisory():
    result = calculate_daily_kpis_from_excel(
        DATA_PATH,
        customer_id="alpha_solar",
    )

    assert any(
        "PR formula is not analyst-approved" in warning
        for warning in result["warnings"]
    )
    assert result["formula_checks"]["pr_percent"]["approved_by_analyst"] is False
    assert result["formula_checks"]["pr_percent"]["values"][-1] == 50.803541


def test_missing_required_source_blocks_calculation():
    raw_df = pd.read_excel(DATA_PATH, sheet_name="daily_kpis")
    mapped = apply_mapping(raw_df, "alpha_solar")
    missing_required = mapped["df"].drop(columns=["generation_kwh"])

    result = calculate_daily_kpis(
        missing_required,
        customer_id="alpha_solar",
    )

    assert result["status"] == "blocked"
    assert result["valid"] is False
    assert result["action_required"][0]["type"] == "missing_required_source"
    assert "generation_kwh" in result["errors"][0]
