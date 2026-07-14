from unittest.mock import Mock

from tradingagents.graph.setup import GraphSetup


class _ConditionalLogic:
    def __getattr__(self, _name):
        return lambda _state: ""


def test_graph_starts_with_macro_then_industry_before_selected_analysts():
    tools = {key: (lambda _state: {}) for key in ("market", "social", "news", "fundamentals")}
    workflow = GraphSetup(Mock(), Mock(), tools, _ConditionalLogic()).setup_graph(["market"])

    assert ("__start__", "Policy Analyst") in workflow.edges
    assert ("Policy Analyst", "Industry Analyst") in workflow.edges
    assert ("Industry Analyst", "Market Analyst") in workflow.edges
