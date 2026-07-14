from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Any

import requests

from .config import STOCK_UNIVERSE

REFERENCE_PROJECTS = [
    {
        "name": "daily_stock_analysis strategies",
        "url": "https://github.com/ZhuLinsen/daily_stock_analysis",
        "note": "参考其龙头、热点题材、情绪周期、放量突破、缩量回踩、预期重估等自然语言策略。",
    },
    {
        "name": "a-stock-data",
        "url": "https://github.com/simonlin1212/a-stock-data",
        "note": "数据源理念：腾讯/新浪/通达信优先，AkShare 不作为唯一行情底座。",
    },
]


DEFAULT_WEIGHTS = {
    "emotion": 1.10,
    "sector": 1.15,
    "relative_strength": 1.00,
    "capital": 0.95,
    "event": 0.80,
    "industry_chain": 0.85,
    "technical": 0.90,
    "quality": 0.65,
}

EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
TRACKED_TICKERS = {str(row["ticker"]).upper() for row in STOCK_UNIVERSE}
EASTMONEY_LIST_PARAMS = {
    "pn": 1,
    "pz": 500,
    "po": 1,
    "np": 1,
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": 2,
    "invt": 2,
    "fid": "f6",
    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
    "fields": "f2,f3,f6,f7,f8,f9,f10,f12,f14,f20,f21,f23,f62,f100",
}


SEED_UNIVERSE = [
    {"ticker": "300496.SZ", "name": "中科创达", "sector": "AI终端", "theme": "端侧AI/智能汽车", "chain": "compute", "quality": 62},
    {"ticker": "603078.SS", "name": "江化微", "sector": "半导体材料", "theme": "湿电子化学品", "chain": "manufacturing", "quality": 58},
    {"ticker": "300811.SZ", "name": "铂科新材", "sector": "电力与散热", "theme": "AI电源/磁性材料", "chain": "power_cooling", "quality": 60},
    {"ticker": "003022.SZ", "name": "联泓新科", "sector": "新材料", "theme": "光伏材料/周期修复", "chain": "materials", "quality": 54},
    {"ticker": "000938.SZ", "name": "紫光股份", "sector": "算力网络", "theme": "服务器/交换机", "chain": "servers", "quality": 63},
    {"ticker": "300502.SZ", "name": "新易盛", "sector": "光通信", "theme": "高速光模块", "chain": "networking", "quality": 68},
    {"ticker": "300308.SZ", "name": "中际旭创", "sector": "光通信", "theme": "800G/1.6T光模块", "chain": "networking", "quality": 72},
    {"ticker": "300476.SZ", "name": "胜宏科技", "sector": "PCB", "theme": "AI服务器PCB", "chain": "networking", "quality": 66},
    {"ticker": "688256.SS", "name": "寒武纪", "sector": "算力芯片", "theme": "国产AI芯片", "chain": "compute", "quality": 57},
    {"ticker": "002371.SZ", "name": "北方华创", "sector": "半导体设备", "theme": "国产设备平台", "chain": "manufacturing", "quality": 76},
    {"ticker": "688012.SS", "name": "中微公司", "sector": "半导体设备", "theme": "刻蚀设备", "chain": "manufacturing", "quality": 74},
    {"ticker": "688072.SS", "name": "拓荆科技", "sector": "半导体设备", "theme": "薄膜沉积", "chain": "manufacturing", "quality": 70},
    {"ticker": "688019.SS", "name": "安集科技", "sector": "半导体材料", "theme": "CMP抛光液", "chain": "manufacturing", "quality": 72},
    {"ticker": "300054.SZ", "name": "鼎龙股份", "sector": "半导体材料", "theme": "CMP/显示材料", "chain": "manufacturing", "quality": 64},
    {"ticker": "002409.SZ", "name": "雅克科技", "sector": "半导体材料", "theme": "前驱体/电子特气", "chain": "manufacturing", "quality": 68},
    {"ticker": "603690.SS", "name": "至纯科技", "sector": "半导体设备", "theme": "清洗/高纯系统", "chain": "manufacturing", "quality": 59},
    {"ticker": "000977.SZ", "name": "浪潮信息", "sector": "AI服务器", "theme": "服务器整机", "chain": "servers", "quality": 62},
    {"ticker": "000063.SZ", "name": "中兴通讯", "sector": "算力网络", "theme": "通信设备/服务器", "chain": "servers", "quality": 67},
    {"ticker": "301165.SZ", "name": "锐捷网络", "sector": "算力网络", "theme": "交换机", "chain": "networking", "quality": 61},
    {"ticker": "300394.SZ", "name": "天孚通信", "sector": "光通信", "theme": "光器件", "chain": "networking", "quality": 70},
    {"ticker": "002463.SZ", "name": "沪电股份", "sector": "PCB", "theme": "AI服务器PCB", "chain": "networking", "quality": 69},
    {"ticker": "605117.SS", "name": "德业股份", "sector": "电力设备", "theme": "逆变器/储能", "chain": "power_cooling", "quality": 61},
    {"ticker": "300274.SZ", "name": "阳光电源", "sector": "电力设备", "theme": "逆变器/储能", "chain": "power_cooling", "quality": 70},
    {"ticker": "002028.SZ", "name": "思源电气", "sector": "电力设备", "theme": "变压器/电网设备", "chain": "power_cooling", "quality": 67},
    {"ticker": "300124.SZ", "name": "汇川技术", "sector": "机器人", "theme": "工业自动化", "chain": "automation", "quality": 74},
    {"ticker": "002050.SZ", "name": "三花智控", "sector": "机器人/热管理", "theme": "热管理/机器人", "chain": "power_cooling", "quality": 72},
    {"ticker": "300750.SZ", "name": "宁德时代", "sector": "新能源", "theme": "电池/储能", "chain": "power_cooling", "quality": 78},
    {"ticker": "002594.SZ", "name": "比亚迪", "sector": "新能源汽车", "theme": "整车/电池", "chain": "demand", "quality": 73},
]


@dataclass(frozen=True)
class Quote:
    ticker: str
    name: str
    price: float | None
    change_pct: float | None
    turnover_pct: float | None
    amount_yi: float | None
    volume_ratio: float | None
    amplitude_pct: float | None
    source: str
    error: str | None = None


def discover_market_universe(limit: int = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a market-wide liquid universe without boosting the user's watchlist."""
    try:
        diff = ((_fetch_market_scan_payload().get("data") or {}).get("diff") or [])
        selected = _select_dynamic_universe(diff, limit)
        if not selected:
            raise ValueError("market snapshot has no completed-session liquidity data")
        overlap = sum(1 for row in selected if row["ticker"] in TRACKED_TICKERS)
        return selected, {
            "universe_source": "Eastmoney A-share market-wide liquidity scan",
            "universe_size": len(selected),
            "market_rows_scanned": len(diff),
            "tracked_overlap": overlap,
            "pool_priority": "none",
            "status": "ready",
        }
    except Exception as exc:
        fallback = [dict(row, universe_origin="independent_theme_fallback") for row in SEED_UNIVERSE[5:]]
        return fallback, {
            "universe_source": "independent thematic fallback",
            "universe_size": len(fallback),
            "market_rows_scanned": 0,
            "tracked_overlap": 0,
            "pool_priority": "none",
            "status": "degraded",
            "error": str(exc),
        }


def _fetch_market_scan_payload() -> dict[str, Any]:
    kwargs = {
        "params": EASTMONEY_LIST_PARAMS,
        "headers": {"User-Agent": "Mozilla/5.0"},
        "timeout": 15,
    }
    try:
        response = requests.get(EASTMONEY_LIST_URL, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ProxyError:
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(EASTMONEY_LIST_URL, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            curl_cmd = [
                "curl",
                "-L",
                "--max-time",
                str(kwargs["timeout"]),
                "-A",
                kwargs["headers"]["User-Agent"],
                EASTMONEY_LIST_URL,
                "--get",
            ]
            for key, value in EASTMONEY_LIST_PARAMS.items():
                curl_cmd.extend(["--data-urlencode", f"{key}={value}"])
            result = subprocess.run(
                curl_cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(result.stdout)


def _select_dynamic_universe(diff: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    eligible = []
    for row in diff:
        code = str(row.get("f12") or "")
        name = str(row.get("f14") or "")
        amount = _to_float(row.get("f6"))
        if not code or not name or amount is None or amount < 100_000_000:
            continue
        if "ST" in name.upper() or "退" in name or code.startswith(("4", "8")):
            continue
        ticker = f"{code}.SS" if code.startswith(("6", "9")) else f"{code}.SZ"
        sector = str(row.get("f100") or "未分类")
        change = _to_float(row.get("f3"))
        turnover = _to_float(row.get("f8"))
        volume_ratio = _to_float(row.get("f10"))
        market_cap = _to_float(row.get("f20"))
        item = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "theme": f"全市场成交活跃 / {sector}",
            "chain": _chain_from_sector(sector),
            "quality": _market_quality_score(row),
            "universe_origin": "market_wide_scan",
            "_quote": Quote(
                ticker=ticker,
                name=name,
                price=_to_float(row.get("f2")),
                change_pct=change,
                turnover_pct=turnover,
                amount_yi=round(amount / 100_000_000, 3),
                volume_ratio=volume_ratio,
                amplitude_pct=_to_float(row.get("f7")),
                source="Eastmoney market-wide snapshot",
            ),
            "_main_inflow": _to_float(row.get("f62")) or 0,
            "_market_cap": market_cap or 0,
        }
        eligible.append(item)

    by_amount = sorted(eligible, key=lambda row: row["_quote"].amount_yi or 0, reverse=True)
    by_strength = sorted(
        [row for row in eligible if 0.5 <= (row["_quote"].change_pct or -99) <= 8.5],
        key=lambda row: ((row["_quote"].change_pct or 0), (row["_quote"].amount_yi or 0)),
        reverse=True,
    )
    by_inflow = sorted(eligible, key=lambda row: row["_main_inflow"], reverse=True)
    selected: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    seen: set[str] = set()
    for row in by_amount[:100] + by_strength[:60] + by_inflow[:50]:
        if row["ticker"] in seen or sector_counts.get(row["sector"], 0) >= 10:
            continue
        seen.add(row["ticker"])
        sector_counts[row["sector"]] = sector_counts.get(row["sector"], 0) + 1
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def _market_quality_score(row: dict[str, Any]) -> float:
    market_cap = _to_float(row.get("f20")) or 0
    pe = _to_float(row.get("f9"))
    score = 52 + (8 if market_cap >= 100_000_000_000 else 4 if market_cap >= 30_000_000_000 else 0)
    if pe is not None and 0 < pe <= 50:
        score += 5
    elif pe is not None and (pe <= 0 or pe > 150):
        score -= 4
    return _clamp(score)


def _chain_from_sector(sector: str) -> str:
    rules = [
        (("软件", "IT服务", "计算机"), "software_apps"),
        (("半导体", "电子化学品"), "manufacturing"),
        (("通信", "光学", "元件"), "networking"),
        (("电力", "电网", "电源", "自动化设备"), "power_cooling"),
        (("消费电子", "汽车零部件"), "demand"),
    ]
    for names, chain in rules:
        if any(name in sector for name in names):
            return chain
    return "market"


def build_daily_candidates(
    conn,
    trade_date: str | None = None,
    limit: int = 20,
    universe: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trade_date = trade_date or date.today().isoformat()
    ensure_candidate_seed_weights(conn)
    discovery = {"universe_source": "caller supplied", "universe_size": len(universe or []), "pool_priority": "none", "status": "ready"}
    if universe is None:
        universe, discovery = discover_market_universe()
    weights = load_strategy_weights(conn)
    quotes = [item.get("_quote") or _fetch_tencent_quote(item) for item in universe]
    market = _market_phase(quotes)
    market.update(discovery)
    rows = [
        _score_candidate(item, quote, market, weights)
        for item, quote in zip(universe, quotes, strict=True)
    ]
    rows = sorted(rows, key=lambda row: row["score"], reverse=True)[:limit]
    persist_daily_candidates(conn, trade_date, rows, market, weights)
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "weights": weights,
        "rows": rows,
        "references": REFERENCE_PROJECTS,
        "universe": discovery,
    }


def latest_daily_candidates(conn, trade_date: str | None = None) -> dict[str, Any]:
    ensure_candidate_seed_weights(conn)
    if trade_date is None:
        row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM daily_candidates").fetchone()
        trade_date = row["trade_date"] if row and row["trade_date"] else None
    if not trade_date:
        return build_daily_candidates(conn, date.today().isoformat())
    rows = [
        _json_candidate_row(dict(row))
        for row in conn.execute(
            """
            SELECT * FROM daily_candidates
            WHERE trade_date=?
            ORDER BY score DESC, ticker
            """,
            (trade_date,),
        )
    ]
    market = {}
    if rows:
        market = rows[0].get("market_snapshot") or {}
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "weights": load_strategy_weights(conn),
        "rows": rows,
        "references": REFERENCE_PROJECTS,
        "universe": {
            "universe_source": market.get("universe_source", "unknown"),
            "universe_size": market.get("universe_size", len(rows)),
            "market_rows_scanned": market.get("market_rows_scanned", 0),
            "tracked_overlap": market.get("tracked_overlap", 0),
            "pool_priority": market.get("pool_priority", "none"),
            "status": market.get("status", "unknown"),
        },
    }


def ensure_candidate_seed_weights(conn) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for name, weight in DEFAULT_WEIGHTS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO candidate_strategy_weights (
                strategy, weight, sample_size, hit_rate_5d, avg_return_5d, updated_at
            ) VALUES (?, ?, 0, NULL, NULL, ?)
            """,
            (name, weight, now),
        )
    conn.commit()


def load_strategy_weights(conn) -> dict[str, float]:
    rows = conn.execute("SELECT strategy, weight FROM candidate_strategy_weights").fetchall()
    weights = {str(row["strategy"]): float(row["weight"]) for row in rows}
    return {**DEFAULT_WEIGHTS, **weights}


def persist_daily_candidates(
    conn,
    trade_date: str,
    rows: list[dict[str, Any]],
    market: dict[str, Any],
    weights: dict[str, float],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM daily_candidates WHERE trade_date=?", (trade_date,))
    for rank, row in enumerate(rows, 1):
        conn.execute(
            """
            INSERT INTO daily_candidates (
                trade_date, rank, ticker, name, sector, theme, market_cap_yi,
                score, bucket, market_phase, strategy_scores,
                risk_flags, reasons, quote_snapshot, market_snapshot, strategy_weights,
                source_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, ticker) DO UPDATE SET
                rank=excluded.rank,
                sector=excluded.sector,
                theme=excluded.theme,
                market_cap_yi=excluded.market_cap_yi,
                score=excluded.score,
                bucket=excluded.bucket,
                market_phase=excluded.market_phase,
                strategy_scores=excluded.strategy_scores,
                risk_flags=excluded.risk_flags,
                reasons=excluded.reasons,
                quote_snapshot=excluded.quote_snapshot,
                market_snapshot=excluded.market_snapshot,
                strategy_weights=excluded.strategy_weights,
                source_status=excluded.source_status,
                created_at=excluded.created_at
            """,
            (
                trade_date,
                rank,
                row["ticker"],
                row["name"],
                row.get("sector"),
                row.get("theme"),
                row.get("market_cap_yi"),
                row["score"],
                row["bucket"],
                market.get("phase", "unknown"),
                json.dumps(row["strategy_scores"], ensure_ascii=False),
                json.dumps(row["risk_flags"], ensure_ascii=False),
                json.dumps(row["reasons"], ensure_ascii=False),
                json.dumps(row["quote"], ensure_ascii=False),
                json.dumps(market, ensure_ascii=False),
                json.dumps(weights, ensure_ascii=False),
                json.dumps(row["source_status"], ensure_ascii=False),
                now,
            ),
        )
    conn.commit()


def update_candidate_strategy_weights(conn, horizon: int = 5) -> dict[str, Any]:
    """Simple self-iteration placeholder: update strategy weights from ready outcomes.

    The first implementation is intentionally conservative. It only adjusts
    weights when candidate_outcomes have enough observations, so bad data does
    not overfit the strategy layer.
    """
    rows = conn.execute(
        """
        SELECT dc.strategy_scores, co.return_pct
        FROM daily_candidates dc
        JOIN candidate_outcomes co
          ON dc.trade_date=co.trade_date AND dc.ticker=co.ticker
        WHERE co.horizon=? AND co.status='ready'
        """,
        (horizon,),
    ).fetchall()
    if len(rows) < 10:
        return {"status": "insufficient_samples", "sample_size": len(rows)}
    per_strategy: dict[str, list[float]] = {name: [] for name in DEFAULT_WEIGHTS}
    for row in rows:
        scores = json.loads(row["strategy_scores"] or "{}")
        ret = float(row["return_pct"] or 0)
        for name, score in scores.items():
            if float(score or 0) > 60:
                per_strategy.setdefault(name, []).append(ret)

    now = datetime.now().isoformat(timespec="seconds")
    updated = []
    for name, returns in per_strategy.items():
        if len(returns) < 5:
            continue
        avg_ret = mean(returns)
        hit_rate = sum(1 for value in returns if value > 0) / len(returns)
        old = load_strategy_weights(conn).get(name, DEFAULT_WEIGHTS.get(name, 1.0))
        delta = max(-0.08, min(0.08, (hit_rate - 0.5) * 0.20 + avg_ret * 0.60))
        new_weight = round(max(0.55, min(1.55, old + delta)), 3)
        conn.execute(
            """
            UPDATE candidate_strategy_weights
            SET weight=?, sample_size=?, hit_rate_5d=?, avg_return_5d=?, updated_at=?
            WHERE strategy=?
            """,
            (new_weight, len(returns), hit_rate, avg_ret, now, name),
        )
        updated.append({"strategy": name, "old": old, "new": new_weight, "sample_size": len(returns)})
    conn.commit()
    return {"status": "updated", "sample_size": len(rows), "updated": updated}


def _fetch_tencent_quote(item: dict[str, Any]) -> Quote:
    ticker = str(item["ticker"]).upper()
    code = ticker.split(".")[0]
    prefix = "sh" if ticker.endswith(".SS") or code.startswith(("6", "9")) else "bj" if code.startswith(("4", "8")) else "sz"
    try:
        resp = requests.get(
            f"https://qt.gtimg.cn/q={prefix}{code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.content.decode("gbk", errors="ignore")
        vals = raw.split('"')[1].split("~")
        return Quote(
            ticker=ticker,
            name=vals[1] or item["name"],
            price=_to_float(vals[3]),
            change_pct=_to_float(vals[32]),
            turnover_pct=_to_float(vals[38]),
            amount_yi=(_to_float(vals[37]) or 0) / 10000,
            volume_ratio=_to_float(vals[49]),
            amplitude_pct=_to_float(vals[43]),
            source="Tencent quote",
        )
    except Exception as exc:
        return Quote(
            ticker=ticker,
            name=item["name"],
            price=None,
            change_pct=None,
            turnover_pct=None,
            amount_yi=None,
            volume_ratio=None,
            amplitude_pct=None,
            source="fallback",
            error=str(exc),
        )


def _market_phase(quotes: list[Quote]) -> dict[str, Any]:
    ready = [quote for quote in quotes if quote.change_pct is not None]
    if not ready:
        return {
            "phase": "data_degraded",
            "description": "行情源不可用，候选仅按产业链和静态策略排序。",
            "advance_ratio": None,
            "hot_ratio": None,
            "avg_change_pct": None,
            "data_ready": 0,
        }
    advance_ratio = sum(1 for quote in ready if (quote.change_pct or 0) > 0) / len(ready)
    hot_ratio = sum(1 for quote in ready if (quote.change_pct or 0) >= 5) / len(ready)
    avg_change = mean([quote.change_pct or 0 for quote in ready])
    high_turnover_ratio = sum(1 for quote in ready if (quote.turnover_pct or 0) >= 5) / len(ready)
    if hot_ratio >= 0.18 and advance_ratio >= 0.55:
        phase = "sector_hot"
        desc = "题材/抱团偏强，优先龙头、板块共振和相对强势。"
    elif avg_change <= -1.5 or advance_ratio <= 0.35:
        phase = "risk_off"
        desc = "市场偏弱，降低追涨权重，优先风险过滤和低位预期差。"
    elif high_turnover_ratio >= 0.25:
        phase = "emotion_heating"
        desc = "换手升温，关注情绪启动但避免高位过热。"
    else:
        phase = "mixed"
        desc = "结构性行情，按板块强度和个股位置筛选。"
    return {
        "phase": phase,
        "description": desc,
        "advance_ratio": round(advance_ratio, 3),
        "hot_ratio": round(hot_ratio, 3),
        "avg_change_pct": round(avg_change, 2),
        "high_turnover_ratio": round(high_turnover_ratio, 3),
        "data_ready": len(ready),
    }


def _score_candidate(
    item: dict[str, Any],
    quote: Quote,
    market: dict[str, Any],
    weights: dict[str, float],
) -> dict[str, Any]:
    strategy_scores = _strategy_scores(item, quote, market)
    risk_flags = _risk_flags(item, quote, market)
    weighted = 0.0
    max_weighted = 0.0
    for name, score in strategy_scores.items():
        weight = weights.get(name, DEFAULT_WEIGHTS.get(name, 1.0))
        weighted += score * weight
        max_weighted += 100 * weight
    base_score = weighted / max_weighted * 100 if max_weighted else 0
    penalty = sum(flag["penalty"] for flag in risk_flags)
    score = round(max(0, min(100, base_score - penalty)), 2)
    return {
        "ticker": item["ticker"],
        "name": quote.name or item["name"],
        "sector": item.get("sector", ""),
        "theme": item.get("theme", ""),
        "market_cap_yi": round(float(item.get("_market_cap") or 0) / 100_000_000, 2) if item.get("_market_cap") else None,
        "score": score,
        "bucket": _bucket(score, risk_flags),
        "strategy_scores": strategy_scores,
        "risk_flags": risk_flags,
        "reasons": _reasons(item, quote, market, strategy_scores),
        "quote": quote.__dict__,
        "source_status": {
            "quote": "ready" if quote.error is None else "degraded",
            "quote_source": quote.source,
            "error": quote.error,
        },
    }


def _strategy_scores(item: dict[str, Any], quote: Quote, market: dict[str, Any]) -> dict[str, float]:
    change = quote.change_pct
    turnover = quote.turnover_pct
    amount = quote.amount_yi
    vol_ratio = quote.volume_ratio
    quality = float(item.get("quality", 55))
    phase = market.get("phase")
    avg = market.get("avg_change_pct") or 0
    hot_ratio = market.get("hot_ratio") or 0
    advance_ratio = market.get("advance_ratio") or 0

    emotion = 48
    if phase == "sector_hot":
        emotion += 8
    elif phase == "emotion_heating":
        emotion += 5
    elif phase == "risk_off":
        emotion -= 6
    if change is not None:
        if 2 <= change <= 5.8:
            emotion += 10
        elif 0.5 <= change < 2:
            emotion += 5
        elif change >= 7.5:
            emotion -= 6
    if turnover is not None and 2 <= turnover <= 10:
        emotion += 6
    elif turnover is not None and turnover > 15:
        emotion -= 10

    sector = 50 + _theme_bonus(item) * 0.55
    if phase in {"sector_hot", "emotion_heating"} and hot_ratio >= 0.12:
        sector += 5
    elif phase == "risk_off":
        sector -= 4

    relative = 48
    if change is not None:
        relative += max(-18, min(18, (change - avg) * 3.2))
        if 1 <= change <= 6:
            relative += 6
        elif change >= 8:
            relative -= 8
    if advance_ratio < 0.4 and change is not None and change > 0:
        relative += 4

    capital = 46
    if amount is not None:
        capital += 12 if amount >= 35 else 8 if amount >= 15 else 4 if amount >= 6 else -4
    if vol_ratio is not None:
        capital += 8 if 1.2 <= vol_ratio <= 3.5 else 4 if 0.9 <= vol_ratio < 1.2 else -6 if vol_ratio > 5 else -3 if vol_ratio < 0.6 else 0
    if turnover is not None:
        capital += 6 if 2 <= turnover <= 8 else 2 if 0.8 <= turnover < 2 else -6 if turnover > 15 else 0

    event = 48 + (6 if item.get("chain") in {"compute", "networking", "power_cooling", "manufacturing", "servers"} else 2)
    industry_chain = 50 + _theme_bonus(item) * 0.45 + (6 if item.get("chain") in {"compute", "networking", "power_cooling"} else 2)
    technical = 46
    if change is not None:
        technical += 12 if 1 <= change <= 4.8 else 7 if 0 < change < 1 else 4 if 4.8 < change <= 6.8 else -8 if change >= 8.5 else -6 if change < -3 else 0
    if vol_ratio is not None:
        technical += 6 if 1.1 <= vol_ratio <= 2.8 else -4 if vol_ratio > 5 else 0
    if turnover is not None:
        technical += 5 if 1.5 <= turnover <= 8 else -6 if turnover > 16 else 0
    return {
        "emotion": _clamp(emotion),
        "sector": _clamp(sector),
        "relative_strength": _clamp(relative),
        "capital": _clamp(capital),
        "event": _clamp(event),
        "industry_chain": _clamp(industry_chain),
        "technical": _clamp(technical),
        "quality": _clamp(quality),
    }


def _risk_flags(item: dict[str, Any], quote: Quote, market: dict[str, Any]) -> list[dict[str, Any]]:
    flags = []
    if quote.error:
        flags.append({"code": "quote_degraded", "label": "行情源降级", "penalty": 8})
    if quote.change_pct is not None and quote.change_pct >= 9.5:
        flags.append({"code": "limit_chase_risk", "label": "接近涨停，追高/买不到风险", "penalty": 12})
    if quote.turnover_pct is not None and quote.turnover_pct >= 18:
        flags.append({"code": "overheated_turnover", "label": "换手过热，分歧放大", "penalty": 8})
    if quote.volume_ratio is not None and quote.volume_ratio >= 5 and quote.change_pct is not None and quote.change_pct < 1:
        flags.append({"code": "volume_no_price", "label": "放量不涨，疑似派发", "penalty": 10})
    if market.get("phase") == "risk_off" and quote.change_pct is not None and quote.change_pct > 5:
        flags.append({"code": "weak_market_chase", "label": "弱市高涨幅，次日兑现风险", "penalty": 8})
    if quote.change_pct is not None and quote.turnover_pct is not None and quote.change_pct >= 7 and quote.turnover_pct >= 10:
        flags.append({"code": "late_acceleration", "label": "高位加速，追涨盈亏比差", "penalty": 8})
    if quote.amplitude_pct is not None and quote.change_pct is not None and quote.amplitude_pct >= 9 and quote.change_pct <= 2:
        flags.append({"code": "intraday_reversal", "label": "振幅大但收涨弱，承接待确认", "penalty": 7})
    if quote.amount_yi is not None and quote.change_pct is not None and quote.amount_yi >= 20 and quote.change_pct <= 0.5:
        flags.append({"code": "heavy_no_trend", "label": "大成交未形成趋势，可能只是换手", "penalty": 6})
    return flags


def _reasons(
    item: dict[str, Any],
    quote: Quote,
    market: dict[str, Any],
    scores: dict[str, float],
) -> list[str]:
    reasons = [f"{item.get('sector')} · {item.get('theme')}"]
    if item.get("universe_origin") == "market_wide_scan":
        reasons.append("来自全市场流动性扫描，不受现有选股池排序影响")
    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    for name, score in top:
        if score >= 62:
            reasons.append(f"{_strategy_label(name)}强：{score:.0f}")
    if quote.change_pct is not None:
        reasons.append(f"涨跌幅 {quote.change_pct:+.2f}% / 成交额 {quote.amount_yi or 0:.1f} 亿")
    reasons.append(market.get("description", ""))
    return [reason for reason in reasons if reason]


def _theme_bonus(item: dict[str, Any]) -> float:
    text = f"{item.get('sector', '')}{item.get('theme', '')}{item.get('chain', '')}"
    hot_terms = ["AI", "算力", "光通信", "半导体", "电力", "散热", "服务器", "机器人", "PCB"]
    return min(12, sum(2 for term in hot_terms if term in text))


def _bucket(score: float, risk_flags: list[dict[str, Any]]) -> str:
    if any(flag["code"] in {"limit_chase_risk", "volume_no_price", "late_acceleration"} for flag in risk_flags):
        return "风险观察"
    if score >= 74:
        return "重点候选"
    if score >= 64:
        return "观察候选"
    return "线索候选"


def _strategy_label(name: str) -> str:
    return {
        "emotion": "情绪/抱团",
        "sector": "板块",
        "relative_strength": "相对强度",
        "capital": "资金行为",
        "event": "事件预期",
        "industry_chain": "产业链",
        "technical": "技术结构",
        "quality": "基本面质量",
    }.get(name, name)


def _json_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("strategy_scores", "risk_flags", "reasons", "quote_snapshot", "market_snapshot", "strategy_weights", "source_status"):
        value = row.get(key)
        if isinstance(value, str):
            row[key] = json.loads(value) if value else None
    row["quote"] = row.pop("quote_snapshot", None)
    return row


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 2)
