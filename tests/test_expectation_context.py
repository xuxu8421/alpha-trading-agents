from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tradingagents.agents.analysts.expectation_analyst import create_expectation_analyst
from tradingagents.agents.utils.agent_utils import get_decision_context_from_state
from tradingagents.graph.setup import GraphSetup


class _ConditionalLogic:
    def __getattr__(self, _name):
        return lambda _state: ""


def _state():
    return {
        "company_of_interest": "300496",
        "trade_date": "2026-07-14",
        "macro_report": "宏观证据",
        "industry_report": "行业证据",
        "financial_report": "财报证据",
        "expectation_report": "预期差证据",
        "market_report": "市场证据",
        "sentiment_report": "情绪证据",
        "news_report": "新闻证据",
        "fundamentals_report": "基本面证据",
        "position_context": "重仓且浮亏30%",
    }


def test_decision_context_keeps_all_first_class_research_inputs():
    context = get_decision_context_from_state(_state())

    for evidence in ("宏观证据", "行业证据", "财报证据", "预期差证据", "重仓且浮亏30%"):
        assert evidence in context


def test_expectation_agent_produces_scenario_report():
    node = create_expectation_analyst(FakeListChatModel(responses=["基准情景：等待订单验证。"]))
    result = node(_state())

    assert result["expectation_report"].startswith("基准情景")


def test_expectation_node_sits_between_financials_and_debate():
    tools = {key: (lambda _state: {}) for key in ("market", "social", "news", "fundamentals")}
    workflow = GraphSetup(object(), object(), tools, _ConditionalLogic()).setup_graph(["market"])

    assert ("Financial Report Analyst", "Expectation Analyst") in workflow.edges
    assert ("Expectation Analyst", "Bull Researcher") in workflow.edges
