from typing import Any

import pandas as pd


REPORT_TYPE = "daily_generation"

DEFAULT_COMPONENTS = [
    "kpi_cards",
    "generation_vs_gti_chart",
    "inv_pow_gti_chart",
    "pr_trend_chart",
    "loss_breakdown_chart",
    "loss_waterfall",
    "inverter_pr_table",
    "specific_yield_trend_chart",
    "data_availability_trend_chart",
]

KPI_CARD_COLUMNS = [
    ("generation_kwh", "Generation", "kWh"),
    ("gti_kwh_m2", "GTI", "kWh/m2"),
    ("pr_percent", "PR", "%"),
    ("cuf_percent", "CUF", "%"),
    ("specific_yield_kwh_per_kwp", "Specific Yield", "kWh/kWp"),
    ("total_loss_kwh", "Total Loss", "kWh"),
]


def _rows_to_dataframe(calculation_result_or_df: dict | pd.DataFrame) -> pd.DataFrame:
    if isinstance(calculation_result_or_df, pd.DataFrame):
        return calculation_result_or_df.copy()

    clean_rows = []
    for row in calculation_result_or_df.get("rows", []):
        clean_rows.append({
            key: value
            for key, value in row.items()
            if key not in ("metric_sources", "changes")
        })
    return pd.DataFrame(clean_rows)


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _values(df: pd.DataFrame, column: str) -> list[Any]:
    return [_json_value(value) for value in df[column].tolist()]


def _missing(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column not in df.columns]


def _skip(component_id: str, missing_columns: list[str]) -> dict:
    return {
        "component_id": component_id,
        "reason": "missing_columns",
        "missing_columns": missing_columns,
        "message": (
            f"Cannot generate {component_id} because "
            f"{', '.join(missing_columns)} is missing."
        ),
    }


def _kpi_cards(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    available_cards = []
    latest = df.iloc[-1] if len(df) else None

    if latest is None:
        return None, _skip("kpi_cards", ["rows"])

    for column, label, unit in KPI_CARD_COLUMNS:
        if column not in df.columns:
            continue
        available_cards.append({
            "metric": column,
            "label": label,
            "value": _json_value(latest[column]),
            "unit": unit,
        })

    if not available_cards:
        return None, _skip("kpi_cards", [column for column, _, _ in KPI_CARD_COLUMNS])

    return {
        "component_id": "kpi_cards",
        "type": "kpi_cards",
        "title": "Daily KPI Summary",
        "cards": available_cards,
    }, None


def _generation_vs_gti(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    required = ["date", "generation_kwh", "gti_kwh_m2"]
    missing = _missing(df, required)
    if missing:
        return None, _skip("generation_vs_gti_chart", missing)

    return {
        "component_id": "generation_vs_gti_chart",
        "type": "bar_line",
        "title": "Generation vs GTI",
        "x": _values(df, "date"),
        "series": [
            {
                "name": "Generation",
                "metric": "generation_kwh",
                "type": "bar",
                "unit": "kWh",
                "y": _values(df, "generation_kwh"),
            },
            {
                "name": "GTI",
                "metric": "gti_kwh_m2",
                "type": "line",
                "unit": "kWh/m2",
                "y": _values(df, "gti_kwh_m2"),
                "axis": "right",
            },
        ],
    }, None


def _line_chart(
    df: pd.DataFrame,
    component_id: str,
    title: str,
    metric: str,
    label: str,
    unit: str,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    required = ["date", metric]
    missing = _missing(df, required)
    if missing:
        return None, _skip(component_id, missing)

    return {
        "component_id": component_id,
        "type": "line",
        "title": title,
        "x": _values(df, "date"),
        "series": [{
            "name": label,
            "metric": metric,
            "type": "line",
            "unit": unit,
            "y": _values(df, metric),
        }],
    }, None


def _loss_breakdown(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    loss_columns = [
        ("outage_loss_kwh", "Outage Loss"),
        ("environmental_loss_kwh", "Environmental Loss"),
        ("clipping_loss_kwh", "Clipping Loss"),
        ("total_loss_kwh", "Total Loss"),
    ]
    available = [
        (column, label)
        for column, label in loss_columns
        if column in df.columns
    ]

    if "date" not in df.columns:
        return None, _skip("loss_breakdown_chart", ["date"])

    if not available:
        return None, _skip(
            "loss_breakdown_chart",
            [column for column, _ in loss_columns],
        )

    return {
        "component_id": "loss_breakdown_chart",
        "type": "stacked_bar",
        "title": "Loss Breakdown",
        "x": _values(df, "date"),
        "series": [
            {
                "name": label,
                "metric": column,
                "type": "bar",
                "unit": "kWh",
                "y": _values(df, column),
            }
            for column, label in available
        ],
    }, None


def _inv_pow_gti(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    timeseries = (supplementary_data or {}).get("daily_timeseries")
    if timeseries is None:
        return None, _skip("inv_pow_gti_chart", ["daily_timeseries"])

    required = ["timestamp", "inv_power_kw", "gti_wm2"]
    missing = _missing(timeseries, required)
    if missing:
        return None, _skip("inv_pow_gti_chart", missing)

    return {
        "component_id": "inv_pow_gti_chart",
        "type": "dual_axis_line",
        "title": "Inverter Power vs GTI",
        "x": _values(timeseries, "timestamp"),
        "series": [
            {
                "name": "Inverter Power",
                "metric": "inv_power_kw",
                "type": "line",
                "unit": "kW",
                "y": _values(timeseries, "inv_power_kw"),
            },
            {
                "name": "GTI",
                "metric": "gti_wm2",
                "type": "line",
                "unit": "W/m2",
                "axis": "right",
                "y": _values(timeseries, "gti_wm2"),
            },
        ],
    }, None


def _inverter_pr_table(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    inverter_df = (supplementary_data or {}).get("inverter_performance")
    if inverter_df is None:
        return None, _skip("inverter_pr_table", ["inverter_performance"])

    required = ["inverter_id", "pr_percent"]
    missing = _missing(inverter_df, required)
    if missing:
        return None, _skip("inverter_pr_table", missing)

    columns = [
        column for column in [
            "inverter_id",
            "pr_percent",
            "status",
            "generation_kwh",
            "availability_percent",
            "deviation_from_fleet_avg_pct",
        ]
        if column in inverter_df.columns
    ]

    return {
        "component_id": "inverter_pr_table",
        "type": "table",
        "title": "Inverter PR Table",
        "columns": columns,
        "rows": [
            {
                column: _json_value(row[column])
                for column in columns
            }
            for _, row in inverter_df.iterrows()
        ],
    }, None


def _loss_waterfall(
    df: pd.DataFrame,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[dict | None, dict | None]:
    required = ["expected_generation_kwh", "generation_kwh"]
    missing = _missing(df, required)
    if missing:
        return None, _skip("loss_waterfall", missing)

    latest = df.iloc[-1]
    steps = [{
        "label": "Expected Generation",
        "metric": "expected_generation_kwh",
        "value": _json_value(latest["expected_generation_kwh"]),
        "type": "absolute",
        "unit": "kWh",
    }]

    for column, label in [
        ("outage_loss_kwh", "Outage Loss"),
        ("environmental_loss_kwh", "Environmental Loss"),
        ("clipping_loss_kwh", "Clipping Loss"),
    ]:
        if column in df.columns:
            steps.append({
                "label": label,
                "metric": column,
                "value": -abs(_json_value(latest[column]) or 0),
                "type": "relative",
                "unit": "kWh",
            })

    steps.append({
        "label": "Actual Generation",
        "metric": "generation_kwh",
        "value": _json_value(latest["generation_kwh"]),
        "type": "total",
        "unit": "kWh",
    })

    return {
        "component_id": "loss_waterfall",
        "type": "waterfall",
        "title": "Generation vs Losses Waterfall",
        "steps": steps,
    }, None


CHART_BUILDERS = {
    "kpi_cards": _kpi_cards,
    "generation_vs_gti_chart": _generation_vs_gti,
    "inv_pow_gti_chart": _inv_pow_gti,
    "inverter_pr_table": _inverter_pr_table,
    "loss_waterfall": _loss_waterfall,
    "pr_trend_chart": lambda df, supplementary_data=None: _line_chart(
        df,
        "pr_trend_chart",
        "PR Trend",
        "pr_percent",
        "PR",
        "%",
        supplementary_data,
    ),
    "specific_yield_trend_chart": lambda df, supplementary_data=None: _line_chart(
        df,
        "specific_yield_trend_chart",
        "Specific Yield Trend",
        "specific_yield_kwh_per_kwp",
        "Specific Yield",
        "kWh/kWp",
        supplementary_data,
    ),
    "data_availability_trend_chart": lambda df, supplementary_data=None: _line_chart(
        df,
        "data_availability_trend_chart",
        "Data Availability Trend",
        "data_availability_percent",
        "Data Availability",
        "%",
        supplementary_data,
    ),
    "loss_breakdown_chart": _loss_breakdown,
}


def build_chart_specs(
    calculation_result_or_df: dict | pd.DataFrame,
    answer_plan: dict | None = None,
    requested_components: list[str] | None = None,
    supplementary_data: dict[str, pd.DataFrame] | None = None,
) -> dict:
    """
    Builds frontend/report-renderer chart specs from calculated KPI data.

    This function does not design pages or export images. It prepares structured
    components that answer_planner.py has requested.
    """
    df = _rows_to_dataframe(calculation_result_or_df)

    if requested_components is None:
        requested_components = (
            (answer_plan or {}).get("requested_components")
            or DEFAULT_COMPONENTS
        )

    chart_specs = []
    skipped_charts = []

    if df.empty:
        return {
            "valid": False,
            "status": "blocked",
            "chart_specs": [],
            "skipped_charts": [],
            "warnings": ["No calculated rows were provided for chart generation."],
            "action_required": [{
                "type": "calculate_kpis_first",
                "message": "Calculate KPIs before building chart specs.",
            }],
        }

    for component_id in dict.fromkeys(requested_components):
        builder = CHART_BUILDERS.get(component_id)
        if not builder:
            skipped_charts.append({
                "component_id": component_id,
                "reason": "unknown_component",
                "message": f"No chart builder exists for {component_id}.",
            })
            continue

        spec, skipped = builder(df, supplementary_data)
        if spec:
            chart_specs.append(spec)
        if skipped:
            skipped_charts.append(skipped)

    return {
        "valid": True,
        "status": "ready",
        "chart_specs": chart_specs,
        "skipped_charts": skipped_charts,
        "warnings": [],
        "action_required": [],
    }
