from typing import Any


REPORT_TYPE = "daily_generation"

KEY_KPI_LABELS = {
    "generation_kwh": ("Generation", "kWh"),
    "gti_kwh_m2": ("GTI", "kWh/m2"),
    "pr_percent": ("PR", "%"),
    "cuf_percent": ("CUF", "%"),
    "specific_yield_kwh_per_kwp": ("Specific Yield", "kWh/kWp"),
    "total_loss_kwh": ("Total Loss", "kWh"),
    "data_availability_percent": ("Data Availability", "%"),
}


def _format_number(value: Any) -> str:
    if value is None:
        return "not available"
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _metric_phrase(metric: str, value: Any) -> str:
    label, unit = KEY_KPI_LABELS.get(metric, (metric, ""))
    formatted = _format_number(value)
    if unit == "%":
        return f"{label} {formatted}%"
    if unit:
        return f"{label} {formatted} {unit}"
    return f"{label} {formatted}"


def _block_id(prefix: str, value: str, index: int) -> str:
    safe = "".join(char.lower() if char.isalnum() else "_" for char in value)
    safe = "_".join(part for part in safe.split("_") if part)
    return f"{prefix}_{safe or index}"


def _executive_summary_block(report_draft: dict) -> dict:
    report_date = report_draft.get("report_date") or "the report date"
    latest = report_draft.get("latest_kpis") or {}

    metrics = [
        _metric_phrase(metric, latest[metric])
        for metric in (
            "generation_kwh",
            "pr_percent",
            "gti_kwh_m2",
            "specific_yield_kwh_per_kwp",
        )
        if metric in latest
    ]
    metric_text = ", ".join(metrics) if metrics else "key KPIs are available"
    finding_count = len(report_draft.get("triggered_findings") or [])

    if finding_count:
        text = (
            f"For {report_date}, {metric_text}. "
            f"The draft includes {finding_count} finding(s) that need analyst review."
        )
    else:
        text = (
            f"For {report_date}, {metric_text}. "
            "No triggered findings were generated from the approved rules."
        )

    return {
        "block_id": "executive_summary",
        "type": "executive_summary",
        "title": "Executive Summary",
        "text": text,
        "source": "report_draft",
        "editable": True,
    }


def _finding_text(finding: dict) -> str:
    message = finding.get("message")
    suggestion = finding.get("suggestion")

    parts = []
    if message:
        parts.append(message)
    else:
        parts.append(f"{finding.get('rule_name', 'Finding')} was triggered.")

    evidence = finding.get("evidence") or {}
    evidence_phrases = []
    for metric, value in evidence.items():
        if metric in {"thresholds", "row_index", "date"}:
            continue
        evidence_phrases.append(_metric_phrase(metric, value))

    if evidence_phrases:
        parts.append("Evidence: " + ", ".join(evidence_phrases) + ".")

    if suggestion:
        parts.append(suggestion)

    return " ".join(parts)


def _finding_blocks(report_draft: dict) -> list[dict]:
    blocks = []
    for index, finding in enumerate(report_draft.get("triggered_findings") or [], start=1):
        rule_name = finding.get("rule_name") or f"Finding {index}"
        blocks.append({
            "block_id": _block_id("finding", rule_name, index),
            "type": "finding_explanation",
            "title": rule_name,
            "text": _finding_text(finding),
            "source": rule_name,
            "severity": finding.get("severity"),
            "evidence": finding.get("evidence") or {},
            "editable": True,
        })
    return blocks


def _question_blocks(report_draft: dict) -> list[dict]:
    blocks = []
    for index, question in enumerate(report_draft.get("answered_questions") or [], start=1):
        question_text = question.get("question_text") or f"Question {index}"
        status = question.get("status")

        if status == "answerable":
            purpose = question.get("answer_purpose") or "The required evidence is available."
            components = question.get("components") or []
            component_text = (
                " Supporting evidence: " + ", ".join(components) + "."
                if components else ""
            )
            text = f"{purpose}{component_text}"
        else:
            missing = ", ".join(question.get("missing_metrics") or [])
            text = (
                f"This question cannot be fully answered yet because "
                f"the following metric(s) are missing: {missing}."
            )

        blocks.append({
            "block_id": _block_id("question", question_text, index),
            "type": "question_answer",
            "title": question_text,
            "text": text,
            "source": "standing_customer_question",
            "status": status,
            "editable": True,
        })
    return blocks


def _review_note_block(report_draft: dict) -> dict | None:
    pending = report_draft.get("pending_approvals") or []
    if not pending:
        return None

    approval_types = sorted({
        item.get("type", "pending item")
        for item in pending
    })
    return {
        "block_id": "analyst_review_note",
        "type": "review_note",
        "title": "Analyst Review Needed",
        "text": (
            "This draft still has pending analyst review item(s): "
            + ", ".join(approval_types)
            + "."
        ),
        "source": "pending_approvals",
        "editable": True,
    }


def generate_narrative_blocks(report_draft: dict) -> dict:
    """
    Creates deterministic, editable narrative blocks from report draft facts.

    This narrator does not call AI and does not calculate KPIs. It only turns
    existing draft evidence into simple analyst-editable wording.
    """
    blocks = [_executive_summary_block(report_draft)]
    blocks.extend(_finding_blocks(report_draft))
    blocks.extend(_question_blocks(report_draft))

    review_note = _review_note_block(report_draft)
    if review_note:
        blocks.append(review_note)

    return {
        "valid": True,
        "status": "ready",
        "narrative_blocks": blocks,
        "warnings": [],
        "action_required": [],
    }
