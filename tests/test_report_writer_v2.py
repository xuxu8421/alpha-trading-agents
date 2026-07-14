from types import SimpleNamespace

from tradingagents.agents.managers.report_writer import create_report_writer


class _CaptureLLM:
    def __init__(self):
        self.prompt = ""

    def invoke(self, prompt):
        self.prompt = prompt
        return SimpleNamespace(content='<!--META {"rating":"持有"}-->\n## 摘要与决策')


def test_report_writer_keeps_meta_and_receives_v2_decision_materials():
    llm = _CaptureLLM()
    node = create_report_writer(llm)
    state = {
        "company_of_interest": "300496",
        "trade_date": "2026-07-14",
        "macro_report": "宏观传导",
        "industry_report": "行业位置",
        "financial_report": "财报质量",
        "expectation_report": "预期差",
        "position_context": "重仓浮亏30%",
        "investment_debate_state": {},
        "risk_debate_state": {},
    }
    result = node(state)

    assert result["final_report"].startswith("<!--META")
    for material in ("宏观传导", "行业位置", "财报质量", "预期差", "重仓浮亏30%"):
        assert material in llm.prompt
    for section in ("宏观到行业的传导", "行业位置与预期", "财报质量", "情景矩阵", "交易决策", "失效条件"):
        assert section in llm.prompt
