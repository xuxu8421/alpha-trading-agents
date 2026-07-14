from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import requests

from .call_auction import _parse_tencent_quotes, _request_tencent
from .config import STOCK_UNIVERSE

INDEX_SYMBOLS = [
    {"ticker": "000001.SS", "name": "上证指数"},
    {"ticker": "399001.SZ", "name": "深证成指"},
    {"ticker": "399006.SZ", "name": "创业板指"},
]

FIELD_TOLERANCE = {
    "price": 0.25,
    "change_pct": 0.35,
    "open": 0.25,
    "previous_close": 0.25,
}

RELATIVE_PRICE_TOLERANCE = 0.002


def build_data_quality_audit(conn, universe: list[dict] | None = None, audit_date: str | None = None) -> dict[str, Any]:
    audit_date = audit_date or date.today().isoformat()
    symbols = _audit_symbols(universe or STOCK_UNIVERSE)
    quote_checks = _quote_consensus_checks(symbols)
    persisted_checks = _persisted_data_checks(conn, audit_date)
    source_checks = _source_health_checks()
    report_checks = _report_assertion_checks(conn, audit_date)
    issues = [issue for group in (quote_checks, persisted_checks, source_checks, report_checks) for issue in group.get("issues", [])]
    semantic_review = _llm_semantic_review(audit_date, quote_checks, persisted_checks, source_checks, report_checks, issues)
    issues.extend(_review_issues(semantic_review))
    issues = _dedupe_issues(issues)
    hard_issues = [issue for issue in issues if issue.get("severity") == "high"]
    medium_issues = [issue for issue in issues if issue.get("severity") == "medium"]
    score = max(0, 100 - len(hard_issues) * 24 - len(medium_issues) * 10 - (len(issues) - len(hard_issues) - len(medium_issues)) * 4)
    status = "blocked" if hard_issues else "warning" if medium_issues or score < 90 else "ready"
    payload = {
        "role": "Data Auditor",
        "audit_date": audit_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "score": round(score, 1),
        "summary": _summary(status, hard_issues, medium_issues, issues),
        "policy": {
            "hard_gate": "关键行情字段单源、跨源偏差过大、同日数据混版或核心源失败时，降低或阻断投研结论。",
            "quote_consensus": "实时行情至少使用东财直连、腾讯、新浪中的两个来源交叉；成交额/换手缺失不得进入候选评分。",
            "report_gate": "研报中的关键价格、资金、估值字段必须带来源与时间，未通过核验的字段只能作为待确认线索。",
        },
        "checks": {
            "quote_consensus": quote_checks,
            "persisted_data": persisted_checks,
            "source_health": source_checks,
            "report_assertions": report_checks,
            "semantic_review": semantic_review,
        },
        "issues": issues,
    }
    _persist_audit(conn, payload)
    return payload


def latest_data_quality_audit(conn, universe: list[dict] | None = None) -> dict[str, Any]:
    audit_date = date.today().isoformat()
    row = conn.execute(
        "SELECT payload FROM data_quality_audits WHERE audit_date=?",
        (audit_date,),
    ).fetchone()
    if row:
        try:
            return json.loads(row["payload"])
        except (TypeError, ValueError, KeyError):
            pass
    return build_data_quality_audit(conn, universe, audit_date)


def _persist_audit(conn, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO data_quality_audits (
            audit_date, generated_at, status, score, summary, payload
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(audit_date) DO UPDATE SET
            generated_at=excluded.generated_at,
            status=excluded.status,
            score=excluded.score,
            summary=excluded.summary,
            payload=excluded.payload
        """,
        (
            payload["audit_date"],
            payload["generated_at"],
            payload["status"],
            payload["score"],
            payload["summary"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()


def _audit_symbols(universe: list[dict]) -> list[dict]:
    rows = INDEX_SYMBOLS + [
        {"ticker": str(item.get("ticker", "")), "name": str(item.get("name", ""))}
        for item in universe
        if item.get("ticker")
    ]
    seen = set()
    out = []
    for row in rows:
        ticker = row["ticker"].upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append({"ticker": ticker, "name": row.get("name") or ticker})
    return out[:12]


def _quote_consensus_checks(symbols: list[dict]) -> dict[str, Any]:
    providers = {
        "eastmoney": _safe(lambda: _fetch_eastmoney_quotes(symbols)),
        "tencent": _safe(lambda: _fetch_tencent_quotes(symbols)),
        "sina": _safe(lambda: _fetch_sina_quotes(symbols)),
    }
    issues = []
    rows = []
    for item in symbols:
        ticker = item["ticker"]
        values = {name: data.get(ticker) for name, data in providers.items() if isinstance(data, dict) and data.get(ticker)}
        ready_fields = {}
        field_issues = []
        if len(values) < 2:
            field_issues.append({"severity": "high", "ticker": ticker, "message": "实时行情少于两个可用来源"})
        for field, tolerance in FIELD_TOLERANCE.items():
            nums = [float(v[field]) for v in values.values() if v.get(field) is not None]
            if len(nums) < 2:
                continue
            tolerance = _field_tolerance(field, nums)
            spread = max(nums) - min(nums)
            ready_fields[field] = round(spread, 4)
            if spread > tolerance:
                field_issues.append(
                    {
                        "severity": "high" if field in {"price", "change_pct"} else "medium",
                        "ticker": ticker,
                        "field": field,
                        "message": f"{ticker} {field} 跨源偏差 {spread:.3f} 超过阈值 {tolerance}",
                    }
                )
        rows.append(
            {
                "ticker": ticker,
                "name": item.get("name", ticker),
                "providers": sorted(values),
                "provider_count": len(values),
                "spreads": ready_fields,
                "status": "warning" if field_issues else "ready",
            }
        )
        issues.extend(field_issues)
    provider_status = {
        name: {
            "status": "failed" if not isinstance(data, dict) or data.get("error") else "ready",
            "count": len(data) if isinstance(data, dict) and not data.get("error") else 0,
            "error": data.get("error") if isinstance(data, dict) else str(data),
        }
        for name, data in providers.items()
    }
    return {"status": "warning" if issues else "ready", "providers": provider_status, "rows": rows, "issues": issues}


def _field_tolerance(field: str, nums: list[float]) -> float:
    if field == "change_pct":
        return FIELD_TOLERANCE[field]
    baseline = abs(mean(nums)) if nums else 0
    return max(FIELD_TOLERANCE[field], baseline * RELATIVE_PRICE_TOLERANCE)


def _persisted_data_checks(conn, audit_date: str) -> dict[str, Any]:
    issues = []
    candidate_rows = conn.execute(
        "SELECT ticker, rank, quote_snapshot, market_snapshot, created_at FROM daily_candidates WHERE trade_date=? ORDER BY rank, ticker",
        (audit_date,),
    ).fetchall()
    if candidate_rows:
        created_days = {str(row["created_at"])[:10] for row in candidate_rows if row["created_at"]}
        market_sources = set()
        zero_amount = []
        ranks = []
        for row in candidate_rows:
            ranks.append(int(row["rank"]))
            quote = json.loads(row["quote_snapshot"] or "{}")
            market = json.loads(row["market_snapshot"] or "{}")
            market_sources.add(market.get("universe_source", "unknown"))
            if quote.get("change_pct") is not None and float(quote.get("amount_yi") or 0) <= 0:
                zero_amount.append(row["ticker"])
        if len(created_days) > 1 or len(market_sources) > 1:
            issues.append({"severity": "high", "module": "daily_candidates", "message": "同日候选股混入多批次或多套市场快照"})
        if len(ranks) != len(set(ranks)):
            issues.append({"severity": "high", "module": "daily_candidates", "message": "同日候选股 rank 重复，说明旧数据未清理"})
        if zero_amount:
            issues.append({"severity": "medium", "module": "daily_candidates", "message": f"候选股成交额缺失：{', '.join(zero_amount[:6])}"})
    else:
        issues.append({"severity": "medium", "module": "daily_candidates", "message": "今天尚无候选股数据"})

    auction = conn.execute(
        "SELECT generated_at, source_status FROM call_auction_snapshots WHERE trade_date=?",
        (audit_date,),
    ).fetchone()
    if not auction:
        issues.append({"severity": "high", "module": "call_auction", "message": "今天尚无集合竞价快照"})
    else:
        generated_at = str(auction["generated_at"])
        status = json.loads(auction["source_status"] or "{}")
        if status.get("status") != "ready":
            issues.append({"severity": "high", "module": "call_auction", "message": f"集合竞价源状态为 {status.get('status')}"})
        if generated_at[11:16] > "09:40":
            issues.append({"severity": "medium", "module": "call_auction", "message": f"集合竞价生成时间 {generated_at} 偏晚，不适合作为开盘前后即时预测"})

    return {
        "status": "warning" if issues else "ready",
        "candidate_count": len(candidate_rows),
        "issues": issues,
    }


def _source_health_checks() -> dict[str, Any]:
    checks = []
    checks.append(_source_check("eastmoney_quote", lambda: _fetch_eastmoney_quotes([{"ticker": "300496.SZ", "name": "中科创达"}])))
    checks.append(_source_check("tencent_quote", lambda: _fetch_tencent_quotes([{"ticker": "300496.SZ", "name": "中科创达"}])))
    checks.append(_source_check("sina_quote", lambda: _fetch_sina_quotes([{"ticker": "300496.SZ", "name": "中科创达"}])))
    ready_count = sum(check["status"] == "ready" for check in checks)
    severity = "medium" if ready_count >= 2 else "high"
    issues = [
        {"severity": severity, "module": check["name"], "message": check["error"]}
        for check in checks
        if check["status"] != "ready"
    ]
    return {"status": "warning" if issues else "ready", "rows": checks, "issues": issues}


def _source_check(name: str, fn) -> dict[str, Any]:
    try:
        data = fn()
        return {"name": name, "status": "ready", "count": len(data)}
    except Exception as exc:
        return {"name": name, "status": "failed", "count": 0, "error": f"{type(exc).__name__}: {exc}"}


def _report_assertion_checks(conn, audit_date: str) -> dict[str, Any]:
    """Check high-impact report assertions against source tables.

    This is intentionally narrow and strict: if a report says the latest
    dragon-tiger list is net selling while the latest event detail is net
    buying, the published conclusion is unsafe even when source health is fine.
    """
    issues = []
    rows = conn.execute(
        """
        SELECT ticker, name, report_date, log_path
        FROM runs
        WHERE report_date=?
        ORDER BY created_at DESC
        LIMIT 12
        """,
        (audit_date,),
    ).fetchall()
    checked = []
    for row in rows:
        ticker = str(row["ticker"]).upper()
        if not re.fullmatch(r"\d{6}\.(?:SZ|SS|SH|BJ)", ticker):
            continue
        report = _load_report_text(row["log_path"])
        if "龙虎榜" not in report:
            continue
        fact = _latest_lhb_fact(ticker)
        checked.append({"ticker": ticker, "name": row["name"], "lhb_fact": fact})
        if fact.get("status") != "ready":
            issues.append(
                {
                    "severity": "medium",
                    "module": "report_assertions",
                    "ticker": ticker,
                    "message": f"{ticker} 研报引用龙虎榜，但最新上榜明细回查失败：{fact.get('error')}",
                    "fix": "龙虎榜方向未核实前，报告只能写待确认，不能给出净买/净卖方向。",
                }
            )
            continue
        net = float(fact.get("net_amount") or 0)
        inst_net = float(fact.get("institution_net") or 0)
        if _claims_lhb_sell(report) and net > 0:
            issues.append(
                {
                    "severity": "high",
                    "module": "report_assertions",
                    "ticker": ticker,
                    "message": f"{ticker} 研报称龙虎榜净卖出，但最新上榜事件为净买入 {net / 1e8:+.2f} 亿",
                    "fix": "区分最新三日榜和近一月汇总，重写资金面结论并重出 PDF。",
                }
            )
        if _claims_lhb_buy(report) and net < 0:
            issues.append(
                {
                    "severity": "high",
                    "module": "report_assertions",
                    "ticker": ticker,
                    "message": f"{ticker} 研报称龙虎榜净买入，但最新上榜事件为净卖出 {net / 1e8:+.2f} 亿",
                    "fix": "区分最新三日榜和近一月汇总，重写资金面结论并重出 PDF。",
                }
            )
        if _claims_institution_sell(report) and inst_net > 0:
            issues.append(
                {
                    "severity": "high",
                    "module": "report_assertions",
                    "ticker": ticker,
                    "message": f"{ticker} 研报称机构净卖出，但最新机构专用席位净买入 {inst_net / 1e8:+.2f} 亿",
                    "fix": "按最新明细修正机构席位方向，旧汇总口径只能作为补充背景。",
                }
            )
    return {"status": "warning" if issues else "ready", "checked": checked, "issues": issues}


def _load_report_text(log_path: str | None) -> str:
    if not log_path:
        return ""
    try:
        data = json.loads(Path(log_path).read_text(encoding="utf-8"))
    except Exception:
        return ""
    parts = [
        data.get("final_report", ""),
        data.get("sentiment_report", ""),
        data.get("final_trade_decision", ""),
    ]
    return "\n".join(str(part or "") for part in parts)


def _latest_lhb_fact(ticker: str) -> dict[str, Any]:
    code = ticker.split(".")[0]
    try:
        import akshare as ak

        dates = ak.stock_lhb_stock_detail_date_em(symbol=code)
        if dates is None or len(dates) == 0:
            return {"status": "empty"}
        latest_date = str(dates.iloc[0].get("交易日", "")).replace("-", "")
        detail = ak.stock_lhb_detail_em(start_date=latest_date, end_date=latest_date)
        row = detail[detail["代码"].astype(str).str.zfill(6) == code]
        if row is None or len(row) == 0:
            return {"status": "empty", "date": latest_date}
        r = row.iloc[0]
        buy = ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="买入")
        sell = ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="卖出")
        inst_buy = _sum_lhb_seat_amount(buy, "买入金额", "机构专用")
        inst_sell = _sum_lhb_seat_amount(sell, "卖出金额", "机构专用")
        return {
            "status": "ready",
            "date": str(r.get("上榜日", latest_date)),
            "net_amount": float(r.get("龙虎榜净买额") or 0),
            "buy_amount": float(r.get("龙虎榜买入额") or 0),
            "sell_amount": float(r.get("龙虎榜卖出额") or 0),
            "institution_net": inst_buy - inst_sell,
            "institution_buy": inst_buy,
            "institution_sell": inst_sell,
            "reason": str(r.get("上榜原因", "")),
        }
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _sum_lhb_seat_amount(df, amount_col: str, token: str) -> float:
    try:
        import pandas as pd

        rows = df[df["交易营业部名称"].astype(str).str.contains(token, regex=False, na=False)]
        return float(pd.to_numeric(rows.get(amount_col), errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def _claims_lhb_sell(text: str) -> bool:
    return _claims_latest_lhb_direction(text, r"(净卖出|净卖|净流出)")


def _claims_lhb_buy(text: str) -> bool:
    return _claims_latest_lhb_direction(text, r"(净买入|净买|净流入)")


def _claims_institution_sell(text: str) -> bool:
    return _claims_latest_lhb_direction(text, r"(机构|机构专用).{0,30}(净卖出|净卖|净流出)")


def _claims_latest_lhb_direction(text: str, direction_pattern: str) -> bool:
    for sentence in re.split(r"[\n。；;！!？?]", text or ""):
        if "龙虎榜" not in sentence and "机构专用" not in sentence:
            continue
        if not re.search(direction_pattern, sentence):
            continue
        if any(token in sentence for token in ("不能解读为", "不能归因为", "不能直接判断", "不是净卖出", "是否从净卖出转为净买入")):
            continue
        is_monthly_context = any(token in sentence for token in ("近一月", "近1月", "一月汇总", "月内", "汇总口径"))
        is_latest_context = any(token in sentence for token in ("最新", "三日", "连续三个交易日", "上榜事件", "最近一次", "7月1日"))
        # Monthly aggregate facts are allowed as background. The hard gate is
        # for statements that present the latest event / three-day list itself
        # as the opposite direction.
        if is_monthly_context and not is_latest_context:
            continue
        if is_monthly_context and is_latest_context and re.search(r"(最新|三日|上榜事件).{0,60}(净买入|净买|净流入)", sentence):
            continue
        return True
    return False


def _llm_semantic_review(
    audit_date: str,
    quote_checks: dict[str, Any],
    persisted_checks: dict[str, Any],
    source_checks: dict[str, Any],
    report_checks: dict[str, Any],
    deterministic_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {
            "role": "LLM Verification Auditor",
            "status": "skipped",
            "model": "deepseek",
            "summary": "未配置 DEEPSEEK_API_KEY，语义核验未运行。",
            "findings": [
                {
                    "severity": "medium",
                    "module": "llm_verification",
                    "message": "每日数据已完成规则核验，但缺少大模型二次核验。",
                    "fix": "配置 DEEPSEEK_API_KEY 后重跑 data-audit。",
                }
            ],
        }

    model = os.getenv("RND_AUDITOR_LLM_MODEL", os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-chat")).strip() or "deepseek-chat"
    context = {
        "audit_date": audit_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "quote_consensus": _compact_quote_checks(quote_checks),
        "persisted_data": persisted_checks,
        "source_health": source_checks,
        "report_assertions": report_checks,
        "deterministic_issues": deterministic_issues,
        "display_contract": {
            "dashboard": "Alpha R&D 工作台",
            "goal": "帮助用户每日看清 A 股候选、集合竞价、市场脉搏、产业情报和研报复盘。",
            "review_scope": [
                "展示结论是否被已有数据支撑",
                "逻辑链是否跳步或把线索当事实",
                "是否存在会误导交易判断的措辞",
                "哪些信息应降级为待确认或补充来源",
            ],
        },
    }
    prompt = (
        "你是 A 股投研系统的 LLM 核验员。只基于输入 JSON 审查，不要联网，不要编造外部事实。"
        "请检查每日工作台数据的真实性支撑、逻辑合理性和前端展示是否容易误读。"
        "不要把跨源价格完全一致或 spread 为 0 单独当作问题，除非同时存在源失败、时间戳过旧或字段缺失证据。"
        "返回严格 JSON："
        '{"status":"ready|warning|blocked","summary":"一句中文结论",'
        '"findings":[{"severity":"high|medium|low","module":"模块名","message":"问题","fix":"修正建议"}]}。'
        "high 只用于会明显改变投研结论或关键事实冲突的问题；medium 用于来源不足、时间不适配或逻辑跳步；low 用于展示优化。"
        "若腾讯/新浪/东方财富中至少两个独立实时源可用且报价一致，单个源失败只能判为 medium，不能判 high；少于两个源才可阻断。"
    )
    try:
        request_kwargs = {
            "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            "json": {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            "timeout": 60,
        }
        response = None
        for attempt in range(3):
            try:
                response = requests.post("https://api.deepseek.com/chat/completions", **request_kwargs)
                response.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        assert response is not None
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        findings = parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
        return {
            "role": "LLM Verification Auditor",
            "status": parsed.get("status") if parsed.get("status") in {"ready", "warning", "blocked"} else "warning",
            "model": model,
            "summary": str(parsed.get("summary") or "LLM 核验完成。"),
            "findings": findings[:8],
        }
    except Exception as exc:
        return {
            "role": "LLM Verification Auditor",
            "status": "warning",
            "model": model,
            "summary": "LLM 核验调用失败，已保留规则核验结果。",
            "findings": [
                {
                    "severity": "medium",
                    "module": "llm_verification",
                    "message": f"DeepSeek 核验调用失败：{type(exc).__name__}",
                    "fix": "检查 DEEPSEEK_API_KEY、网络和 DeepSeek 服务状态后重跑 data-audit。",
                }
            ],
        }


def _compact_quote_checks(checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": checks.get("status"),
        "provider_status": checks.get("providers"),
        "rows": [
            {
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "provider_count": row.get("provider_count"),
                "status": row.get("status"),
                "spreads": row.get("spreads"),
            }
            for row in checks.get("rows", [])[:12]
        ],
    }


def _review_issues(review: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for finding in review.get("findings", []) or []:
        severity = finding.get("severity") if finding.get("severity") in {"high", "medium", "low"} else "medium"
        if severity == "low":
            continue
        issues.append(
            {
                "severity": severity,
                "module": finding.get("module") or "llm_verification",
                "message": str(finding.get("message") or finding.get("fix") or "LLM 核验提醒"),
                "fix": finding.get("fix"),
            }
        )
    return issues


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for issue in issues:
        key = _issue_fingerprint(issue)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _issue_fingerprint(issue: dict[str, Any]) -> tuple[Any, ...]:
    message = str(issue.get("message", ""))
    ticker_match = re.search(r"\b\d{6}\.(?:SZ|SS)\b", message)
    if ticker_match:
        for field in FIELD_TOLERANCE:
            if field in message:
                return (issue.get("severity"), ticker_match.group(0), field)
    if "集合竞价生成时间" in message and "偏晚" in message:
        return (issue.get("severity"), "call_auction", "late_generated_at")
    return (
        issue.get("severity"),
        issue.get("module") or issue.get("ticker") or issue.get("field"),
        re.sub(r"\s+", "", message),
    )


def _fetch_tencent_quotes(symbols: list[dict]) -> dict[str, dict[str, Any]]:
    raw = _request_tencent([_ticker_to_tencent_symbol(item["ticker"]) for item in symbols])
    parsed = _parse_tencent_quotes(raw)
    return {
        quote["ticker"].upper(): {
            "name": quote["name"],
            "price": quote["current"],
            "change_pct": quote["current_change_pct"],
            "open": quote["open_price"],
            "previous_close": quote["previous_close"],
            "amount_yi": quote["amount_yi"],
            "source": "Tencent",
        }
        for quote in parsed.values()
    }


def _fetch_eastmoney_quotes(symbols: list[dict]) -> dict[str, dict[str, Any]]:
    out = {}
    for item in symbols:
        ticker = item["ticker"].upper()
        code = ticker.split(".")[0]
        secid = ("1." if ticker.endswith(".SS") or code.startswith(("6", "9")) else "0.") + code
        data = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2,
                "invt": 2,
                "secid": secid,
                "fields": "f43,f46,f48,f57,f58,f60,f168,f169,f170,f171",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data.raise_for_status()
        obj = data.json().get("data") or {}
        if obj.get("f43") in (None, "-"):
            continue
        out[ticker] = {
            "name": obj.get("f58") or item.get("name") or ticker,
            "price": _to_float(obj.get("f43")),
            "change_pct": _to_float(obj.get("f170")),
            "open": _to_float(obj.get("f46")),
            "previous_close": _to_float(obj.get("f60")),
            "amount_yi": round((_to_float(obj.get("f48")) or 0) / 100_000_000, 3),
            "source": "Eastmoney",
        }
    return out


def _fetch_sina_quotes(symbols: list[dict]) -> dict[str, dict[str, Any]]:
    sina_symbols = [_ticker_to_sina_symbol(item["ticker"]) for item in symbols]
    response = requests.get(
        "https://hq.sinajs.cn/list=" + ",".join(sina_symbols),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
        timeout=8,
    )
    response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    out = {}
    for match in re.finditer(r"var hq_str_([^=]+)=\"([^\"]*)\";", text):
        symbol, body = match.groups()
        values = body.split(",")
        if len(values) < 10 or not values[0]:
            continue
        ticker = _sina_symbol_to_ticker(symbol)
        previous = _to_float(values[2])
        current = _to_float(values[3])
        out[ticker] = {
            "name": values[0],
            "price": current,
            "change_pct": round((current / previous - 1) * 100, 3) if previous else None,
            "open": _to_float(values[1]),
            "previous_close": previous,
            "amount_yi": round((_to_float(values[9]) or 0) / 100_000_000, 3),
            "source": "Sina",
        }
    return out


def _safe(fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _summary(status: str, hard: list[dict], medium: list[dict], issues: list[dict]) -> str:
    if status == "ready":
        return "核心行情源交叉校验通过，当前结论可作为研究输入。"
    if hard:
        return f"发现 {len(hard)} 个高优先级数据问题，相关结论必须降级或重跑。"
    return f"发现 {len(medium) or len(issues)} 个数据质量提醒，结论可读但需要标注置信度。"


def _ticker_to_tencent_symbol(ticker: str) -> str:
    code = ticker.split(".")[0]
    if ticker.endswith(".SS") or code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def _ticker_to_sina_symbol(ticker: str) -> str:
    code = ticker.split(".")[0]
    if ticker.endswith(".SS") or code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


def _sina_symbol_to_ticker(symbol: str) -> str:
    code = symbol[2:]
    suffix = ".SS" if symbol.startswith("sh") else ".SZ"
    return code + suffix


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
