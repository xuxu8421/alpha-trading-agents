from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DegradationEvent:
    module: str
    severity: str
    message: str
    optimization_hint: str


def parse_report_meta(final_report: str) -> dict:
    match = re.search(r"<!--\s*META\s*(\{.*?\})\s*-->", final_report or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except Exception:
        return {}


def normalize_action(*values: str) -> str:
    text = " ".join(v or "" for v in values).lower()
    if any(token in text for token in ("sell", "卖出", "清仓", "减持", "离场")):
        return "sell"
    if any(token in text for token in ("buy", "买入", "增持", "建仓", "加仓")):
        return "buy"
    if any(token in text for token in ("hold", "持有", "观望", "中性")):
        return "hold"
    return "unknown"


def extract_confidence(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"(?:confidence|置信度)[:：]?\s*(高|中|低|high|medium|low|[0-9]+(?:\.[0-9]+)?)", text, re.I)
    if not match:
        return None
    raw = match.group(1).lower()
    if raw in ("高", "high"):
        return 0.85
    if raw in ("中", "medium"):
        return 0.6
    if raw in ("低", "low"):
        return 0.35
    val = float(raw)
    return val / 100 if val > 1 else val


def run_summary_from_state(state: dict) -> dict:
    final_report = state.get("final_report", "")
    final_decision = state.get("final_trade_decision", "")
    trader_decision = state.get("trader_investment_decision", "")
    meta = parse_report_meta(final_report)
    action = normalize_action(meta.get("action", ""), meta.get("rating", ""))
    if action == "unknown":
        action = normalize_action(final_decision, trader_decision)
    return {
        "ticker": state.get("company_of_interest", ""),
        "report_date": state.get("trade_date", ""),
        "rating": meta.get("rating", ""),
        "action": action,
        "confidence": extract_confidence(final_report + "\n" + final_decision),
        "entry": meta.get("entry", ""),
        "stop": meta.get("stop", ""),
        "target": meta.get("target", ""),
        "excerpt": _excerpt(final_report or final_decision),
        "final_report_len": len(final_report or ""),
    }


def scan_degradations(state: dict) -> list[DegradationEvent]:
    events: list[DegradationEvent] = []
    sections = {
        "market": state.get("market_report", ""),
        "sentiment": state.get("sentiment_report", ""),
        "news": state.get("news_report", ""),
        "fundamentals": state.get("fundamentals_report", ""),
        "policy": state.get("policy_report", ""),
        "research": state.get("investment_plan", ""),
        "trader": state.get("trader_investment_decision", ""),
        "portfolio": state.get("final_trade_decision", ""),
        "final_report": state.get("final_report", ""),
    }
    for module, text in sections.items():
        if not text:
            events.append(
                DegradationEvent(
                    module=module,
                    severity="high" if module in {"market", "fundamentals", "final_report"} else "medium",
                    message=f"{module} output is empty",
                    optimization_hint=f"Strengthen the {module} agent or data path; empty output should block publication or trigger fallback content.",
                )
            )
            continue
        lowered = text.lower()
        if "no_data_available" in lowered:
            events.append(
                DegradationEvent(
                    module=module,
                    severity="high",
                    message=_first_matching_line(text, "NO_DATA_AVAILABLE"),
                    optimization_hint=f"Add an A-share-native data source or parser for {module}; do not let this remain a passive sentinel.",
                )
            )
        if "data_unavailable" in lowered or "fred_api_key" in lowered:
            events.append(
                DegradationEvent(
                    module=module,
                    severity="medium",
                    message=_first_matching_line(text, "DATA_UNAVAILABLE") or _first_matching_line(text, "FRED_API_KEY"),
                    optimization_hint=f"Either configure the optional provider or replace it with an A-share-relevant proxy for {module}.",
                )
            )
        if "error retrieving" in lowered or "获取失败" in text:
            events.append(
                DegradationEvent(
                    module=module,
                    severity="medium",
                    message=_first_matching_line(text, "Error retrieving") or _first_matching_line(text, "获取失败"),
                    optimization_hint=f"Convert this {module} failure into a typed fallback and add a regression test.",
                )
            )
    return events


def _first_matching_line(text: str, needle: str) -> str:
    needle_lower = needle.lower()
    for line in (text or "").splitlines():
        if needle_lower in line.lower():
            return line.strip()[:500]
    return ""


def _excerpt(text: str, limit: int = 360) -> str:
    clean = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit]
