import os
import sys

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

import database
from insights import generate_insights


def _setup_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "reportgen.db"))
    database.create_tables()
    database.seed_default_data()


def test_seeded_insight_rules_are_suggestions_pending_analyst_approval(
    monkeypatch,
    tmp_path,
):
    _setup_temp_db(monkeypatch, tmp_path)

    profile = database.get_insight_rules(
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    rules = {rule["rule_name"]: rule for rule in profile["rules"]}

    assert "PR drop vs previous day" in rules
    assert rules["PR drop vs previous day"]["approved_by_analyst"] is False
    assert rules["PR drop vs previous day"]["input_columns"] == [
        "pr_percent",
        "prev_day_pr_percent",
    ]
    assert rules["PR drop vs previous day"]["thresholds"] == {
        "pr_drop_threshold_pct": 10,
    }


def test_analyst_can_add_rule_for_any_kpi(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_insight_rule(
        rule_name="Battery availability below target",
        condition="battery_availability_percent < min_battery_availability_percent",
        input_columns=["battery_availability_percent"],
        thresholds={"min_battery_availability_percent": 92},
        severity="medium",
        message_template=(
            "Battery availability is below "
            "{min_battery_availability_percent}%."
        ),
        suggestion_template="Add maintenance context or explain the outage window.",
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    profile = database.get_insight_rules(
        customer_id="alpha_solar",
        report_type="daily_generation",
        include_unapproved=False,
    )

    rules = {rule["rule_name"]: rule for rule in profile["rules"]}

    assert "Battery availability below target" in rules
    assert rules["Battery availability below target"]["approved_by_analyst"] is True
    assert rules["Battery availability below target"]["thresholds"] == {
        "min_battery_availability_percent": 92,
    }


def test_customer_specific_approved_rule_overrides_global_suggestion(
    monkeypatch,
    tmp_path,
):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_insight_rule(
        rule_name="PR below minimum",
        condition="pr_percent < min_pr_percent",
        input_columns=["pr_percent"],
        thresholds={"min_pr_percent": 70},
        severity="high",
        message_template="PR is below Alpha Solar's approved target.",
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    profile = database.get_insight_rules(
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    rules = {rule["rule_name"]: rule for rule in profile["rules"]}

    assert rules["PR below minimum"]["approved_by_analyst"] is True
    assert rules["PR below minimum"]["thresholds"] == {"min_pr_percent": 70}
    assert rules["PR below minimum"]["customer_id"] == "alpha_solar"


def test_generate_insights_requires_approved_rules(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)
    df = pd.DataFrame([{
        "date": "2025-06-14",
        "pr_percent": 50.88,
        "prev_day_pr_percent": 76.17,
    }])

    result = generate_insights(
        df,
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    assert result["status"] == "needs_analyst_input"
    assert result["action_required"][0]["type"] == "approve_insight_rules"
    assert result["rules_evaluated"] == 0


def test_generate_insights_runs_approved_custom_kpi_rule(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_insight_rule(
        rule_name="Battery availability below target",
        condition="battery_availability_percent < min_battery_availability_percent",
        input_columns=["battery_availability_percent"],
        thresholds={"min_battery_availability_percent": 92},
        severity="medium",
        message_template=(
            "Battery availability is below "
            "{min_battery_availability_percent}%."
        ),
        suggestion_template="Add maintenance context for {date}.",
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    df = pd.DataFrame([
        {"date": "2025-06-13", "battery_availability_percent": 95},
        {"date": "2025-06-14", "battery_availability_percent": 88},
    ])

    result = generate_insights(
        df,
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    assert result["status"] == "ready"
    assert result["rules_evaluated"] == 1
    assert len(result["findings"]) == 1
    assert result["findings"][0]["rule_name"] == "Battery availability below target"
    assert result["findings"][0]["evidence"]["battery_availability_percent"] == 88
    assert result["findings"][0]["message"] == "Battery availability is below 92%."


def test_generate_insights_skips_rule_with_missing_input(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_insight_rule(
        rule_name="Missing metric rule",
        condition="missing_metric < min_missing_metric",
        input_columns=["missing_metric"],
        thresholds={"min_missing_metric": 10},
        severity="medium",
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    result = generate_insights(
        pd.DataFrame([{"date": "2025-06-14", "pr_percent": 50.88}]),
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    assert result["status"] == "ready"
    assert result["findings"] == []
    assert result["skipped_rules"][0]["reason"] == "missing_input_columns"
    assert "Please check mappings" in result["skipped_rules"][0]["message"]
