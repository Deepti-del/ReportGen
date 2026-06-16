import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

from database import get_calculation_profile
from formula_utils import validate_formula


def test_validate_formula_returns_clean_missing_column_message():
    result = validate_formula(
        "generation_kwh / (gti_kwh_m2 * dc_capacity_kwp) * 100",
        available_columns=["generation_kwh", "dc_capacity_kwp"],
        input_columns=["generation_kwh", "gti_kwh_m2", "dc_capacity_kwp"],
        metric_name="PR",
    )

    assert result["valid"] is False
    assert result["reason"] == "missing_input_columns"
    assert result["missing_input_columns"] == ["gti_kwh_m2"]
    assert "Please check your column mappings" in result["message"]


def test_validate_formula_accepts_simple_arithmetic():
    result = validate_formula(
        "generation_kwh / dc_capacity_kwp",
        available_columns=["generation_kwh", "dc_capacity_kwp"],
        input_columns=["generation_kwh", "dc_capacity_kwp"],
        metric_name="Specific Yield",
    )

    assert result["valid"] is True
    assert result["formula_columns"] == ["dc_capacity_kwp", "generation_kwh"]


def test_calculation_profile_groups_seeded_metrics():
    profile = get_calculation_profile("alpha_solar", "daily_generation")

    required = {
        metric["output_column"]
        for metric in profile["required_source"]
    }
    derivable = {
        metric["output_column"]
        for metric in profile["derivable"]
    }
    optional = {
        metric["output_column"]
        for metric in profile["optional"]
    }

    assert "generation_kwh" in required
    assert "pr_percent" in derivable
    assert "specific_yield_kwh_per_kwp" in derivable
    assert "sunshine_hours" in optional
