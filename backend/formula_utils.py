import ast
from typing import Iterable


ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
)


def _formula_column_names(formula_string: str) -> set[str]:
    tree = ast.parse(formula_string, mode="eval")
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }


def validate_formula(
    formula_string: str,
    available_columns: Iterable[str],
    input_columns: Iterable[str] | None = None,
    metric_name: str | None = None,
) -> dict:
    """
    Validates a dataframe formula before calculator execution.

    This does not calculate anything. It checks that:
    - the formula is present and parseable
    - only simple arithmetic syntax is used
    - every declared input column exists in the mapped dataframe
    - every formula reference is declared in input_columns
    - every formula reference exists in the mapped dataframe
    """
    label = metric_name or "metric"
    formula = (formula_string or "").strip()
    available = set(available_columns)
    declared_inputs = set(input_columns or [])

    if not formula:
        return {
            "valid": False,
            "reason": "missing_formula",
            "message": f"Cannot calculate {label} because no formula was provided.",
        }

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        return {
            "valid": False,
            "reason": "invalid_formula_syntax",
            "message": f"Cannot calculate {label} because the formula is invalid: {exc.msg}.",
        }

    unsafe_nodes = [
        type(node).__name__
        for node in ast.walk(tree)
        if not isinstance(node, ALLOWED_AST_NODES)
    ]
    if unsafe_nodes:
        return {
            "valid": False,
            "reason": "unsafe_formula",
            "message": (
                f"Cannot calculate {label} because the formula uses unsupported "
                f"syntax: {', '.join(sorted(set(unsafe_nodes)))}."
            ),
        }

    formula_columns = _formula_column_names(formula)

    missing_declared_inputs = sorted(declared_inputs - available)
    if missing_declared_inputs:
        return {
            "valid": False,
            "reason": "missing_input_columns",
            "missing_input_columns": missing_declared_inputs,
            "message": (
                f"Cannot calculate {label} because "
                f"{', '.join(missing_declared_inputs)} was not found in the mapped data. "
                "Please check your column mappings."
            ),
        }

    undeclared_formula_columns = sorted(formula_columns - declared_inputs)
    if declared_inputs and undeclared_formula_columns:
        return {
            "valid": False,
            "reason": "formula_references_undeclared_columns",
            "undeclared_columns": undeclared_formula_columns,
            "message": (
                f"Cannot calculate {label} because the formula references "
                f"{', '.join(undeclared_formula_columns)}, but those columns are not "
                "listed as input columns."
            ),
        }

    missing_formula_columns = sorted(formula_columns - available)
    if missing_formula_columns:
        return {
            "valid": False,
            "reason": "missing_formula_columns",
            "missing_input_columns": missing_formula_columns,
            "message": (
                f"Cannot calculate {label} because "
                f"{', '.join(missing_formula_columns)} was not found in the mapped data. "
                "Please check your column mappings."
            ),
        }

    return {
        "valid": True,
        "reason": "valid",
        "formula_columns": sorted(formula_columns),
        "message": f"Formula for {label} is valid.",
    }
