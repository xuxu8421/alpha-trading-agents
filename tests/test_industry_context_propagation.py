from tradingagents.agents.utils.agent_utils import get_research_context_from_state


def test_shared_research_context_contains_macro_and_industry_for_specialists():
    context = get_research_context_from_state(
        {"macro_report": "流动性中性", "industry_report": "软件行业需求分化"}
    )

    assert "流动性中性" in context
    assert "软件行业需求分化" in context
    assert "行业基准" in context
