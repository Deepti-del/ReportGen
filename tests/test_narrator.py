import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

sys.path.insert(0, BACKEND_DIR)

from narrator import generate_narrative_blocks


def test_generate_narrative_blocks_for_findings_and_questions():
    draft = {
        "report_date": "2025-06-14",
        "latest_kpis": {
            "generation_kwh": 513700,
            "pr_percent": 50.88,
            "gti_kwh_m2": 7.49,
            "specific_yield_kwh_per_kwp": 3.805,
        },
        "triggered_findings": [{
            "rule_name": "PR drop",
            "severity": "high",
            "message": "PR dropped more than 10% vs previous day.",
            "suggestion": "Use PR trend and Inv_Pow vs GTI evidence.",
            "evidence": {
                "pr_percent": 50.88,
                "prev_day_pr_percent": 68.1,
                "thresholds": {"pr_drop_threshold_pct": 10},
            },
        }],
        "answered_questions": [{
            "question_text": "Explain the June 14 daily generation event.",
            "answer_purpose": "Explain whether the PR drop has plant-side evidence.",
            "status": "answerable",
            "components": ["pr_trend_chart", "inv_pow_gti_chart"],
            "missing_metrics": [],
        }],
        "pending_approvals": [],
    }

    result = generate_narrative_blocks(draft)

    assert result["status"] == "ready"
    assert result["narrative_blocks"][0]["type"] == "executive_summary"
    assert "PR 50.88%" in result["narrative_blocks"][0]["text"]
    assert result["narrative_blocks"][1]["title"] == "PR drop"
    assert "Evidence: PR 50.88%" in result["narrative_blocks"][1]["text"]
    assert result["narrative_blocks"][2]["type"] == "question_answer"
    assert result["narrative_blocks"][2]["editable"] is True


def test_generate_narrative_blocks_adds_review_note_for_pending_approvals():
    result = generate_narrative_blocks({
        "report_date": "2025-06-14",
        "latest_kpis": {},
        "triggered_findings": [],
        "answered_questions": [],
        "pending_approvals": [{
            "type": "needs_formula_approval",
            "metric_name": "Specific Yield",
        }],
    })

    assert result["narrative_blocks"][-1]["type"] == "review_note"
    assert "needs_formula_approval" in result["narrative_blocks"][-1]["text"]
