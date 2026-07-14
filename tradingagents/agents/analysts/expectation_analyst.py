"""Expectation-gap synthesis across macro, industry, company, and price."""

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_expectation_analyst(llm):
    def expectation_analyst_node(state):
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是预期差分析师。Alpha 不等于“公司好”，而等于“未来实际结果相对当前价格隐含预期的偏差”。禁止把宏观、行业、公司三个层级混成一句叙事。

请依次输出：
1. 已知事实与仍属预测的内容；
2. 国家/宏观层的市场共识、你的判断、差异和传导路径；
3. 行业层的市场共识、景气/竞争/估值隐含假设和差异；
4. 公司层的收入、利润、现金流、资本回报与市场隐含假设；
5. 牛/基/熊情景矩阵，每项含期限、概率、关键数字/方向、催化剂、失效条件；
6. 未来1周/1季/1年的验证清单；
7. 当前价格若缺失，明确写“无法量化价格隐含预期”，只能做定性判断。

宏观报告：{macro}
行业报告：{industry}
财报报告：{financial}
基本面报告：{fundamentals}
行情报告：{market}
新闻报告：{news}
情绪报告：{sentiment}

结尾给出一句可证伪的核心判断。{language}""",
                ),
                ("human", "标的 {ticker}，分析日 {trade_date}"),
            ]
        )
        result = (prompt | llm).invoke(
            {
                "ticker": state["company_of_interest"],
                "trade_date": state["trade_date"],
                "macro": state.get("macro_report", ""),
                "industry": state.get("industry_report", ""),
                "financial": state.get("financial_report", ""),
                "fundamentals": state.get("fundamentals_report", ""),
                "market": state.get("market_report", ""),
                "news": state.get("news_report", ""),
                "sentiment": state.get("sentiment_report", ""),
                "language": get_language_instruction(),
            }
        )
        report = result.content if hasattr(result, "content") else str(result)
        return {
            "messages": [AIMessage(content=report)],
            "expectation_report": report,
        }

    return expectation_analyst_node
