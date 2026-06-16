import ast
import math
import re
from typing import Any, Iterable

import pandas as pd

from database import get_insight_rules


REPORT_TYPE = "daily_generation"

ALLOWED_CONDITION_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _normalise_condition(condition: str) -> str:
    cleaned = (condition or "").strip()
    cleaned = re.sub(r"\bAND\b", "and", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bOR\b", "or", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNOT\b", "not", cleaned, flags=re.IGNORECASE)
    return cleaned


def _condition_names(condition: str) -> set[str]:
    tree = ast.parse(condition, mode="eval")
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 6)
        return None
    return value


def _rows_to_dataframe(calculation_result_or_df: dict | pd.DataFrame) -> pd.DataFrame:
    if isinstance(calculation_result_or_df, pd.DataFrame):
        return calculation_result_or_df.copy()

    rows = calculation_result_or_df.get("rows", [])
    clean_rows = []
    for row in rows:
        clean_rows.append({
            key: value
            for key, value in row.items()
            if key not in ("metric_sources", "changes")
        })
    return pd.DataFrame(clean_rows)


def _validate_rule(rule: dict, available_columns: Iterable[str]) -> dict:
    rule_name = rule.get("rule_name") or "insight rule"
    condition = _normalise_condition(rule.get("condition") or "")
    input_columns = set(rule.get("input_columns") or [])
    thresholds = rule.get("thresholds") or {}
    available = set(available_columns)

    if not condition:
        return {
            "valid": False,
            "reason": "missing_condition",
            "message": f"Cannot run {rule_name} because no condition was provided.",
        }

    try:
        tree = ast.parse(condition, mode="eval")
    except SyntaxError as exc:
        return {
            "valid": False,
            "reason": "invalid_condition_syntax",
            "message": f"Cannot run {rule_name} because the condition is invalid: {exc.msg}.",
        }

    unsafe_nodes = [
        type(node).__name__
        for node in ast.walk(tree)
        if not isinstance(node, ALLOWED_CONDITION_NODES)
    ]
    if unsafe_nodes:
        return {
            "valid": False,
            "reason": "unsafe_condition",
            "message": (
                f"Cannot run {rule_name} because the condition uses unsupported "
                f"syntax: {', '.join(sorted(set(unsafe_nodes)))}."
            ),
        }

    missing_inputs = sorted(input_columns - available)
    if missing_inputs:
        return {
            "valid": False,
            "reason": "missing_input_columns",
            "missing_input_columns": missing_inputs,
            "message": (
                f"Cannot run {rule_name} because "
                f"{', '.join(missing_inputs)} was not found in the calculated data. "
                "Please check mappings, formulas, or rule inputs."
            ),
        }

    condition_names = _condition_names(condition)
    allowed_names = input_columns | set(thresholds.keys())
    undeclared_names = sorted(condition_names - allowed_names)
    if undeclared_names:
        return {
            "valid": False,
            "reason": "condition_references_undeclared_names",
            "undeclared_names": undeclared_names,
            "message": (
                f"Cannot run {rule_name} because the condition references "
                f"{', '.join(undeclared_names)}, but those names are not listed "
                "as input columns or thresholds."
            ),
        }

    return {
        "valid": True,
        "reason": "valid",
        "condition": condition,
        "message": f"{rule_name} is valid.",
    }


def _format_template(template: str | None, values: dict) -> str | None:
    if not template:
        return None
    return template.format_map(_SafeFormatDict(values))


def _evaluate_rule_on_row(rule: dict, row: pd.Series, condition: str) -> bool:
    values = {
        column: row[column]
        for column in rule.get("input_columns", [])
    }
    values.update(rule.get("thresholds") or {})

    if any(pd.isna(value) for value in values.values()):
        return False

    compiled = compile(ast.parse(condition, mode="eval"), "<insight-rule>", "eval")
    return bool(eval(compiled, {"__builtins__": {}}, values))


def _finding(rule: dict, row: pd.Series, row_index: int, condition: str) -> dict:
    thresholds = rule.get("thresholds") or {}
    evidence = {
        column: _json_value(row[column])
        for column in rule.get("input_columns", [])
    }
    template_values = {
        **evidence,
        **thresholds,
        "row_index": row_index,
    }
    if "date" in row.index:
        template_values["date"] = _json_value(row["date"])

    return {
        "rule_name": rule.get("rule_name"),
        "severity": rule.get("severity", "medium"),
        "rule_type": rule.get("rule_type", "row_condition"),
        "condition": condition,
        "message": _format_template(rule.get("message_template"), template_values),
        "suggestion": _format_template(rule.get("suggestion_template"), template_values),
        "evidence": {
            **evidence,
            "thresholds": thresholds,
            "row_index": row_index,
            "date": template_values.get("date"),
        },
        "scope": rule.get("scope"),
        "customer_id": rule.get("customer_id"),
        "report_type": rule.get("report_type"),
    }


def generate_insights(
    calculation_result_or_df: dict | pd.DataFrame,
    customer_id: str,
    report_type: str = REPORT_TYPE,
    approved_only: bool = True,
) -> dict:
    """
    Executes analyst-approved insight rules against calculated report data.

    Rules are database-driven and KPI-agnostic. The analyst can add a rule for
    any calculated or mapped KPI by defining:
    - input columns
    - threshold values
    - condition
    - severity and message templates
    """
    df = _rows_to_dataframe(calculation_result_or_df)
    rules_profile = get_insight_rules(
        customer_id=customer_id,
        report_type=report_type,
        include_unapproved=not approved_only,
    )
    rules = [
        rule for rule in rules_profile["rules"]
        if rule.get("active") and (rule.get("approved_by_analyst") or not approved_only)
    ]

    if df.empty:
        return {
            "valid": False,
            "status": "blocked",
            "findings": [],
            "skipped_rules": [],
            "warnings": ["No calculated rows were provided for insight generation."],
            "action_required": [{
                "type": "calculate_kpis_first",
                "message": "Calculate KPIs before running insight rules.",
            }],
            "rules_evaluated": 0,
        }

    if not rules:
        return {
            "valid": False,
            "status": "needs_analyst_input",
            "findings": [],
            "skipped_rules": [],
            "warnings": ["No approved insight rules are available for this customer/report type."],
            "action_required": [{
                "type": "approve_insight_rules",
                "message": (
                    "Approve or add insight rules before generating deterministic findings."
                ),
            }],
            "rules_evaluated": 0,
        }

    findings = []
    skipped_rules = []
    evaluated = 0

    for rule in rules:
        validation = _validate_rule(rule, df.columns)
        if not validation["valid"]:
            skipped_rules.append({
                "rule_name": rule.get("rule_name"),
                "reason": validation["reason"],
                "message": validation["message"],
            })
            continue

        condition = validation["condition"]
        evaluated += 1

        for row_index, row in df.iterrows():
            try:
                matched = _evaluate_rule_on_row(rule, row, condition)
            except (ArithmeticError, TypeError, ValueError, NameError) as exc:
                skipped_rules.append({
                    "rule_name": rule.get("rule_name"),
                    "reason": "condition_runtime_error",
                    "message": (
                        f"Could not run {rule.get('rule_name')} on row {row_index}: {exc}."
                    ),
                })
                break

            if matched:
                findings.append(_finding(rule, row, int(row_index), condition))

    return {
        "valid": True,
        "status": "ready",
        "findings": findings,
        "skipped_rules": skipped_rules,
        "warnings": [],
        "action_required": [],
        "rules_evaluated": evaluated,
    }
