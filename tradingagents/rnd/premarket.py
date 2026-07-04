from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import requests

from .config import RND_HOME


PREMARKET_CACHE_PATH = RND_HOME / "premarket_snapshot.json"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
    )
}
DSA_SOURCE = "https://github.com/ZhuLinsen/daily_stock_analysis"

_INDEX_SYMBOLS = {
    "上证指数": "s_sh000001",
    "深证成指": "s_sz399001",
    "创业板指": "s_sz399006",
    "恒生指数": "hkHSI",
    "纳斯达克": "usIXIC",
    "标普500": "usINX",
}
_IMPORTANT_NEWS_TERMS = (
    "A股",
    "证监会",
    "央行",
    "财政部",
    "国务院",
    "美联储",
    "关税",
    "人民币",
    "汇率",
    "半导体",
    "芯片",
    "人工智能",
    "AI",
    "新能源",
    "光伏",
    "稀土",
    "原油",
    "黄金",
    "美股",
    "港股",
)
_RISK_TERMS = (
    "风险",
    "下跌",
    "暴跌",
    "制裁",
    "冲突",
    "调查",
    "减持",
    "终止",
    "退市",
    "违约",
    "暂停",
)


def build_premarket_brief(
    universe: list[dict],
    *,
    now: datetime | None = None,
    cache_path: Path = PREMARKET_CACHE_PATH,
) -> dict[str, Any]:
    """Build a source-attributed pre-market message snapshot.

    The structured payload and fail-open cache follow the useful integration
    pattern from ZhuLinsen/daily_stock_analysis without importing its runtime.
    """

    current = now or datetime.now()
    session_date = _next_weekday(current.date(), current.hour)
    cached = _read_cache(cache_path)
    jobs: dict[str, Callable[[], list[dict]]] = {
        "indices": _fetch_index_tape,
        "headlines": _fetch_global_headlines,
        "calendar": lambda: _fetch_economic_calendar(session_date),
        "hot_stocks": _fetch_xueqiu_hot,
        "notices": lambda: _fetch_watchlist_notices(universe, current.date()),
    }
    fields: dict[str, list[dict]] = {}
    sources: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        pending = {executor.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(pending):
            name = pending[future]
            try:
                rows = future.result()
                fields[name] = rows
                sources.append({"name": name, "status": "ready", "count": len(rows)})
            except Exception as exc:  # network/provider failures are fail-open
                stale_rows = cached.get(name) if isinstance(cached.get(name), list) else []
                fields[name] = stale_rows
                sources.append(
                    {
                        "name": name,
                        "status": "stale" if stale_rows else "failed",
                        "count": len(stale_rows),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    headlines = _select_headlines(fields.get("headlines", []), universe)
    watchlist_news = _watchlist_headline_hits(headlines, universe)
    payload = {
        "version": 1,
        "kind": "premarket_brief",
        "market_scope": "A股",
        "generated_at": current.isoformat(timespec="seconds"),
        "session_date": session_date.isoformat(),
        "session_label": f"{session_date:%Y-%m-%d} 盘前",
        "stance": _build_stance(fields.get("indices", []), headlines),
        "indices": fields.get("indices", []),
        "headlines": headlines[:10],
        "watchlist_news": watchlist_news[:8],
        "calendar": _prioritize_calendar(fields.get("calendar", []))[:8],
        "hot_stocks": fields.get("hot_stocks", [])[:10],
        "notices": fields.get("notices", [])[:12],
        "sources": sorted(sources, key=lambda item: item["name"]),
        "reference_project": {
            "name": "daily_stock_analysis",
            "url": DSA_SOURCE,
            "license": "MIT",
        },
    }
    ready_count = sum(item["status"] == "ready" for item in sources)
    stale_count = sum(item["status"] == "stale" for item in sources)
    payload["status"] = "ready" if ready_count == len(jobs) else "partial" if ready_count or stale_count else "failed"
    if ready_count:
        _write_cache(cache_path, payload)
    return payload


def _request_json(url: str, *, params: dict | None = None, timeout: float = 7.0) -> dict:
    response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("provider returned a non-object payload")
    return data


def _fetch_index_tape() -> list[dict]:
    query = ",".join(_INDEX_SYMBOLS.values())
    response = requests.get(
        f"https://qt.gtimg.cn/q={query}",
        headers={**REQUEST_HEADERS, "Referer": "https://finance.qq.com/"},
        timeout=7,
    )
    response.raise_for_status()
    return _parse_tencent_quotes(response.content.decode("gbk", errors="ignore"))


def _parse_tencent_quotes(raw: str) -> list[dict]:
    symbol_to_label = {value: key for key, value in _INDEX_SYMBOLS.items()}
    rows = []
    for line in raw.splitlines():
        match = re.search(r"v_([^=]+)=\"([^\"]*)\"", line)
        if not match:
            continue
        symbol, body = match.groups()
        values = body.split("~")
        if len(values) < 6:
            continue
        compact = symbol.startswith("s_")
        change_index, pct_index = (4, 5) if compact else (31, 32)
        if len(values) <= pct_index:
            continue
        rows.append(
            {
                "name": symbol_to_label.get(symbol, values[1] or symbol),
                "value": _to_float(values[3]),
                "change": _to_float(values[change_index]),
                "change_pct": _to_float(values[pct_index]),
                "quote_time": "上一交易日" if compact else (values[30] if len(values) > 30 else ""),
                "source": "腾讯行情",
            }
        )
    if not rows:
        raise ValueError("Tencent index tape returned no parsable quotes")
    order = {name: index for index, name in enumerate(_INDEX_SYMBOLS)}
    return sorted(rows, key=lambda item: order.get(item["name"], 999))


def _fetch_global_headlines() -> list[dict]:
    data = _request_json(
        "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
        params={
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": "60",
            "req_trace": str(int(datetime.now().timestamp() * 1000)),
        },
    )
    items = data.get("data", {}).get("fastNewsList", [])
    rows = []
    for item in items:
        title = _clean_text(item.get("title") or item.get("summary"))
        summary = _clean_text(item.get("summary"))
        if not title:
            continue
        code = str(item.get("code") or "").strip()
        rows.append(
            {
                "title": title,
                "summary": summary[:260],
                "published_at": str(item.get("showTime") or ""),
                "source": "东方财富快讯",
                "url": f"https://finance.eastmoney.com/a/{code}.html" if code else "https://kuaixun.eastmoney.com/",
            }
        )
    if not rows:
        raise ValueError("Eastmoney fast news returned no rows")
    return rows


def _select_headlines(headlines: list[dict], universe: list[dict]) -> list[dict]:
    names = [str(item.get("name") or "") for item in universe]

    def score(item: dict) -> int:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        important = sum(term.lower() in text.lower() for term in _IMPORTANT_NEWS_TERMS)
        tracked = sum(name and name in text for name in names)
        risk = sum(term in text for term in _RISK_TERMS)
        return tracked * 8 + important * 2 + risk

    ranked = sorted(enumerate(headlines), key=lambda pair: (-score(pair[1]), pair[0]))
    selected = [item for _, item in ranked if score(item) > 0]
    if len(selected) < 8:
        seen = {item["title"] for item in selected}
        selected.extend(item for item in headlines if item["title"] not in seen)
    for item in selected:
        item["risk"] = any(term in f"{item['title']} {item.get('summary', '')}" for term in _RISK_TERMS)
    return selected


def _watchlist_headline_hits(headlines: list[dict], universe: list[dict]) -> list[dict]:
    hits = []
    for item in headlines:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        matched = [u.get("name", "") for u in universe if u.get("name") and u["name"] in text]
        if matched:
            hits.append({**item, "stocks": matched})
    return hits


def _fetch_economic_calendar(session_date: date) -> list[dict]:
    formatted = session_date.isoformat()
    data = _request_json(
        "https://finance.pae.baidu.com/sapi/v1/financecalendar",
        params={
            "start_date": formatted,
            "end_date": formatted,
            "pn": "0",
            "rn": "100",
            "cate": "economic_data",
            "finClientType": "pc",
        },
    )
    rows = []
    for group in data.get("Result", {}).get("calendarInfo", []):
        if group.get("date") != formatted:
            continue
        for item in group.get("list", []):
            rows.append(
                {
                    "time": str(item.get("time") or "待定"),
                    "region": str(item.get("country") or item.get("region") or "全球"),
                    "event": _clean_text(item.get("title")),
                    "importance": int(_to_float(item.get("star"))),
                    "previous": str(item.get("formerVal") or "--"),
                    "expected": str(item.get("indicateVal") or "--"),
                    "source": "百度财经日历",
                }
            )
    if not rows:
        raise ValueError("Baidu economic calendar returned no rows")
    return rows


def _prioritize_calendar(rows: list[dict]) -> list[dict]:
    important = [item for item in rows if item.get("importance", 0) >= 2]
    selected = important or rows
    return sorted(selected, key=lambda item: (-int(item.get("importance", 0)), item.get("time", "")))


def _fetch_xueqiu_hot() -> list[dict]:
    session = requests.Session()
    headers = {
        **REQUEST_HEADERS,
        "Referer": "https://xueqiu.com/hq",
        "X-Requested-With": "XMLHttpRequest",
    }
    session.get("https://xueqiu.com/", headers=headers, timeout=5)
    response = session.get(
        "https://xueqiu.com/service/v5/stock/screener/screen",
        params={
            "category": "CN",
            "size": "30",
            "order": "desc",
            "order_by": "tweet",
            "only_count": "0",
            "page": "1",
        },
        headers=headers,
        timeout=7,
    )
    response.raise_for_status()
    items = response.json().get("data", {}).get("list", [])
    rows = [
        {
            "rank": index,
            "name": item.get("name") or item.get("symbol"),
            "symbol": item.get("symbol") or "",
            "attention": int(_to_float(item.get("tweet"))),
            "change_pct": _to_float(item.get("pct")),
            "source": "雪球讨论榜",
        }
        for index, item in enumerate(items[:10], start=1)
    ]
    if not rows:
        raise ValueError("Xueqiu hot list returned no rows")
    return rows


def _fetch_watchlist_notices(universe: list[dict], current_date: date) -> list[dict]:
    start = current_date - timedelta(days=5)

    def fetch_one(stock: dict) -> list[dict]:
        ticker = str(stock.get("ticker") or "")
        code = ticker.split(".")[0]
        if not re.fullmatch(r"\d{6}", code):
            return []
        data = _request_json(
            "https://np-anotice-stock.eastmoney.com/api/security/ann",
            params={
                "sr": "-1",
                "page_size": "20",
                "page_index": "1",
                "ann_type": "A",
                "client_source": "web",
                "f_node": "0",
                "s_node": "0",
                "stock_list": code,
                "begin_time": start.isoformat(),
                "end_time": current_date.isoformat(),
            },
        )
        rows = []
        for item in data.get("data", {}).get("list", [])[:3]:
            art_code = str(item.get("art_code") or "")
            rows.append(
                {
                    "stock": stock.get("name") or code,
                    "ticker": ticker,
                    "title": _clean_text(item.get("title")),
                    "date": str(item.get("notice_date") or "")[:10],
                    "url": f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html",
                    "source": "东方财富公告",
                }
            )
        return rows

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(universe)))) as executor:
        futures = [executor.submit(fetch_one, stock) for stock in universe]
        for future in as_completed(futures):
            rows.extend(future.result())
    return sorted(rows, key=lambda item: item.get("date", ""), reverse=True)


def _build_stance(indices: list[dict], headlines: list[dict]) -> dict[str, str]:
    external = [
        item.get("change_pct", 0.0)
        for item in indices
        if item.get("name") in {"恒生指数", "纳斯达克", "标普500"}
    ]
    average = sum(external) / len(external) if external else 0.0
    risks = sum(bool(item.get("risk")) for item in headlines[:10])
    if average <= -1.0 or risks >= 4:
        return {
            "level": "谨慎",
            "summary": "外部市场或风险消息偏弱，开盘先看承接与量价确认，避免集合竞价后直接追价。",
        }
    if average >= 1.0 and risks <= 2:
        return {
            "level": "偏积极",
            "summary": "外部风险偏好较强，但盘前信息只用于制定观察条件，仍需等待开盘量价确认。",
        }
    return {
        "level": "中性",
        "summary": "隔夜线索未形成单边共振，优先核对自选股公告、竞价强弱与首小时成交结构。",
    }


def _next_weekday(value: date, current_hour: int = 0) -> date:
    candidate = value
    if candidate.weekday() >= 5:
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if current_hour >= 15:
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate


def _read_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
