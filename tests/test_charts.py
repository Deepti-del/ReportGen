import os
import sys

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

from charts import build_chart_specs


def _daily_df():
    return pd.DataFrame([
        {
            "date": "2025-06-13",
            "generation_kwh": 494600,
            "gti_kwh_m2": 5.83,
            "pr_percent": 76.17,
            "total_loss_kwh": 154000,
            "outage_loss_kwh": 10000,
            "environmental_loss_kwh": 20000,
            "clipping_loss_kwh": 5000,
            "data_availability_percent": 99.2,
        },
        {
            "date": "2025-06-14",
            "generation_kwh": 513698,
            "gti_kwh_m2": 7.49,
            "pr_percent": 50.88,
            "total_loss_kwh": 377000,
            "outage_loss_kwh": 86000,
            "environmental_loss_kwh": 30000,
            "clipping_loss_kwh": 10000,
            "data_availability_percent": 98.7,
        },
    ])


def test_build_chart_specs_from_answer_plan_components():
    answer_plan = {
        "requested_components": [
            "kpi_cards",
            "generation_vs_gti_chart",
            "pr_trend_chart",
        ]
    }

    result = build_chart_specs(_daily_df(), answer_plan=answer_plan)

    assert result["status"] == "ready"
    assert [chart["component_id"] for chart in result["chart_specs"]] == [
        "kpi_cards",
        "generation_vs_gti_chart",
        "pr_trend_chart",
    ]
    assert result["chart_specs"][1]["series"][0]["metric"] == "generation_kwh"
    assert result["chart_specs"][1]["series"][1]["metric"] == "gti_kwh_m2"


def test_build_chart_specs_skips_missing_chart_columns():
    result = build_chart_specs(
        pd.DataFrame([{"date": "2025-06-14", "pr_percent": 50.88}]),
        requested_components=["generation_vs_gti_chart", "pr_trend_chart"],
    )

    assert result["status"] == "ready"
    assert [chart["component_id"] for chart in result["chart_specs"]] == [
        "pr_trend_chart",
    ]
    assert result["skipped_charts"][0]["component_id"] == "generation_vs_gti_chart"
    assert result["skipped_charts"][0]["missing_columns"] == [
        "generation_kwh",
        "gti_kwh_m2",
    ]


def test_loss_breakdown_uses_available_loss_columns():
    result = build_chart_specs(
        _daily_df().drop(columns=["outage_loss_kwh"]),
        requested_components=["loss_breakdown_chart"],
    )

    chart = result["chart_specs"][0]

    assert chart["component_id"] == "loss_breakdown_chart"
    assert [series["metric"] for series in chart["series"]] == [
        "environmental_loss_kwh",
        "clipping_loss_kwh",
        "total_loss_kwh",
    ]
