"""Industry-level research node connecting macro policy to company analysis."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.rnd.config import STOCK_UNIVERSE
from tradingagents.rnd.industry_chain import build_industry_chain_brief


def _ticker_variants(ticker: str) -> set[str]:
    value = str(ticker).upper().strip()
    base = value.split(".")[0]
    return {value, base, f"{base}.SZ", f"{base}.SH", f"{base}.SS"}


def build_industry_evidence(ticker: str) -> dict[str, Any]:
    """Return a compact, traceable industry packet for one instrument."""
    brief = build_industry_chain_brief(STOCK_UNIVERSE)
    variants = _ticker_variants(ticker)
    company = next(
        (row for row in brief["company_index"] if row["ticker"].upper() in variants),
        None,
    )
    intelligence = brief.get("daily_intelligence", {})
    if company is None:
        company = {
            "ticker": str(ticker).upper(),
            "name": str(ticker),
            "tracked": False,
            "links": [],
        }
        limitations = ["该标的尚未进入本地产业链映射，禁止凭主题联想补造上下游关系。"]
    else:
        company = {**company, "tracked": True}
        limitations = []

    track_ids = {link.get("track") for link in company.get("links", [])}
    tracks = [
        track
        for track in brief.get("tracks", [])
        if track.get("id") in track_ids
    ]
    signals = [
        signal
        for signal in intelligence.get("signals", [])
        if not track_ids
        or track_ids.intersection(
            {
                str(item).lower().replace(" ", "_")
                for item in signal.get("affected_tracks", [])
            }
        )
    ]
    if not signals:
        signals = intelligence.get("signals", [])[:3]

    return {
        "company": company,
        "tracks": tracks,
        "industry_regime": intelligence.get("regime", {}),
        "signals": signals[:5],
        "quality": intelligence.get("quality", {}),
        "evidence_legend": brief.get("evidence_legend", []),
        "limitations": limitations,
    }


def create_industry_analyst(llm):
    def industry_analyst_node(state):
        ticker = state["company_of_interest"]
        evidence = build_industry_evidence(ticker)
        macro = state.get("macro_report") or state.get("policy_report", "")
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是产业研究负责人。你的任务不是复述公司新闻，而是把国家/宏观变量沿产业链传导到公司。

必须依次回答：行业边界与价值链、供需/周期阶段、关键瓶颈与议价权、竞争格局和可比公司、政策传导、市场一致预期、未来1周/1季/1年的验证指标、失效条件。严格区分“已验证、业务匹配、待核验”；没有证据时明确降级，不得把业务匹配写成订单确认。

宏观政策上文：
{macro_report}

产业证据包：
{industry_evidence}

输出简洁但完整的 Markdown 行业报告，并明确该公司处于行业什么位置、相对同业强弱来自哪里。{language}""",
                ),
                ("human", "研究标的：{ticker}；研究日期：{trade_date}"),
            ]
        )
        chain = prompt | llm
        result = chain.invoke(
            {
                "ticker": ticker,
                "trade_date": state["trade_date"],
                "macro_report": macro,
                "industry_evidence": json.dumps(evidence, ensure_ascii=False, default=str),
                "language": get_language_instruction(),
            }
        )
        report = result.content if hasattr(result, "content") else str(result)
        ledger = json.dumps(
            {"industry": evidence, "as_of": state["trade_date"]},
            ensure_ascii=False,
            default=str,
        )
        return {
            "messages": [AIMessage(content=report)],
            "industry_report": report,
            "evidence_ledger": ledger,
        }

    return industry_analyst_node
