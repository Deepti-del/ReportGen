import os
import sys

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
DATA_PATH = os.path.join(
    ROOT_DIR,
    "data",
    "Alpha_Solar_Dummy_Dataset.xlsx",
)

sys.path.insert(0, BACKEND_DIR)

import database
from answer_planner import build_answer_plan
from calculator import calculate_daily_kpis_from_excel
from charts import build_chart_specs
from formula_service import approve_suggested_formula
from insights import generate_insights
from mapper import apply_mapping, confirm_alpha_solar_daily_kpi_mappings
from report_draft import assemble_report_draft
from validator import validate_workbook


CUSTOMER_ID = "alpha_solar"
REPORT_TYPE = "daily_generation"
EVENT_DATE = "2025-06-14"


def _setup_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "reportgen.db"))
    database.create_tables()
    database.seed_default_data()
    confirm_alpha_solar_daily_kpi_mappings()


def _filter_date(df: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    dates = pd.to_datetime(df[date_column]).dt.strftime("%Y-%m-%d")
    return df[dates == EVENT_DATE].copy()


def _prepare_event_context(calculation: dict, workbook: dict[str, pd.DataFrame]) -> pd.DataFrame:
    enriched_df = pd.DataFrame([
        {
            key: value
            for key, value in row.items()
            if key not in ("metric_sources", "changes")
        }
        for row in calculation["rows"]
    ])

    event_mask = pd.to_datetime(enriched_df["date"]).dt.strftime("%Y-%m-%d") == EVENT_DATE
    event_index = enriched_df.index[event_mask][0]

    event_losses = _filter_date(workbook["loss_events"])
    curtailment = event_losses[event_losses["loss_type"] == "grid_curtailment"]
    curtailment_event_present = int(not curtailment.empty)
    missing_curtailment_note = int(
        curtailment_event_present
        and curtailment["note"].isna().any()
    )

    event_inverters = _filter_date(workbook["inverter_performance"])
    inv_a01 = event_inverters[event_inverters["inverter_id"] == "INV_A01"].iloc[0]

    enriched_df["curtailment_event_present"] = 0
    enriched_df["missing_curtailment_note"] = 0
    enriched_df["inv_a01_pr_percent"] = pd.NA
    enriched_df["fleet_pr_percent"] = pd.NA

    enriched_df.loc[event_index, "curtailment_event_present"] = curtailment_event_present
    enriched_df.loc[event_index, "missing_curtailment_note"] = missing_curtailment_note
    enriched_df.loc[event_index, "inv_a01_pr_percent"] = inv_a01["pr_percent"]
    enriched_df.loc[event_index, "fleet_pr_percent"] = enriched_df.loc[
        event_index,
        "pr_percent",
    ]

    return enriched_df


def _approve_event_day_configuration(daily_kpis: pd.DataFrame):
    approve_suggested_formula(
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
        output_column="specific_yield_kwh_per_kwp",
        scope="customer_report_type",
        available_columns=list(daily_kpis.columns),
    )

    database.approve_insight_rule(
        rule_name="PR drop",
        condition="pr_percent < prev_day_pr_percent * (1 - pr_drop_threshold_pct / 100)",
        input_columns=["pr_percent", "prev_day_pr_percent"],
        thresholds={"pr_drop_threshold_pct": 10},
        severity="high",
        message_template="PR dropped more than {pr_drop_threshold_pct}% vs previous day.",
        suggestion_template="Use PR trend and Inv_Pow vs GTI evidence to explain the drop.",
        scope="customer_report_type",
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )

    database.approve_insight_rule(
        rule_name="Plant-side event",
        condition="curtailment_event_present == 1 and missing_curtailment_note == 1",
        input_columns=["curtailment_event_present", "missing_curtailment_note"],
        thresholds={},
        severity="high",
        message_template="Grid curtailment occurred and needs an annotation.",
        suggestion_template="Add note: PR impacted by grid curtailment 14:10-15:48.",
        scope="customer_report_type",
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )

    database.approve_insight_rule(
        rule_name="INV_A01 underperformance",
        condition="inv_a01_pr_percent < fleet_pr_percent * 0.90",
        input_columns=["inv_a01_pr_percent", "fleet_pr_percent"],
        thresholds={},
        severity="medium",
        message_template="INV_A01 PR is more than 10% below fleet PR.",
        suggestion_template="Review INV_A01 status and inverter PR table before publishing.",
        scope="customer_report_type",
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )

    database.approve_customer_question(
        question_text="Explain the June 14 daily generation event.",
        answer_purpose=(
            "Answer whether the PR drop is visible, whether plant-side evidence "
            "exists, and which inverter underperformed."
        ),
        required_metrics=["date", "pr_percent", "generation_kwh"],
        preferred_components=[
            "pr_trend_chart",
            "inv_pow_gti_chart",
            "inverter_pr_table",
            "loss_waterfall",
        ],
        scope="customer_report_type",
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )


def test_event_day_end_to_end(monkeypatch, tmp_path):
    _setup_temp_db(monkeypatch, tmp_path)

    workbook = pd.read_excel(DATA_PATH, sheet_name=None)
    daily_kpis = workbook["daily_kpis"]
    _approve_event_day_configuration(daily_kpis)

    validation = validate_workbook(
        DATA_PATH,
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )

    mapping = apply_mapping(daily_kpis, CUSTOMER_ID)
    calculation = calculate_daily_kpis_from_excel(
        DATA_PATH,
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )
    enriched_df = _prepare_event_context(calculation, workbook)
    event_row = enriched_df[
        pd.to_datetime(enriched_df["date"]).dt.strftime("%Y-%m-%d") == EVENT_DATE
    ].iloc[0]

    event_context_df = enriched_df[
        pd.to_datetime(enriched_df["date"]).dt.strftime("%Y-%m-%d") == EVENT_DATE
    ].copy()

    insights = generate_insights(
        event_context_df,
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
    )
    answer_plan = build_answer_plan(
        event_context_df,
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
        insights_result=insights,
    )
    chart_specs = build_chart_specs(
        enriched_df,
        answer_plan=answer_plan,
        supplementary_data={
            "daily_timeseries": workbook["daily_timeseries"],
            "inverter_performance": _filter_date(workbook["inverter_performance"]),
        },
    )
    draft = assemble_report_draft(
        customer_id=CUSTOMER_ID,
        report_type=REPORT_TYPE,
        report_date=EVENT_DATE,
        validation_result=validation,
        mapping_result=mapping,
        calculation_result=calculation,
        insights_result=insights,
        answer_plan=answer_plan,
        chart_result=chart_specs,
    )

    finding_summary = ", ".join(
        f"{finding['rule_name']} ({finding['severity']})"
        for finding in insights["findings"]
    )
    component_summary = ", ".join(answer_plan["requested_components"])

    print("\nEvent day end-to-end run")
    print(f"Validation: {'passed' if validation['valid'] else 'failed'}")
    print(
        "Mapping: "
        f"{len(mapping['mapped'])} columns "
        f"{'confirmed' if mapping['confirmed'] else 'unconfirmed'}"
    )
    print(
        "Calculation: "
        f"PR {event_row['pr_percent']:.2f}%, "
        f"generation {event_row['generation_kwh']:,.0f} kWh, "
        f"specific yield {event_row['specific_yield_kwh_per_kwp']:.3f}"
    )
    print(f"Insights: {len(insights['findings'])} findings - {finding_summary}")
    print(f"Answer plan: includes {component_summary}")
    print(f"Chart specs: {len(chart_specs['chart_specs'])} specs generated")
    print(
        "Report draft: "
        f"{draft['status']}, "
        f"{len(draft['triggered_findings'])} findings, "
        f"{len(draft['chart_specs'])} charts, "
        f"{len(draft['tables'])} tables"
    )

    assert validation["valid"] is True
    assert mapping["confirmed"] is True
    assert len(mapping["mapped"]) == 18
    assert calculation["status"] == "ready"
    assert round(event_row["pr_percent"], 2) == 50.88
    assert round(event_row["generation_kwh"], 0) == 513700
    assert round(event_row["specific_yield_kwh_per_kwp"], 3) == 3.805
    assert [finding["rule_name"] for finding in insights["findings"]] == [
        "PR drop",
        "Plant-side event",
        "INV_A01 underperformance",
    ]
    assert answer_plan["requested_components"] == [
        "pr_trend_chart",
        "inv_pow_gti_chart",
        "inverter_pr_table",
        "loss_waterfall",
    ]
    assert [chart["component_id"] for chart in chart_specs["chart_specs"]] == [
        "pr_trend_chart",
        "inv_pow_gti_chart",
        "inverter_pr_table",
        "loss_waterfall",
    ]
    assert draft["status"] == "draft_ready"
    assert draft["report_date"] == EVENT_DATE
    assert len(draft["triggered_findings"]) == 3
    assert [chart["component_id"] for chart in draft["chart_specs"]] == [
        "pr_trend_chart",
        "inv_pow_gti_chart",
        "loss_waterfall",
    ]
    assert [table["component_id"] for table in draft["tables"]] == [
        "inverter_pr_table",
    ]
