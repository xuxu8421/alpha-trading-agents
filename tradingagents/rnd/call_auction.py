from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from statistics import mean
from typing import Any

import requests


REFERENCES = [
    {
        "name": "上交所交易规则 2026",
        "url": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml",
        "use": "确认开盘集合竞价时段、连续竞价时段和收盘集合竞价时段。",
    },
    {
        "name": "CSRC 投教：二级市场交易机制",
        "url": "https://www.csrc.gov.cn/csrc/c100211/c6288926/6288926/files/f2a0e5fdf2db4e00afb4c6ee60a245d8.pdf",
        "use": "确认集合竞价成交价按可实现最大成交量等原则确定。",
    },
    {
        "name": "eltdx",
        "url": "https://github.com/electkismet/eltdx",
        "use": "后续可作为竞价明细、09:25 竞价成交快照和通达信协议研究入口。",
    },
    {
        "name": "TDXPystock",
        "url": "https://github.com/newhackerman/TDXPystock",
        "use": "参考其 9:25 后导出竞价数据、板块异动和早盘选股的流程。",
    },
    {
        "name": "AXOrderBook",
        "url": "https://github.com/fpga2u/AXOrderBook",
        "use": "理解 L2 逐笔委托、成交和集合竞价阶段订单簿重建的高阶方向。",
    },
]


TIME_WINDOWS = [
    {
        "time": "09:15-09:20",
        "label": "可申报可撤单",
        "meaning": "这个阶段最容易出现试盘和撤单，看到的大单不直接当真，只记录方向和撤单率。",
        "watch": ["虚高涨幅", "大单快速消失", "竞价额是否持续放大"],
    },
    {
        "time": "09:20-09:25",
        "label": "可申报不可撤单",
        "meaning": "观察价值最高，价格和量能继续强化才说明资金承接更真实。",
        "watch": ["竞价涨幅稳定", "未匹配买量", "板块内多股同步"],
    },
    {
        "time": "09:25",
        "label": "开盘价撮合",
        "meaning": "最终开盘价和成交量落地，重点看竞价成交额/昨日成交额、开盘缺口和板块队形。",
        "watch": ["开盘涨幅", "竞价成交额", "一字板/高开回落风险"],
    },
    {
        "time": "09:25-09:30",
        "label": "静默观察",
        "meaning": "委托可以继续进来但不撮合，用来准备交易计划，不把这 5 分钟当已成交信号。",
        "watch": ["是否排队买不到", "是否需要等 09:30 后确认", "撤单和改价风险"],
    },
]


DEFAULT_RULE_WEIGHTS = {
    "market_gap": 1.10,
    "market_follow": 1.00,
    "pool_breadth": 0.95,
    "pool_leadership": 0.85,
    "crowding_risk": 0.80,
}


INDEX_UNIVERSE = [
    {"name": "上证指数", "symbol": "sh000001"},
    {"name": "深证成指", "symbol": "sz399001"},
    {"name": "创业板指", "symbol": "sz399006"},
    {"name": "沪深300", "symbol": "sh000300"},
]


@dataclass(frozen=True)
class AuctionQuote:
    ticker: str
    name: str
    current: float | None
    previous_close: float | None
    open_price: float | None
    current_change_pct: float | None
    open_gap_pct: float | None
    from_open_pct: float | None
    amount_yi: float | None
    turnover_pct: float | None
    volume_ratio: float | None
    quote_time: str
    source: str
    error: str | None = None


def build_call_auction_brief(
    universe: list[dict],
    conn=None,
    trade_date: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    trade_date = trade_date or date.today().isoformat()
    if conn is not None:
        ensure_rule_weights(conn)
    weights = load_rule_weights(conn) if conn is not None else DEFAULT_RULE_WEIGHTS
    market_rows, stock_rows, source_status = _fetch_auction_proxy(universe)
    prediction = _predict_market_from_snapshots(market_rows, stock_rows, weights)
    stock_features = [_stock_feature(row) for row in stock_rows]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "title": "集合竞价观察",
        "summary": "每日 09:25 后用开盘价、开盘缺口、竞价后即时走势和股票池共振，给出当天大盘走势预测；收盘后用真实走势校准规则。",
        "data_note": "当前是 09:25 开盘价/实时行情代理口径，不等同于逐笔竞价明细；接入通达信或 L2 后会替换为真实竞价委托/成交数据。",
        "market": market_rows,
        "stocks": stock_features,
        "prediction": prediction,
        "weights": weights,
        "source_status": source_status,
        "outcome": latest_call_auction_outcome(conn, trade_date) if conn is not None else None,
        "time_windows": TIME_WINDOWS,
        "references": REFERENCES,
    }
    if conn is not None and persist:
        persist_call_auction_snapshot(conn, payload)
    return payload


def latest_call_auction_brief(conn, universe: list[dict], trade_date: str | None = None) -> dict[str, Any]:
    ensure_rule_weights(conn)
    if trade_date is None:
        if _should_refresh_today_auction():
            trade_date = date.today().isoformat()
        else:
            row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM call_auction_snapshots").fetchone()
            trade_date = row["trade_date"] if row and row["trade_date"] else None
    if not trade_date:
        return build_call_auction_brief(universe, conn)
    row = conn.execute(
        "SELECT * FROM call_auction_snapshots WHERE trade_date=?",
        (trade_date,),
    ).fetchone()
    if not row:
        return build_call_auction_brief(universe, conn, trade_date)
    payload = {
        "generated_at": row["generated_at"],
        "trade_date": row["trade_date"],
        "title": "集合竞价观察",
        "summary": "每日 09:25 后用开盘价、开盘缺口、竞价后即时走势和股票池共振，给出当天大盘走势预测；收盘后用真实走势校准规则。",
        "data_note": "当前是 09:25 开盘价/实时行情代理口径，不等同于逐笔竞价明细；接入通达信或 L2 后会替换为真实竞价委托/成交数据。",
        "market": json.loads(row["market_snapshot"]),
        "stocks": [_stock_feature(item) for item in json.loads(row["stock_snapshots"])],
        "prediction": json.loads(row["prediction"]),
        "weights": json.loads(row["rule_weights"]),
        "source_status": json.loads(row["source_status"]),
        "outcome": latest_call_auction_outcome(conn, trade_date),
        "time_windows": TIME_WINDOWS,
        "references": REFERENCES,
    }
    return payload


def _should_refresh_today_auction(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and now.time() >= time(9, 25)


def persist_call_auction_snapshot(conn, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO call_auction_snapshots (
            trade_date, generated_at, market_snapshot, stock_snapshots,
            prediction, rule_weights, source_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            generated_at=excluded.generated_at,
            market_snapshot=excluded.market_snapshot,
            stock_snapshots=excluded.stock_snapshots,
            prediction=excluded.prediction,
            rule_weights=excluded.rule_weights,
            source_status=excluded.source_status
        """,
        (
            payload["trade_date"],
            payload["generated_at"],
            json.dumps(payload["market"], ensure_ascii=False),
            json.dumps([_quote_dict(row) for row in payload["stocks"]], ensure_ascii=False),
            json.dumps(payload["prediction"], ensure_ascii=False),
            json.dumps(payload["weights"], ensure_ascii=False),
            json.dumps(payload["source_status"], ensure_ascii=False),
        ),
    )
    conn.commit()


def evaluate_call_auction_prediction(conn, universe: list[dict], trade_date: str | None = None) -> dict[str, Any]:
    trade_date = trade_date or date.today().isoformat()
    now_dt = datetime.now()
    if now_dt.hour < 15:
        return {"status": "pending_close", "trade_date": trade_date, "message": "15:00 后再校准集合竞价预测。"}
    snap = conn.execute(
        "SELECT * FROM call_auction_snapshots WHERE trade_date=?",
        (trade_date,),
    ).fetchone()
    if not snap:
        return {"status": "missing_prediction", "trade_date": trade_date}
    market_rows, _, source_status = _fetch_auction_proxy(universe)
    prediction = json.loads(snap["prediction"])
    outcome = _score_prediction(prediction, market_rows)
    now = now_dt.isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO call_auction_outcomes (
            trade_date, status, actual_snapshot, score, error_tags, diagnosis, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            status=excluded.status,
            actual_snapshot=excluded.actual_snapshot,
            score=excluded.score,
            error_tags=excluded.error_tags,
            diagnosis=excluded.diagnosis,
            checked_at=excluded.checked_at
        """,
        (
            trade_date,
            outcome["status"],
            json.dumps({"market": market_rows, "source_status": source_status}, ensure_ascii=False),
            outcome["score"],
            json.dumps(outcome["error_tags"], ensure_ascii=False),
            outcome["diagnosis"],
            now,
        ),
    )
    conn.commit()
    iteration = update_call_auction_rule_weights(conn)
    return {**outcome, "trade_date": trade_date, "iteration": iteration}


def latest_call_auction_outcome(conn, trade_date: str | None = None) -> dict[str, Any] | None:
    if conn is None:
        return None
    if trade_date is None:
        row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM call_auction_outcomes").fetchone()
        trade_date = row["trade_date"] if row and row["trade_date"] else None
    if not trade_date:
        return None
    row = conn.execute(
        "SELECT * FROM call_auction_outcomes WHERE trade_date=?",
        (trade_date,),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    for key in ("actual_snapshot", "error_tags"):
        out[key] = json.loads(out[key] or "{}")
    return out


def ensure_rule_weights(conn) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for name, weight in DEFAULT_RULE_WEIGHTS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO call_auction_rule_weights (
                rule, weight, sample_size, hit_rate, updated_at
            ) VALUES (?, ?, 0, NULL, ?)
            """,
            (name, weight, now),
        )
    conn.commit()


def load_rule_weights(conn) -> dict[str, float]:
    rows = conn.execute("SELECT rule, weight FROM call_auction_rule_weights").fetchall()
    weights = {str(row["rule"]): float(row["weight"]) for row in rows}
    return {**DEFAULT_RULE_WEIGHTS, **weights}


def update_call_auction_rule_weights(conn) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT cas.prediction, cao.score
        FROM call_auction_snapshots cas
        JOIN call_auction_outcomes cao ON cas.trade_date=cao.trade_date
        WHERE cao.status='ready'
        """
    ).fetchall()
    if len(rows) < 5:
        return {"status": "insufficient_samples", "sample_size": len(rows)}
    buckets: dict[str, list[float]] = {name: [] for name in DEFAULT_RULE_WEIGHTS}
    for row in rows:
        prediction = json.loads(row["prediction"] or "{}")
        contributions = prediction.get("rule_contributions", {})
        score = float(row["score"] or 0)
        for name, value in contributions.items():
            if abs(float(value or 0)) >= 6:
                buckets.setdefault(name, []).append(score)
    now = datetime.now().isoformat(timespec="seconds")
    updated = []
    current = load_rule_weights(conn)
    for name, scores in buckets.items():
        if len(scores) < 3:
            continue
        hit_rate = sum(1 for score in scores if score >= 65) / len(scores)
        delta = max(-0.06, min(0.06, (hit_rate - 0.55) * 0.16))
        new_weight = round(max(0.55, min(1.55, current.get(name, 1.0) + delta)), 3)
        conn.execute(
            """
            UPDATE call_auction_rule_weights
            SET weight=?, sample_size=?, hit_rate=?, updated_at=?
            WHERE rule=?
            """,
            (new_weight, len(scores), hit_rate, now, name),
        )
        updated.append({"rule": name, "weight": new_weight, "hit_rate": hit_rate, "sample_size": len(scores)})
    conn.commit()
    return {"status": "updated", "sample_size": len(rows), "updated": updated}


def _fetch_auction_proxy(universe: list[dict]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    index_symbols = [row["symbol"] for row in INDEX_UNIVERSE]
    stock_symbols = [_ticker_to_symbol(str(row.get("ticker", ""))) for row in universe if row.get("ticker")]
    symbols = index_symbols + stock_symbols
    try:
        raw = _request_tencent(symbols)
        parsed = _parse_tencent_quotes(raw)
        market = [parsed.get(symbol) for symbol in index_symbols if parsed.get(symbol)]
        stocks = []
        for item in universe:
            symbol = _ticker_to_symbol(str(item.get("ticker", "")))
            quote = parsed.get(symbol)
            if quote:
                quote["theme"] = item.get("theme", "")
                stocks.append(quote)
        status = {
            "status": "ready" if market and stocks else "partial",
            "source": "Tencent realtime quote, open-price proxy",
            "data_ready": len(market) + len(stocks),
            "note": "开盘价/实时行情代理集合竞价，不含逐笔委托和撤单率。",
        }
        return market, stocks, status
    except Exception as exc:
        return [], [], {
            "status": "failed",
            "source": "Tencent realtime quote, open-price proxy",
            "data_ready": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "note": "行情源失败，保留学习框架，不生成有效预测。",
        }


def _request_tencent(symbols: list[str]) -> str:
    response = requests.get(
        "https://qt.gtimg.cn/q=" + ",".join(symbols),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"},
        timeout=8,
    )
    response.raise_for_status()
    return response.content.decode("gbk", errors="ignore")


def _parse_tencent_quotes(raw: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        if not line or '="' not in line:
            continue
        symbol = line.split("=", 1)[0].replace("v_", "")
        values = line.split('"')[1].split("~")
        if len(values) < 38:
            continue
        current = _to_float(values[3])
        previous = _to_float(values[4])
        open_price = _to_float(values[5])
        amount_yi = (_to_float(values[37]) or 0) / 10000
        row = {
            "ticker": _symbol_to_ticker(symbol),
            "symbol": symbol,
            "name": values[1] or symbol,
            "current": current,
            "previous_close": previous,
            "open_price": open_price,
            "current_change_pct": _to_float(values[32]),
            "open_gap_pct": _pct(open_price, previous),
            "from_open_pct": _pct(current, open_price),
            "amount_yi": round(amount_yi, 2),
            "turnover_pct": _to_float(values[38]) if len(values) > 38 else None,
            "volume_ratio": _to_float(values[49]) if len(values) > 49 else None,
            "quote_time": values[30] if len(values) > 30 else "",
            "source": "Tencent realtime quote",
            "error": None,
        }
        rows[symbol] = row
    if not rows:
        raise ValueError("Tencent returned no parsable quotes")
    return rows


def _predict_market_from_snapshots(
    market_rows: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    weights = {**DEFAULT_RULE_WEIGHTS, **(weights or {})}
    if not market_rows:
        return {
            "stance": "数据不足",
            "direction": "unknown",
            "confidence": 0,
            "score": 0,
            "expected_path": "行情源不可用，不生成当日走势预测。",
            "reasons": ["集合竞价行情源降级"],
            "risk_flags": ["data_degraded"],
            "rule_contributions": {},
        }
    market_gap = mean([row.get("open_gap_pct") or 0 for row in market_rows])
    market_follow = mean([row.get("from_open_pct") or 0 for row in market_rows])
    stock_gaps = [row.get("open_gap_pct") or 0 for row in stock_rows if row.get("open_gap_pct") is not None]
    stock_changes = [row.get("current_change_pct") or 0 for row in stock_rows if row.get("current_change_pct") is not None]
    pool_breadth = (sum(1 for value in stock_gaps if value > 0) / len(stock_gaps)) if stock_gaps else 0.5
    leadership = (sum(1 for value in stock_changes if value >= 2.0) / len(stock_changes)) if stock_changes else 0
    crowding = (sum(1 for row in stock_rows if (row.get("open_gap_pct") or 0) >= 5.0) / len(stock_rows)) if stock_rows else 0
    contributions = {
        "market_gap": _clamp_signal(market_gap * 34) * weights["market_gap"],
        "market_follow": _clamp_signal(market_follow * 28) * weights["market_follow"],
        "pool_breadth": (pool_breadth - 0.5) * 34 * weights["pool_breadth"],
        "pool_leadership": leadership * 18 * weights["pool_leadership"],
        "crowding_risk": -crowding * 20 * weights["crowding_risk"],
    }
    score = round(50 + sum(contributions.values()), 2)
    score = max(0, min(100, score))
    if score >= 66:
        stance, direction, path = "偏强", "up", "竞价确认偏强，倾向震荡上行；若 10:00 前回落跌破开盘区间，需要降级为冲高回落。"
    elif score >= 56:
        stance, direction, path = "温和偏强", "up", "开盘结构略偏强，倾向先上探再分化；需要观察权重指数和题材中军是否同步。"
    elif score <= 38:
        stance, direction, path = "偏弱", "down", "竞价和开盘承接偏弱，倾向弱势震荡；优先控制仓位，等待修复信号。"
    elif score <= 46:
        stance, direction, path = "弱修复/震荡", "flat_down", "竞价没有形成有效共振，倾向低位震荡或弱修复。"
    else:
        stance, direction, path = "震荡", "flat", "竞价信号分歧，倾向结构性震荡；不把单一高开当作趋势确认。"
    reasons = [
        f"指数平均开盘缺口 {market_gap:+.2f}%",
        f"指数开盘后均值 {market_follow:+.2f}%",
        f"股票池竞价红盘比例 {pool_breadth:.0%}",
        f"强势股比例 {leadership:.0%}",
    ]
    risk_flags = []
    if crowding >= 0.25:
        risk_flags.append("股票池高开拥挤，追高兑现风险")
    if market_gap > 0.8 and market_follow < -0.25:
        risk_flags.append("指数高开回落，冲高回落风险")
    if market_gap < -0.5 and market_follow > 0.25:
        risk_flags.append("低开修复，注意只确认修复不确认反转")
    return {
        "stance": stance,
        "direction": direction,
        "confidence": round(min(88, max(35, abs(score - 50) * 1.45 + 42)), 1),
        "score": score,
        "expected_path": path,
        "reasons": reasons,
        "risk_flags": risk_flags,
        "rule_contributions": {key: round(value, 2) for key, value in contributions.items()},
    }


def _stock_feature(row: dict[str, Any]) -> dict[str, Any]:
    gap = row.get("open_gap_pct")
    follow = row.get("from_open_pct")
    change = row.get("current_change_pct")
    amount = row.get("amount_yi") or 0
    tags = []
    if gap is not None and gap >= 5:
        tags.append("高开强势")
    elif gap is not None and gap >= 2:
        tags.append("竞价偏强")
    elif gap is not None and gap <= -2:
        tags.append("竞价偏弱")
    if follow is not None and follow < -1:
        tags.append("开盘承接转弱")
    if follow is not None and follow > 1:
        tags.append("开盘继续走强")
    if amount >= 8:
        tags.append("成交活跃")
    if change is not None and change >= 9.5:
        tags.append("接近涨停")
    if not tags:
        tags.append("常规观察")
    return {**row, "features": tags, "decision_hint": _decision_hint(tags)}


def _decision_hint(tags: list[str]) -> str:
    if "接近涨停" in tags:
        return "强度高但可执行性差，避免盲目排板。"
    if "开盘承接转弱" in tags:
        return "高开后转弱，等 09:45 后确认再判断。"
    if "开盘继续走强" in tags and "成交活跃" in tags:
        return "可列为早盘重点观察，但仍需看板块共振。"
    return "作为观察信号，不单独构成交易结论。"


def _score_prediction(prediction: dict[str, Any], market_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not market_rows:
        return {
            "status": "pending",
            "score": None,
            "error_tags": ["data_degraded"],
            "diagnosis": "收盘行情不可用，暂不能校准。",
        }
    sh = next((row for row in market_rows if row.get("symbol") == "sh000001"), market_rows[0])
    actual_change = float(sh.get("current_change_pct") or 0)
    actual_from_open = float(sh.get("from_open_pct") or 0)
    direction = prediction.get("direction")
    if direction == "up":
        base = 82 if actual_change > 0 else 45 if actual_from_open > 0 else 25
    elif direction in {"flat", "flat_down"}:
        base = 82 if abs(actual_change) <= 0.5 else 58 if abs(actual_change) <= 1.2 else 35
    elif direction == "down":
        base = 82 if actual_change < 0 else 45 if actual_from_open < 0 else 25
    else:
        base = 50
    tags = []
    if base < 50:
        tags.append("direction_error")
    if direction == "up" and actual_from_open < -0.8:
        tags.append("auction_follow_through_error")
    if direction == "down" and actual_from_open > 0.8:
        tags.append("repair_missed")
    if not tags:
        tags.append("ok")
    return {
        "status": "ready",
        "score": float(base),
        "error_tags": tags,
        "diagnosis": f"预测 {prediction.get('stance', '')}，上证实际涨跌 {actual_change:+.2f}%，开盘后 {actual_from_open:+.2f}%。",
    }


def _ticker_to_symbol(ticker: str) -> str:
    code = ticker.split(".")[0]
    if ticker.endswith(".SS") or code.startswith(("6", "9")):
        return "sh" + code
    if ticker.endswith(".BJ") or code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def _symbol_to_ticker(symbol: str) -> str:
    code = symbol[2:]
    if symbol.startswith("sh"):
        return code + ".SS"
    if symbol.startswith("bj"):
        return code + ".BJ"
    return code + ".SZ"


def _pct(value: float | None, base: float | None) -> float | None:
    if value is None or base in (None, 0):
        return None
    return round((value / base - 1) * 100, 2)


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_signal(value: float) -> float:
    return max(-18, min(18, value))


def _quote_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"features", "decision_hint"}}
