"""Policy & retail-discussion analyst — an A-share-specific role.

TradingAgents was built for US equities. A-shares are materially more
policy-driven (政策市) and retail-driven than US large caps, so this node adds
a lens the base framework lacks: it reads (1) the policy / macro tape (财新
内容精选 + policy-keyword-filtered company news) and (2) 雪球 retail-discussion
heat (is this stock a trending retail topic, and what themes is retail chasing),
and produces a concise read of policy catalysts/risks and retail-crowding.

Like the sentiment analyst it pre-fetches data (no tool-calling) and writes a
single ``policy_report`` field. For non-A-share tickers it no-ops with a short
note so the graph topology stays static across markets.
"""

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.dataflows.akshare_cn import fetch_cn_policy, is_a_share


def create_policy_analyst(llm):
    """Create the policy & industrial-catalyst analyst node (A-share-focused)."""

    def policy_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]

        if not is_a_share(ticker):
            note = (
                f"Policy analysis is A-share-specific and was "
                f"skipped for non-A-share ticker {ticker}."
            )
            return {
                "messages": [AIMessage(content=note)],
                "policy_report": note,
                "macro_report": note,
            }

        data = fetch_cn_policy(ticker)
        instrument_context = get_instrument_context_from_state(state)
        system_message = _build_policy_system_message(
            ticker=ticker,
            end_date=end_date,
            policy_block=data["policy_block"],
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an A-share policy & industrial-catalyst analyst, collaborating with other analysts."
                    " Today's date is {current_date}; treat it as 'now'. {instrument_context}"
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm
        result = chain.invoke(state["messages"])
        report = result.content if hasattr(result, "content") else str(result)

        return {
            "messages": [AIMessage(content=report)],
            "policy_report": report,
            "macro_report": report,
        }

    return policy_analyst_node


def _build_policy_system_message(*, ticker: str, end_date: str,
                                 policy_block: str) -> str:
    return f"""You are an A-share **policy & industrial-catalyst analyst**. A-shares are a 政策市 (policy-driven market) where regulator action, industrial policy, 国常会/部委 signals and 国家队 flows move whole sectors — often more than near-term fundamentals. Your job is to read the policy/regulatory/industrial backdrop for {ticker} as of {end_date} and tell the desk what policy catalysts and risks matter. (Retail-discussion / 雪球 crowding is handled separately by the sentiment analyst — do NOT duplicate it here; stay focused on policy & industry.)

## Data (pre-fetched)

### 政策 / 宏观 + 公司政策相关事件
财新内容精选 (macro/policy) plus policy-/industrial-relevant company news (订单/招标/补贴/监管/国产替代/标准/纳入…).
<start_of_policy>
{policy_block}
<end_of_policy>

## How to analyze

1. **国家/宏观环境**：先判断增长、流动性、信用、汇率、风险偏好和资本市场制度处于何种状态；信息不足必须标注。
2. **Policy catalysts (tailwinds)**: identify any policy/regulatory/industrial support plausibly affecting this name or its sector — 产业政策、补贴、国产替代、信创、新质生产力、招标中标、纳入白名单/目录、地方专项、国家队增持. State direction and whether it's a confirmed event vs a rumor/narrative.
3. **Policy risks (headwinds)**: 监管收紧、反垄断、出口管制、价格管制/降价、环保限产、税费、IPO/再融资/减持新规、退市风险.
4. **传导链**：逐条写成“国家变量 → 行业供需/成本/估值 → 公司收入/利润/现金流”，禁止跳步。
5. **期限与失效**：每项判断给出1周/1季/1年中的适用期限、置信度和可证伪条件。
6. **Be honest about limits**: company policy news is keyword-filtered and 财新 is market-wide macro; flag low-confidence reads. Do NOT invent policies.

## Output

Write a concise report (a short markdown table: 政策信号 · 方向(利好/利空/中性) · 证据), then 2–4 bullets of **net read** for the trader: the key policy catalyst/risk and whether the sector is in a policy tailwind / vacuum / headwind right now.

{get_language_instruction()}"""
