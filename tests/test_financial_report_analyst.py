from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tradingagents.agents.analysts.financial_reading_framework import (
    financial_reading_framework,
)
from tradingagents.agents.analysts.financial_report_analyst import (
    compact_statement_data,
    create_financial_report_analyst,
    prefetch_statement_data,
)


def test_financial_framework_is_falsification_first_and_industry_aware():
    framework = financial_reading_framework("300496", "AI软件与智能汽车行业")

    for item in ("审计意见", "资产负债表", "利润质量", "现金流", "附注", "五年纵向", "同业横向", "造假痕迹"):
        assert item in framework
    assert "研发资本化" in framework
    assert framework.index("排雷") < framework.index("估值")


def test_statement_prefetch_is_deterministic_and_keeps_failures_visible():
    def fake_call(_ticker, freq, _date):
        if freq == "annual":
            return "annual-data"
        raise RuntimeError("quarterly unavailable")

    with (
        patch("tradingagents.agents.analysts.financial_report_analyst.get_balance_sheet.func", fake_call),
        patch("tradingagents.agents.analysts.financial_report_analyst.get_income_statement.func", fake_call),
        patch("tradingagents.agents.analysts.financial_report_analyst.get_cashflow.func", fake_call),
    ):
        packet = prefetch_statement_data("300496", "2026-07-14")

    assert packet["annual"]["balance_sheet"] == "annual-data"
    assert "quarterly unavailable" in packet["quarterly"]["cashflow"]


def test_financial_agent_consumes_industry_context_and_returns_own_report():
    llm = FakeListChatModel(responses=["财报结论：现金含量需继续验证。"])
    node = create_financial_report_analyst(llm)
    state = {
        "company_of_interest": "300496",
        "trade_date": "2026-07-14",
        "industry_report": "行业处于端侧 AI 商业化验证期。",
        "fundamentals_report": "基础财务摘要。",
        "evidence_ledger": "{}",
    }
    with patch(
        "tradingagents.agents.analysts.financial_report_analyst.prefetch_statement_data",
        return_value={"annual": {}, "quarterly": {}, "limitations": ["测试限制"]},
    ):
        result = node(state)

    assert result["financial_report"].startswith("财报结论")
    assert "financial_statements" in result["evidence_ledger"]


def test_statement_compaction_keeps_periods_and_material_columns():
    raw = (
        "# Income Statement\n"
        "报告期,营业总收入,营业总收入_同比,无关字段\n"
        "2025-12-31,100,0.20,999\n"
        "2025-09-30,70,0.15,888\n"
    )
    packet = {
        "annual": {"income_statement": raw},
        "quarterly": {"income_statement": raw},
        "limitations": [],
        "as_of": "2026-07-14",
    }
    compact = compact_statement_data(packet)
    text = compact["annual"]["income_statement"]
    assert "2025-12-31" in text
    assert "营业总收入_同比" in text
    assert "无关字段" not in text
    assert compact["quarterly"]["income_statement"].startswith("[duplicate")
