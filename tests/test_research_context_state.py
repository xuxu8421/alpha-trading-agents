from tradingagents.graph.propagation import Propagator


def test_initial_state_contains_v2_research_context_fields():
    state = Propagator().create_initial_state("300496", "2026-07-14")

    for field in (
        "macro_report",
        "industry_report",
        "financial_report",
        "expectation_report",
        "evidence_ledger",
        "position_context",
    ):
        assert field in state
        assert state[field] == ""
