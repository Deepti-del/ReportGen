import os
import sys

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

import database
from answer_planner import build_answer_plan


def _setup_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "reportgen.db"))
    database.create_tables()
    database.seed_default_data()


def test_seeded_customer_questions_are_pending_analyst_approval(
    monkeypatch,
    tmp_path,
):
    _setup_temp_db(monkeypatch, tmp_path)

    profile = database.get_customer_questions(
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    questions = {
        question["question_text"]: question
        for question in profile["questions"]
    }

    assert "Did PR meet the expected target today?" in questions
    assert (
        questions["Did PR meet the expected target today?"]["approved_by_analyst"]
        is False
    )


def test_answer_plan_uses_approved_customer_questions(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_customer_question(
        question_text="Did PR meet the expected target today?",
        answer_purpose="Compare PR against target.",
        required_metrics=["date", "pr_percent"],
        preferred_components=["kpi_cards", "pr_trend_chart"],
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    df = pd.DataFrame([
        {"date": "2025-06-14", "pr_percent": 50.88},
    ])

    plan = build_answer_plan(
        df,
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    assert plan["status"] == "ready"
    assert plan["requested_components"] == ["kpi_cards", "pr_trend_chart"]
    assert plan["plan_items"][0]["status"] == "answerable"


def test_answer_plan_marks_question_when_required_metric_missing(
    monkeypatch,
    tmp_path,
):
    _setup_temp_db(monkeypatch, tmp_path)

    database.approve_customer_question(
        question_text="Was generation aligned with irradiation?",
        answer_purpose="Compare generation and GTI.",
        required_metrics=["date", "generation_kwh", "gti_kwh_m2"],
        preferred_components=["generation_vs_gti_chart"],
        scope="customer_report_type",
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    plan = build_answer_plan(
        pd.DataFrame([{"date": "2025-06-14", "generation_kwh": 513698}]),
        customer_id="alpha_solar",
        report_type="daily_generation",
    )

    assert plan["status"] == "needs_analyst_input"
    assert plan["plan_items"][0]["missing_metrics"] == ["gti_kwh_m2"]
    assert plan["action_required"][0]["type"] == "missing_answer_data"


def test_answer_plan_adds_triggered_insight_components(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    df = pd.DataFrame([{
        "date": "2025-06-14",
        "pr_percent": 50.88,
        "generation_kwh": 513698,
        "gti_kwh_m2": 7.49,
    }])
    insights_result = {
        "findings": [{
            "rule_name": "PR below minimum",
            "message": "PR is below target.",
            "severity": "high",
            "evidence": {
                "pr_percent": 50.88,
                "thresholds": {"min_pr_percent": 65},
                "row_index": 0,
                "date": "2025-06-14",
            },
        }]
    }

    plan = build_answer_plan(
        df,
        customer_id="alpha_solar",
        report_type="daily_generation",
        insights_result=insights_result,
    )

    assert "pr_trend_chart" in plan["requested_components"]
    assert "inv_pow_gti_chart" in plan["requested_components"]
