import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

from report_draft import assemble_report_draft


def test_assemble_report_draft_packages_backend_outputs():
    validation = {
        "valid": True,
        "warnings": [],
    }
    mapping = {
        "confirmed": True,
        "warnings": [],
    }
    calculation = {
        "valid": True,
        "status": "ready",
        "warnings": [],
        "action_required": [],
        "summary": {
            "row_count": 1,
            "latest": {
                "date": "2025-06-14",
                "generation_kwh": 513700,
                "pr_percent": 50.88,
                "metric_sources": {"pr_percent": "provided"},
                "changes": {"pr_percent": -25.29},
            },
        },
    }
    insights = {
        "valid": True,
        "status": "ready",
        "warnings": [],
        "action_required": [],
        "rules_evaluated": 1,
        "findings": [{
            "rule_name": "PR drop",
            "severity": "high",
            "message": "PR dropped.",
            "evidence": {"pr_percent": 50.88},
        }],
        "skipped_rules": [],
    }
    answer_plan = {
        "valid": True,
        "status": "ready",
        "warnings": [],
        "action_required": [],
        "requested_components": ["kpi_cards", "pr_trend_chart", "inverter_pr_table"],
        "plan_items": [{
            "source": "standing_customer_question",
            "question_text": "Did PR meet target?",
            "answer_purpose": "Compare PR against target.",
            "status": "answerable",
            "required_metrics": ["pr_percent"],
            "missing_metrics": [],
            "components": ["kpi_cards", "pr_trend_chart"],
            "approved_by_analyst": True,
        }],
    }
    charts = {
        "valid": True,
        "status": "ready",
        "warnings": [],
        "action_required": [],
        "skipped_charts": [],
        "chart_specs": [
            {
                "component_id": "kpi_cards",
                "type": "kpi_cards",
                "cards": [{"metric": "pr_percent", "value": 50.88, "unit": "%"}],
            },
            {
                "component_id": "pr_trend_chart",
                "type": "line",
                "series": [],
            },
            {
                "component_id": "inverter_pr_table",
                "type": "table",
                "rows": [],
            },
        ],
    }

    draft = assemble_report_draft(
        customer_id="alpha_solar",
        report_type="daily_generation",
        validation_result=validation,
        mapping_result=mapping,
        calculation_result=calculation,
        insights_result=insights,
        answer_plan=answer_plan,
        chart_result=charts,
    )

    assert draft["status"] == "draft_ready"
    assert draft["report_date"] == "2025-06-14"
    assert draft["latest_kpis"]["pr_percent"] == 50.88
    assert draft["kpi_cards"][0]["metric"] == "pr_percent"
    assert draft["triggered_findings"][0]["rule_name"] == "PR drop"
    assert draft["answered_questions"][0]["question_text"] == "Did PR meet target?"
    assert draft["chart_specs"][0]["component_id"] == "pr_trend_chart"
    assert draft["tables"][0]["component_id"] == "inverter_pr_table"
    assert draft["pending_approvals"] == []


def test_assemble_report_draft_surfaces_pending_approvals():
    draft = assemble_report_draft(
        customer_id="alpha_solar",
        report_type="daily_generation",
        validation_result={"valid": True},
        calculation_result={
            "status": "needs_analyst_input",
            "action_required": [{
                "type": "needs_formula_approval",
                "metric_name": "Specific Yield",
            }],
            "summary": {},
        },
    )

    assert draft["status"] == "needs_analyst_input"
    assert draft["pending_approvals"][0]["type"] == "needs_formula_approval"
