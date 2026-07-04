from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from statistics import mean
from typing import Any

import requests


EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_CLIST_BASE_PARAMS = {
    "pn": 1,
    "pz": 520,
    "po": 1,
    "np": 1,
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": 2,
    "invt": 2,
    "fid": "f62",
    "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f20,f62,f66,f69,f72,f75,f78,f81,f84,f87,f104,f105,f128,f140,f141",
}

SOURCE_REGISTRY = [
    {
        "name": "东方财富行业板块资金流",
        "tier": "A",
        "url": "https://data.eastmoney.com/bkzj/hy.html",
        "use": "行业板块涨跌、成交额、主力净流入、上涨/下跌家数。",
    },
    {
        "name": "东方财富概念板块资金流",
        "tier": "A",
        "url": "https://data.eastmoney.com/bkzj/gn.html",
        "use": "概念题材强度、资金抱团、领涨股和拥挤度。",
    },
    {
        "name": "雪球/股吧/抖音叙事热度",
        "tier": "D",
        "url": "https://xueqiu.com/",
        "use": "后续接入，只作为叙事扩散和散户拥挤度，不作为事实证据。",
        "status": "planned",
    },
]


def build_market_pulse(conn, trade_date: str | None = None) -> dict[str, Any]:
    trade_date = trade_date or date.today().isoformat()
    industry = _fetch_board_rows("industry")
    concept = _fetch_board_rows("concept")
    universe = industry + concept
    history = _recent_phase_context(conn, trade_date)
    phase = _market_phase(universe, history)
    leaders = _rank_boards(universe, "leader")[:12]
    starters = _rank_boards(universe, "starter")[:10]
    crowded = _rank_boards(universe, "crowded")[:10]
    retreat = _rank_boards(universe, "retreat")[:10]
    value_zones = _rank_boards(universe, "value")[:10]
    payload = {
        "role": "Market Pulse Agent",
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": phase["phase"],
        "score": phase["score"],
        "summary": phase["summary"],
        "stance": phase,
        "sections": {
            "leaders": leaders,
            "starters": starters,
            "crowded": crowded,
            "retreat": retreat,
            "value_zones": value_zones,
        },
        "raw_counts": {
            "industry": len(industry),
            "concept": len(concept),
            "total": len(universe),
        },
        "source_status": _source_status(industry, concept),
        "sources": SOURCE_REGISTRY,
        "method": {
            "leader": "涨幅、成交额、主力净流入、上涨家数占比和领涨股共同确认，同时看是否延续前几日强化。",
            "starter": "中等涨幅、资金净流入、上涨家数扩散且未明显过热，标记为启动预警。",
            "crowded": "涨幅/振幅/换手过高，或连续强势后开始资金背离，标记高位分歧。",
            "retreat": "板块下跌、主力净流出、下跌家数占比高，且相对前几日明显走弱，标记退潮。",
            "value": "资金刚转强、涨幅未过热、扩散尚可，作为性价比观察区。",
        },
    }
    _persist_market_pulse(conn, payload)
    return payload


def latest_market_pulse(conn, trade_date: str | None = None) -> dict[str, Any]:
    if trade_date is None:
        row = conn.execute("SELECT MAX(trade_date) AS trade_date FROM market_pulse_snapshots").fetchone()
        trade_date = row["trade_date"] if row and row["trade_date"] else None
    if trade_date:
        row = conn.execute(
            "SELECT payload FROM market_pulse_snapshots WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        if row:
            try:
                return json.loads(row["payload"])
            except (TypeError, ValueError):
                pass
    return build_market_pulse(conn, date.today().isoformat())


def _persist_market_pulse(conn, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO market_pulse_snapshots (
            trade_date, generated_at, phase, score, summary, payload
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            generated_at=excluded.generated_at,
            phase=excluded.phase,
            score=excluded.score,
            summary=excluded.summary,
            payload=excluded.payload
        """,
        (
            payload["trade_date"],
            payload["generated_at"],
            payload["phase"],
            payload["score"],
            payload["summary"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()


def _fetch_board_rows(kind: str) -> list[dict[str, Any]]:
    fs = "m:90+t:2" if kind == "industry" else "m:90+t:3"
    payload = _fetch_board_payload(fs)
    diff = ((payload.get("data") or {}).get("diff") or [])
    rows = [_normalize_board(row, kind) for row in diff]
    return [row for row in rows if row["name"] and row["amount_yi"] >= 1]


def _fetch_board_payload(fs: str) -> dict[str, Any]:
    params = {**EASTMONEY_CLIST_BASE_PARAMS, "fs": fs}
    kwargs = {
        "params": params,
        "headers": {"User-Agent": "Mozilla/5.0"},
        "timeout": 15,
    }
    try:
        response = requests.get(EASTMONEY_CLIST_URL, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ProxyError:
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(EASTMONEY_CLIST_URL, **kwargs)
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
                EASTMONEY_CLIST_URL,
                "--get",
            ]
            for key, value in params.items():
                curl_cmd.extend(["--data-urlencode", f"{key}={value}"])
            result = subprocess.run(curl_cmd, check=True, capture_output=True, text=True)
            return json.loads(result.stdout)


def _normalize_board(row: dict[str, Any], kind: str) -> dict[str, Any]:
    up = _to_float(row.get("f104")) or 0
    down = _to_float(row.get("f105")) or 0
    total = up + down
    amount_yi = (_to_float(row.get("f6")) or 0) / 100_000_000
    main_yi = (_to_float(row.get("f62")) or 0) / 100_000_000
    change = _to_float(row.get("f3")) or 0
    amplitude = _to_float(row.get("f7")) or 0
    turnover = _to_float(row.get("f8")) or 0
    breadth = up / total if total else 0.5
    fund_intensity = main_yi / amount_yi if amount_yi else 0
    row_out = {
        "code": str(row.get("f12") or ""),
        "name": str(row.get("f14") or ""),
        "kind": kind,
        "change_pct": round(change, 2),
        "amount_yi": round(amount_yi, 2),
        "main_inflow_yi": round(main_yi, 2),
        "large_inflow_yi": round((_to_float(row.get("f66")) or 0) / 100_000_000, 2),
        "large_inflow_pct": _round(row.get("f69")),
        "medium_inflow_yi": round((_to_float(row.get("f78")) or 0) / 100_000_000, 2),
        "retail_inflow_yi": round((_to_float(row.get("f84")) or 0) / 100_000_000, 2),
        "amplitude_pct": round(amplitude, 2),
        "turnover_pct": round(turnover, 2),
        "volume_ratio": _round(row.get("f10")),
        "up_count": int(up),
        "down_count": int(down),
        "breadth": round(breadth, 3),
        "fund_intensity": round(fund_intensity, 4),
        "leader_stock": str(row.get("f128") or ""),
        "leader_code": str(row.get("f140") or ""),
    }
    row_out["scores"] = _board_scores(row_out)
    row_out["stage"] = _stage(row_out)
    row_out["action_hint"] = _action_hint(row_out)
    return row_out


def _board_scores(row: dict[str, Any]) -> dict[str, float]:
    change = row["change_pct"]
    breadth = row["breadth"]
    inflow = row["main_inflow_yi"]
    amount = row["amount_yi"]
    amplitude = row["amplitude_pct"]
    turnover = row["turnover_pct"]
    strength = _clamp(50 + change * 7 + (breadth - 0.5) * 35)
    capital = _clamp(50 + min(25, inflow * 2.2) + row["fund_intensity"] * 240)
    diffusion = _clamp(35 + breadth * 65)
    heat = _clamp(35 + min(30, amount / 8) + turnover * 3 + amplitude * 1.8)
    crowding = _clamp(max(0, change - 3) * 12 + max(0, amplitude - 6) * 5 + max(0, turnover - 5) * 5 - max(0, inflow) * 0.8)
    activation = _clamp(45 + (1 if 0.5 <= change <= 3.2 else -1) * 12 + max(0, inflow) * 2 + (breadth - 0.5) * 45 - max(0, change - 4) * 10)
    value = _clamp(40 + activation * 0.45 + capital * 0.25 + diffusion * 0.20 - crowding * 0.35)
    retreat = _clamp(max(0, -change) * 18 + max(0, -inflow) * 2.2 + max(0.0, 0.45 - breadth) * 95)
    return {
        "strength": round(strength, 1),
        "capital": round(capital, 1),
        "diffusion": round(diffusion, 1),
        "heat": round(heat, 1),
        "activation": round(activation, 1),
        "crowding": round(crowding, 1),
        "value": round(value, 1),
        "retreat": round(retreat, 1),
    }


def _stage(row: dict[str, Any]) -> str:
    scores = row["scores"]
    if scores["retreat"] >= 62:
        return "退潮"
    if scores["crowding"] >= 62:
        return "高位拥挤"
    if scores["strength"] >= 70 and scores["capital"] >= 58:
        return "主升"
    if scores["activation"] >= 64 and scores["crowding"] < 58:
        return "启动预警"
    if scores["value"] >= 60:
        return "性价比观察"
    return "震荡观察"


def _action_hint(row: dict[str, Any]) -> str:
    stage = row["stage"]
    if stage == "主升":
        return "只看核心中军和低吸点，不追一致加速。"
    if stage == "启动预警":
        return "重点观察首个放量回踩或板块内中军确认。"
    if stage == "性价比观察":
        return "适合加入观察池，等资金连续性确认。"
    if stage == "高位拥挤":
        return "持仓注意分歧和放量滞涨，新增仓位谨慎。"
    if stage == "退潮":
        return "回避补跌与反抽诱多，等资金重新流入。"
    return "仅观察，不作为优先交易方向。"


def _rank_boards(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    key_map = {
        "leader": lambda r: r["scores"]["strength"] * 0.35 + r["scores"]["capital"] * 0.35 + r["scores"]["diffusion"] * 0.2 + r["scores"]["heat"] * 0.1,
        "starter": lambda r: r["scores"]["activation"] * 0.55 + r["scores"]["capital"] * 0.25 + r["scores"]["diffusion"] * 0.2 - r["scores"]["crowding"] * 0.25,
        "crowded": lambda r: r["scores"]["crowding"] * 0.65 + r["scores"]["heat"] * 0.25 + max(0, r["change_pct"]) * 2,
        "retreat": lambda r: r["scores"]["retreat"] * 0.75 + max(0, -r["main_inflow_yi"]) * 1.5,
        "value": lambda r: r["scores"]["value"] * 0.55 + r["scores"]["activation"] * 0.25 + r["scores"]["capital"] * 0.2,
    }
    filtered = rows
    if mode == "starter":
        filtered = [r for r in rows if r["stage"] in {"启动预警", "性价比观察", "震荡观察"} and r["change_pct"] <= 4.2]
    elif mode == "crowded":
        filtered = [r for r in rows if r["scores"]["crowding"] >= 45 or r["stage"] == "高位拥挤"]
    elif mode == "retreat":
        filtered = [r for r in rows if r["scores"]["retreat"] >= 35]
    elif mode == "value":
        filtered = [r for r in rows if r["stage"] in {"启动预警", "性价比观察"} and r["scores"]["crowding"] < 60]
    ranked = sorted(filtered, key=key_map[mode], reverse=True)
    return [{**row, "rank_score": round(key_map[mode](row), 1)} for row in ranked]


def _recent_phase_context(conn, trade_date: str, window: int = 4) -> list[dict[str, Any]]:
    history = []
    rows = conn.execute(
        """
        SELECT payload
        FROM market_pulse_snapshots
        WHERE trade_date < ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (trade_date, window),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError, KeyError):
            continue
        stance = payload.get("stance") or {}
        if stance:
            history.append(stance)
    return history


def _market_phase(rows: list[dict[str, Any]], history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not rows:
        return {
            "phase": "data_degraded",
            "score": 0,
            "summary": "板块行情源不可用，市场脉搏暂停输出。",
            "positive_ratio": 0,
            "fund_positive_ratio": 0,
        }
    positives = [row for row in rows if row["change_pct"] > 0]
    fund_positive = [row for row in rows if row["main_inflow_yi"] > 0]
    strong = [row for row in rows if row["scores"]["strength"] >= 70]
    crowded = [row for row in rows if row["scores"]["crowding"] >= 65]
    retreat = [row for row in rows if row["scores"]["retreat"] >= 62]
    positive_ratio = len(positives) / len(rows)
    fund_positive_ratio = len(fund_positive) / len(rows)
    avg_change = mean([row["change_pct"] for row in rows])
    avg_breadth = mean([row["breadth"] for row in rows])
    score = _clamp(45 + positive_ratio * 22 + fund_positive_ratio * 18 + avg_change * 4 + (avg_breadth - 0.5) * 18 - len(retreat) / len(rows) * 20)
    recent = history or []
    prior_score = mean([float(item.get("score") or 0) for item in recent]) if recent else score
    prior_positive = mean([float(item.get("positive_ratio") or 0) for item in recent]) if recent else positive_ratio
    prior_fund = mean([float(item.get("fund_positive_ratio") or 0) for item in recent]) if recent else fund_positive_ratio
    prior_strong = mean([float(item.get("strong_count") or 0) for item in recent]) if recent else len(strong)
    score_delta = score - prior_score
    breadth_delta = positive_ratio - prior_positive
    fund_delta = fund_positive_ratio - prior_fund
    if score >= 72 and len(strong) >= 10 and positive_ratio >= 0.56 and fund_positive_ratio >= 0.5 and score_delta >= -1:
        phase = "主线强化"
        summary = "板块扩散、资金流入和强势板块数量同时维持高位，主线仍在强化，优先看核心中军和分歧承接。"
    elif score >= 58 and (score_delta >= 4 or breadth_delta >= 0.05 or fund_delta >= 0.05) and len(retreat) <= len(strong):
        phase = "弱修复"
        summary = "市场在修复，但主线还未全面确认，适合看低位启动、分歧回流和性价比方向。"
    elif score <= 44 or len(retreat) > max(len(strong), len(crowded)) or (score_delta <= -6 and positive_ratio < 0.45):
        phase = "退潮防守"
        summary = "退潮板块数量占优且较前几日走弱，追涨性价比差，优先防守和等待新主线确认。"
    elif len(crowded) >= 10 and (score_delta < 0 or len(strong) < prior_strong):
        phase = "主线分歧"
        summary = "局部主线仍有热度，但拥挤和分歧在上升，更适合看承接质量而不是追一致加速。"
    else:
        phase = "结构轮动"
        summary = "市场不是全面行情，资金在局部板块间轮动，优先找相对强势且位置合适的方向。"
    return {
        "phase": phase,
        "score": round(score, 1),
        "summary": summary,
        "positive_ratio": round(positive_ratio, 3),
        "fund_positive_ratio": round(fund_positive_ratio, 3),
        "avg_change_pct": round(avg_change, 2),
        "avg_breadth": round(avg_breadth, 3),
        "strong_count": len(strong),
        "crowded_count": len(crowded),
        "retreat_count": len(retreat),
        "score_delta": round(score_delta, 1),
        "positive_ratio_delta": round(breadth_delta, 3),
        "fund_positive_ratio_delta": round(fund_delta, 3),
    }


def _source_status(industry: list[dict], concept: list[dict]) -> dict[str, Any]:
    status = "ready" if industry and concept else "partial" if industry or concept else "failed"
    return {
        "status": status,
        "industry_count": len(industry),
        "concept_count": len(concept),
        "note": "当前版本以东财板块资金流为硬数据底座，社媒热度作为下一阶段叙事源接入。",
    }


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, ndigits: int = 2) -> float | None:
    parsed = _to_float(value)
    return round(parsed, ndigits) if parsed is not None else None


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))
