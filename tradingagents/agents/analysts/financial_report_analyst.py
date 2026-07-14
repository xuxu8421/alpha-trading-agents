"""Dedicated financial-report analyst with deterministic statement inputs."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_language_instruction,
)
from tradingagents.dataflows.config import get_config

from .financial_reading_framework import financial_reading_framework

STATEMENT_TOOLS = {
    "balance_sheet": get_balance_sheet,
    "income_statement": get_income_statement,
    "cashflow": get_cashflow,
}

_MATERIAL_TOKENS = (
    "报告期",
    "营业收入",
    "营业总收入",
    "营业成本",
    "营业总成本",
    "研发费用",
    "销售费用",
    "管理费用",
    "财务费用",
    "营业利润",
    "利润总额",
    "净利润",
    "每股收益",
    "货币资金",
    "应收账款",
    "存货",
    "合同资产",
    "合同负债",
    "开发支出",
    "商誉",
    "无形资产",
    "固定资产",
    "资产总计",
    "负债合计",
    "短期借款",
    "长期借款",
    "股东权益",
    "所有者权益",
    "经营活动产生的现金流量净额",
    "投资活动产生的现金流量净额",
    "筹资活动产生的现金流量净额",
    "现金及现金等价物净增加额",
    "购建固定资产",
)


def _compact_statement(text: str) -> str:
    """Keep all periods but only decision-relevant statement columns."""
    if not text or "\n" not in text or text.startswith("数据不可用"):
        return text
    lines = text.splitlines()
    csv_start = next(
        (index for index, line in enumerate(lines) if "," in line and not line.startswith("#")),
        None,
    )
    if csv_start is None:
        return text
    reader = csv.DictReader(io.StringIO("\n".join(lines[csv_start:])))
    fields = reader.fieldnames or []
    selected = [
        field
        for field in fields
        if any(token in field.removesuffix("_同比") for token in _MATERIAL_TOKENS)
    ]
    if not selected:
        return text
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=selected, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(reader)
    source_headers = [line for line in lines[:csv_start] if line.startswith("#")]
    return "\n".join(source_headers + [output.getvalue().strip()])


def compact_statement_data(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded prompt packet while preserving raw tables in the ledger."""
    compact: dict[str, Any] = {
        "annual": {},
        "quarterly": {},
        "limitations": list(packet.get("limitations", [])),
        "as_of": packet.get("as_of"),
        "source_contract": packet.get("source_contract"),
    }
    seen: dict[str, str] = {}
    for frequency in ("annual", "quarterly"):
        for name, value in packet.get(frequency, {}).items():
            rendered = _compact_statement(str(value))
            fingerprint = rendered.strip()
            if fingerprint in seen:
                compact[frequency][name] = f"[duplicate of {seen[fingerprint]}]"
            else:
                compact[frequency][name] = rendered
                seen[fingerprint] = f"{frequency}.{name}"
    return compact


def prefetch_statement_data(ticker: str, trade_date: str) -> dict[str, Any]:
    """Fetch both annual and quarterly statements without allowing LLM math."""
    packet: dict[str, Any] = {"annual": {}, "quarterly": {}, "limitations": []}
    for frequency in ("annual", "quarterly"):
        for name, tool in STATEMENT_TOOLS.items():
            try:
                packet[frequency][name] = tool.func(ticker, frequency, trade_date)
            except Exception as exc:  # data gaps must be visible, not fatal
                if get_config().get("strict_data_mode"):
                    raise
                message = f"数据不可用: {type(exc).__name__}: {exc}"
                packet[frequency][name] = message
                packet["limitations"].append(f"{frequency}.{name}: {message}")
    packet["as_of"] = trade_date
    packet["source_contract"] = "configured deterministic fundamental-data vendor"
    return packet


def create_financial_report_analyst(llm):
    def financial_report_analyst_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        industry = state.get("industry_report", "")
        statements = prefetch_statement_data(ticker, trade_date)
        prompt_statements = compact_statement_data(statements)
        framework = financial_reading_framework(ticker, industry)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是专业财报分析师。遵循“先排雷、后理解、再估值”，资产负债表优先，再用利润表和现金流量表交叉验证。

硬约束：只引用证据包里出现的数字；每个关键数字注明年报/季报及日期。无法定位原始年报页码、审计意见或附注时，必须写“未获取原文，无法确认”，不得把聚合数据伪装成原始披露。计算由确定性数据层完成；本节点负责解释、矛盾检查和提出需补证的问题。

行业上下文：
{industry_report}

基础财务节点已有摘要：
{fundamentals_report}

分析框架：
{framework}

财务报表证据包：
{statements}

输出：审计与数据边界、三表联读、资产质量、盈利质量、现金含量、资本配置、纵向趋势、同业比较、操纵/脆弱性红旗、行业专属指标、牛基熊情景和待核验证据。{language}""",
                ),
                ("human", "分析 {ticker} 截至 {trade_date} 可获得的财报。"),
            ]
        )
        result = (prompt | llm).invoke(
            {
                "ticker": ticker,
                "trade_date": trade_date,
                "industry_report": industry,
                "fundamentals_report": state.get("fundamentals_report", ""),
                "framework": framework,
                "statements": json.dumps(
                    prompt_statements, ensure_ascii=False, default=str
                ),
                "language": get_language_instruction(),
            }
        )
        report = result.content if hasattr(result, "content") else str(result)
        ledger = json.dumps(
            {
                "upstream": state.get("evidence_ledger", ""),
                "financial_statements": statements,
            },
            ensure_ascii=False,
            default=str,
        )
        return {
            "messages": [AIMessage(content=report)],
            "financial_report": report,
            "evidence_ledger": ledger,
        }

    return financial_report_analyst_node
