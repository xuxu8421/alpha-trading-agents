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


def extract_thesis_snapshot(state: dict) -> dict:
    """Extract reviewable claims from a completed V2 graph state."""
    final_report = state.get("final_report", "")
    meta = parse_report_meta(final_report)
    expectation = state.get("expectation_report", "")
    return {
        "ticker": state.get("company_of_interest", ""),
        "report_date": state.get("trade_date", ""),
        "macro_claim": _claim_excerpt(state.get("macro_report") or state.get("policy_report", "")),
        "industry_claim": _claim_excerpt(state.get("industry_report", "")),
        "company_claim": _claim_excerpt(
            state.get("financial_report") or state.get("fundamentals_report", "")
        ),
        "expectation_claim": _claim_excerpt(expectation),
        "action": normalize_action(meta.get("action", ""), meta.get("rating", ""), final_report),
        "horizon": _extract_horizon(expectation or final_report),
        "confidence": extract_confidence(expectation + "\n" + final_report),
        "catalysts": _extract_tagged_lines(expectation + "\n" + final_report, ("催化", "触发")),
        "invalidations": _extract_tagged_lines(
            expectation + "\n" + final_report,
            ("失效", "证伪", "推翻", "若", "如果"),
        ),
    }


def _claim_excerpt(text: str, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _extract_horizon(text: str) -> str:
    match = re.search(r"(?:T\+\s*)?(1|5|10|20|60)\s*(?:个?交易日|日)", text or "", re.I)
    return f"T+{match.group(1)}" if match else "T+5"


def _extract_tagged_lines(text: str, keywords: tuple[str, ...]) -> list[str]:
    chunks = re.split(r"[\n。；]", text or "")
    found = []
    for chunk in chunks:
        clean = re.sub(r"\s+", " ", chunk).strip(" -*#：:")
        if clean and any(keyword in clean for keyword in keywords):
            found.append(clean[:300])
    return found[:10]


def scan_degradations(state: dict) -> list[DegradationEvent]:
    events: list[DegradationEvent] = []
    sections = {
        "market": state.get("market_report", ""),
        "sentiment": state.get("sentiment_report", ""),
        "news": state.get("news_report", ""),
        "fundamentals": state.get("fundamentals_report", ""),
        "policy": state.get("policy_report", ""),
        "macro": state.get("macro_report", ""),
        "industry": state.get("industry_report", ""),
        "financial_report": state.get("financial_report", ""),
        "expectation": state.get("expectation_report", ""),
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
