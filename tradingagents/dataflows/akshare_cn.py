"""A-share (China market) data sources via akshare.

akshare (github.com/akfamily/akshare) is the de-facto free data layer for
Chinese markets. This module wires three things the English-only sources
(Yahoo / StockTwits / Reddit) cannot provide for A-shares:

  1. get_news_akshare        — 东方财富 个股新闻 (per-ticker headlines)
  2. get_global_news_akshare — 东方财富 全球财经快讯 (macro / market news, CN)
  3. fetch_cn_sentiment      — 千股千评 量化情绪 + 个股新闻流 as a retail/
                               institutional sentiment proxy (replaces the
                               StockTwits / Reddit blocks for A-shares)

Routing contract: the news functions raise ``NoMarketDataError`` for any
non-A-share ticker so the vendor router (interface.route_to_vendor) falls
through to yfinance/alpha_vantage with zero behavioural change for US tickers.

Note on look-ahead: the akshare endpoints return *latest* real-time items,
not a historical archive keyed by date. News is still filtered to the
requested ``[start_date, end_date]`` window where each item carries a
timestamp, so a same-day / recent analysis is well covered; deep historical
backtests will see fewer rows. This is flagged in the block headers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd

from .errors import NoMarketDataError

_A_SHARE_SUFFIXES = (".SS", ".SZ", ".SH", ".BJ")


def is_a_share(ticker: str) -> bool:
    """True for A-share tickers: ``300811.SZ`` / ``600519.SS`` or bare 6-digit."""
    t = (ticker or "").strip().upper()
    if t.endswith(_A_SHARE_SUFFIXES):
        return True
    return bool(re.fullmatch(r"\d{6}", t))


def to_ak_symbol(ticker: str) -> str:
    """``300811.SZ`` -> ``300811`` (akshare wants the bare 6-digit code)."""
    t = (ticker or "").strip().upper()
    for suf in _A_SHARE_SUFFIXES:
        if t.endswith(suf):
            return t[: -len(suf)]
    return t


def get_ohlcv_akshare_frame(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Return normalized A-share OHLCV from akshare as Date/Open/High/Low/Close/Volume.

    akshare's Eastmoney endpoint uses Chinese column names and bare six-digit
    symbols. Normalize it to the same shape yfinance/stockstats expects so A
    shares do not depend on Yahoo's overseas endpoint for core prices.
    """
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; akshare OHLCV skipped")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
        end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError("start_date/end_date must be YYYY-MM-DD") from exc

    ak = _ak()
    code = to_ak_symbol(ticker)
    try:
        df = _retry(
            lambda: ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq",
            ),
            tries=4,
        )
    except Exception as eastmoney_error:
        try:
            return _get_ohlcv_tencent_frame(ticker, start_date, end_date)
        except Exception as tencent_error:
            raise NoMarketDataError(
                ticker,
                code,
                "A-share OHLCV sources failed; "
                f"Eastmoney: {eastmoney_error}; Tencent: {tencent_error}",
            ) from tencent_error

    if df is None or len(df) == 0:
        raise NoMarketDataError(ticker, code, f"no rows between {start_date} and {end_date}")

    out = df.rename(
        columns={
            "日期": "Date",
            "开盘": "Open",
            "最高": "High",
            "最低": "Low",
            "收盘": "Close",
            "成交量": "Volume",
        }
    )[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["Date", "Close"]).sort_values("Date")
    out["Adj Close"] = out["Close"]
    out.attrs["source"] = "akshare/Eastmoney"
    return out


def _get_ohlcv_tencent_frame(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch adjusted daily bars from Tencent when Eastmoney is unavailable."""
    import requests

    code = to_ak_symbol(ticker)
    prefix = "sh" if code.startswith(("6", "9")) else "bj" if code.startswith("8") else "sz"
    market_code = f"{prefix}{code}"
    response = requests.get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{market_code},day,{start_date},{end_date},2000,qfq"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise ValueError(f"Tencent kline error: {payload.get('msg') or payload.get('code')}")
    stock_data = (payload.get("data") or {}).get(market_code) or {}
    rows = stock_data.get("qfqday") or stock_data.get("day") or []
    if not rows:
        raise ValueError("Tencent kline returned no rows")

    frame = pd.DataFrame(
        [row[:6] for row in rows if len(row) >= 6],
        columns=["Date", "Open", "Close", "High", "Low", "Volume"],
    )
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["Date", "Close"]).sort_values("Date")
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    frame = frame[(frame["Date"] >= start_ts) & (frame["Date"] <= end_ts)]
    if frame.empty:
        raise ValueError(f"Tencent kline has no rows between {start_date} and {end_date}")
    frame["Adj Close"] = frame["Close"]
    frame.attrs["source"] = "Tencent qfq kline"
    return frame


def get_stock_data_akshare(ticker: str, start_date: str, end_date: str) -> str:
    """Formatted A-share OHLCV data via akshare / Eastmoney."""
    data = get_ohlcv_akshare_frame(ticker, start_date, end_date)
    for col in ("Open", "High", "Low", "Close", "Adj Close"):
        data[col] = data[col].round(2)

    csv_string = data.to_csv(index=False)
    code = to_ak_symbol(ticker)
    source = data.attrs.get("source", "akshare/Eastmoney")
    header = f"# Stock data for {code} (from {ticker}, source: {source}) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string


def _ak():
    import akshare as ak  # lazy: importing akshare is slow and optional
    return ak


def _retry(fn, tries: int = 5, delay: float = 0.5, backoff: float = 2.0):
    """Call ``fn`` with retries + exponential backoff — akshare endpoints are
    occasionally flaky (RemoteDisconnected / transient resets). The default
    schedule (0.5, 1, 2, 4s over 5 tries) reliably absorbs the intermittent
    东财 individual-fund-flow drops. Re-raises the last error if all fail."""
    import time
    last = None
    wait = delay
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - transient network/interface errors
            last = e
            if i < tries - 1:
                time.sleep(wait)
                wait *= backoff
    raise last


def _float_or_zero(value) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _tencent_quote(code: str) -> dict:
    """Tencent quote/valuation snapshot.

    This follows the data-source priority recommended by the a-stock-data
    project: use Tencent for real-time quote/valuation fields because it is a
    keyless HTTP endpoint with lower blocking risk than Eastmoney.
    """
    import requests

    prefix = "sh" if code.startswith(("6", "9")) else "bj" if code.startswith("8") else "sz"
    resp = requests.get(
        f"https://qt.gtimg.cn/q={prefix}{code}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    raw = resp.content.decode("gbk", errors="ignore")
    if '"' not in raw:
        raise NoMarketDataError(code, detail="Tencent quote returned no payload")
    vals = raw.split('"')[1].split("~")
    if len(vals) < 53:
        raise NoMarketDataError(code, detail="Tencent quote payload is incomplete")
    return {
        "name": vals[1],
        "price": _float_or_zero(vals[3]),
        "last_close": _float_or_zero(vals[4]),
        "open": _float_or_zero(vals[5]),
        "change_amt": _float_or_zero(vals[31]),
        "change_pct": _float_or_zero(vals[32]),
        "high": _float_or_zero(vals[33]),
        "low": _float_or_zero(vals[34]),
        "amount_wan": _float_or_zero(vals[37]),
        "turnover_pct": _float_or_zero(vals[38]),
        "pe_ttm": _float_or_zero(vals[39]),
        "amplitude_pct": _float_or_zero(vals[43]),
        "mcap_yi": _float_or_zero(vals[44]),
        "float_mcap_yi": _float_or_zero(vals[45]),
        "pb": _float_or_zero(vals[46]),
        "limit_up": _float_or_zero(vals[47]),
        "limit_down": _float_or_zero(vals[48]),
        "vol_ratio": _float_or_zero(vals[49]),
        "pe_static": _float_or_zero(vals[52]),
    }


def _sina_financial_report(code: str, report_type: str, num: int = 8) -> list[dict]:
    """Sina financial statements.

    report_type: fzb=balance sheet, lrb=income statement, llb=cash flow.
    The nested ``result.data.report_list`` shape mirrors the corrected parser
    documented by a-stock-data.
    """
    import requests

    prefix = "sh" if code.startswith("6") else "sz"
    resp = requests.get(
        "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
        params={
            "paperCode": f"{prefix}{code}",
            "source": report_type,
            "type": "0",
            "page": "1",
            "num": str(num),
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    report_list = resp.json().get("result", {}).get("data", {}).get("report_list", {}) or {}
    rows: list[dict] = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period]
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for item in obj.get("data", []) or []:
            title = item.get("item_title", "")
            value = item.get("item_value")
            if not title or value is None:
                continue
            rec[title] = value
            yoy = item.get("item_tongbi")
            if yoy not in (None, ""):
                rec[f"{title}_同比"] = yoy
        rows.append(rec)
    return rows


def _filter_financial_rows(rows: list[dict], curr_date: str | None) -> list[dict]:
    if not curr_date:
        return rows
    try:
        cutoff = datetime.strptime(curr_date, "%Y-%m-%d").date()
    except ValueError:
        return rows
    kept = []
    for row in rows:
        try:
            period = datetime.strptime(str(row.get("报告期", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if period <= cutoff:
            kept.append(row)
    return kept


def _financial_rows_to_csv(
    ticker: str,
    rows: list[dict],
    title: str,
    source: str,
    curr_date: str | None,
) -> str:
    if not rows:
        raise NoMarketDataError(ticker, detail=f"{source} returned no {title} rows")
    frame = pd.DataFrame(rows)
    header = f"# {title} for {ticker} (source: {source})\n"
    if curr_date:
        header += f"# Filtered to report periods <= {curr_date}\n"
    header += f"# Total records: {len(frame)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + frame.to_csv(index=False)


def get_fundamentals_akshare(ticker: str, curr_date: str | None = None) -> str:
    """A-share fundamentals from Tencent quote + Eastmoney company profile."""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; akshare fundamentals skipped")
    code = to_ak_symbol(ticker)
    quote = _tencent_quote(code)
    lines = [
        f"# A-share Company Fundamentals for {ticker}",
        "# Sources: Tencent quote/valuation; Eastmoney company profile via akshare when available",
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Name: {quote.get('name')}",
        f"Price: {quote.get('price')}",
        f"Change Pct: {quote.get('change_pct')}%",
        f"Turnover Pct: {quote.get('turnover_pct')}%",
        f"Volume Ratio: {quote.get('vol_ratio')}",
        f"Market Cap: {quote.get('mcap_yi')} 亿",
        f"Float Market Cap: {quote.get('float_mcap_yi')} 亿",
        f"PE Ratio (TTM): {quote.get('pe_ttm')}",
        f"Static PE: {quote.get('pe_static')}",
        f"Price to Book: {quote.get('pb')}",
        f"Limit Up: {quote.get('limit_up')}",
        f"Limit Down: {quote.get('limit_down')}",
    ]
    try:
        ak = _ak()
        info = _retry(lambda: ak.stock_individual_info_em(symbol=code), tries=3)
        if info is not None and len(info):
            lines.extend(["", "## Eastmoney Company Profile"])
            for _, row in info.iterrows():
                label = str(row.get("item", "")).strip()
                value = str(row.get("value", "")).strip()
                if label and value:
                    lines.append(f"{label}: {value}")
    except Exception:
        # Company profile is useful but non-critical. Do not inject transient
        # provider errors into the analyst prompt; the degradation is tracked in
        # the R&D improvement queue instead.
        pass
    return "\n".join(lines)


def get_income_statement_akshare(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; Sina income skipped")
    rows = _filter_financial_rows(_sina_financial_report(to_ak_symbol(ticker), "lrb"), curr_date)
    return _financial_rows_to_csv(ticker, rows, "Income Statement", "Sina Finance", curr_date)


def get_balance_sheet_akshare(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; Sina balance sheet skipped")
    rows = _filter_financial_rows(_sina_financial_report(to_ak_symbol(ticker), "fzb"), curr_date)
    return _financial_rows_to_csv(ticker, rows, "Balance Sheet", "Sina Finance", curr_date)


def get_cashflow_akshare(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; Sina cash flow skipped")
    rows = _filter_financial_rows(_sina_financial_report(to_ak_symbol(ticker), "llb"), curr_date)
    return _financial_rows_to_csv(ticker, rows, "Cash Flow", "Sina Finance", curr_date)


def _parse_dt(s: str):
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# News (per-ticker)
# ---------------------------------------------------------------------------
def get_news_akshare(ticker: str, start_date: str, end_date: str) -> str:
    """Per-ticker A-share news via 东方财富 (akshare ``stock_news_em``).

    Raises ``NoMarketDataError`` for non-A-share tickers so the router
    delegates to the next configured vendor.
    """
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, detail="not an A-share; akshare CN news skipped")

    ak = _ak()
    code = to_ak_symbol(ticker)
    try:
        df = ak.stock_news_em(symbol=code)
    except Exception as e:  # network / interface drift -> let router decide
        raise NoMarketDataError(
            ticker, code, f"akshare stock_news_em failed: {e}"
        ) from e

    if df is None or len(df) == 0:
        return f"No A-share news found for {ticker} (东方财富/akshare)."

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        start_dt, end_dt = None, None

    rows = []
    for _, r in df.iterrows():
        title = str(r.get("新闻标题", "")).strip()
        body = str(r.get("新闻内容", "")).strip()
        src = str(r.get("文章来源", "")).strip()
        ts = str(r.get("发布时间", "")).strip()
        link = str(r.get("新闻链接", "")).strip()
        pub = _parse_dt(ts)
        # Look-ahead-safe window filter when both the item and window are dated.
        if pub is not None and start_dt is not None and not (start_dt <= pub < end_dt):
            continue
        rows.append((pub, title, body, src, ts, link))

    if not rows:
        return (
            f"No A-share news for {ticker} within {start_date}~{end_date} "
            f"(东方财富 returned {len(df)} recent items, all outside the window)."
        )

    rows.sort(key=lambda x: (x[0] or datetime.min), reverse=True)
    out = [f"## {ticker} 个股新闻（来源：东方财富 / akshare），{start_date} ~ {end_date}:\n"]
    for _, title, body, src, ts, link in rows:
        out.append(f"### {title}  ({ts}, 来源: {src})")
        if body:
            out.append(body[:500])
        if link:
            out.append(f"Link: {link}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Global / macro market news (no ticker)
# ---------------------------------------------------------------------------
def get_global_news_akshare(curr_date: str, look_back_days=None, limit=None) -> str:
    """Macro / market-wide CN news via 东方财富 全球财经快讯 (``stock_info_global_em``)."""
    ak = _ak()
    limit = int(limit) if limit else 15
    try:
        df = ak.stock_info_global_em()
    except Exception as e:
        return f"Error fetching A-share global news: {e}"

    if df is None or len(df) == 0:
        return f"No A-share global news found for {curr_date}."

    # Always enforce the analysis-date boundary. A near-now report is still a
    # point-in-time artifact and must not consume tomorrow's live-feed items.
    cutoff = None
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        cutoff = end_dt + timedelta(days=1)
    except ValueError:
        pass

    out, kept = [], 0
    for _, r in df.iterrows():
        if kept >= limit:
            break
        title = str(r.get("标题", "")).strip()
        summary = str(r.get("摘要", "")).strip()
        ts = str(r.get("发布时间", "")).strip()
        link = str(r.get("链接", "")).strip()
        pub = _parse_dt(ts)
        if pub is not None and cutoff is not None and pub >= cutoff:
            continue  # look-ahead safety
        block = f"### {title}  ({ts})"
        if summary:
            block += f"\n{summary[:400]}"
        if link:
            block += f"\nLink: {link}"
        out.append(block)
        kept += 1

    if not out:
        return f"No A-share global news at/under {curr_date}."
    return f"## 全球财经快讯（来源：东方财富 / akshare），截至 {curr_date}:\n\n" + "\n\n".join(out)


# ---------------------------------------------------------------------------
# Sentiment proxy (replaces StockTwits / Reddit for A-shares)
# ---------------------------------------------------------------------------
def _market_of(ticker: str) -> str:
    """Eastmoney market code for the fund-flow API: sh / sz / bj."""
    t = (ticker or "").strip().upper()
    if t.endswith((".SS", ".SH")):
        return "sh"
    if t.endswith(".SZ"):
        return "sz"
    if t.endswith(".BJ"):
        return "bj"
    code = to_ak_symbol(ticker)
    if code.startswith("6"):
        return "sh"
    if code.startswith(("8", "4", "92")):
        return "bj"
    return "sz"


def _fund_flow_block(ak, code: str, ticker: str) -> str:
    """主力/超大单 net inflow trend over the last ~5 trading days (smart money)."""
    try:
        df = _retry(lambda: ak.stock_individual_fund_flow(stock=code, market=_market_of(ticker)))
    except Exception as e:
        return f"个股资金流获取失败：{e}"
    if df is None or len(df) == 0:
        return "无个股资金流数据。"
    tail = df.tail(5)

    def yi(x):  # 元 -> 亿元
        try:
            return f"{float(x) / 1e8:+.2f}亿"
        except Exception:
            return str(x)

    lines = []
    main_sum = 0.0
    pos_days = 0
    for _, r in tail.iterrows():
        d = str(r.get("日期", ""))
        main = r.get("主力净流入-净额", 0)
        pct = r.get("主力净流入-净占比", "")
        try:
            main_f = float(main)
            main_sum += main_f
            if main_f > 0:
                pos_days += 1
        except Exception:
            pass
        lines.append(f"  - {d}: 主力 {yi(main)} ({pct}%)，涨跌幅 {r.get('涨跌幅','')}%")
    trend = "净流入" if main_sum > 0 else "净流出"
    head = (
        f"个股资金流（东方财富，近5个交易日）：主力合计 {yi(main_sum)}（{trend}），"
        f"其中 {pos_days}/5 日主力净流入。"
    )
    return head + "\n" + "\n".join(lines)


def _lhb_block(ak, code: str) -> str:
    """龙虎榜 recent activity — 游资/机构 seat participation, a hot-money signal."""
    latest = _latest_lhb_event_block(ak, code)
    try:
        df = _retry(lambda: ak.stock_lhb_stock_statistic_em(symbol="近一月"))
        row = df[df["代码"].astype(str).str.zfill(6) == code]
    except Exception as e:
        monthly = f"龙虎榜近一月汇总获取失败：{e}"
        return latest + "\n" + monthly if latest else monthly
    if not len(row):
        monthly = "近一个月未上龙虎榜（无异动席位信号）。"
        return latest + "\n" + monthly if latest else monthly
    r = row.iloc[0]

    def yi(k):
        try:
            return f"{float(r.get(k, 0)) / 1e8:+.2f}亿"
        except Exception:
            return str(r.get(k, "—"))
    monthly = (
        f"龙虎榜近一月汇总（东方财富，不等同于最新三日榜）：上榜 {r.get('上榜次数','—')} 次，"
        f"最近上榜日 {r.get('最近上榜日','—')}；龙虎榜净买额 {yi('龙虎榜净买额')}，"
        f"机构买入净额 {yi('机构买入净额')}（买方机构 {r.get('买方机构次数','—')} 次 / "
        f"卖方机构 {r.get('卖方机构次数','—')} 次）。频繁上榜=游资活跃，机构净买>0=机构介入。"
    )
    return latest + "\n" + monthly if latest else monthly


def _latest_lhb_event_block(ak, code: str) -> str:
    """Latest stock-specific dragon-tiger event, kept separate from monthly stats."""
    try:
        dates = _retry(lambda: ak.stock_lhb_stock_detail_date_em(symbol=code), tries=2)
        if dates is None or len(dates) == 0:
            return ""
        latest_date = str(dates.iloc[0].get("交易日", "")).replace("-", "")
        if not latest_date:
            return ""
        detail = _retry(lambda: ak.stock_lhb_detail_em(start_date=latest_date, end_date=latest_date), tries=2)
        row = detail[detail["代码"].astype(str).str.zfill(6) == code]
        if row is None or len(row) == 0:
            return ""
        r = row.iloc[0]
        buy = _retry(lambda: ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="买入"), tries=2)
        sell = _retry(lambda: ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="卖出"), tries=2)
    except Exception as e:
        return f"龙虎榜最新上榜明细获取失败：{e}"

    def yi_value(value) -> str:
        try:
            return f"{float(value) / 1e8:+.2f}亿"
        except Exception:
            return str(value)

    inst_buy = _sum_by_name(buy, "买入金额", "机构专用")
    inst_sell = _sum_by_name(sell, "卖出金额", "机构专用")
    inst_net = inst_buy - inst_sell
    reason = str(r.get("上榜原因", ""))
    reason = reason[:38] + "…" if len(reason) > 38 else reason
    return (
        f"龙虎榜最新上榜事件（东方财富，{str(r.get('上榜日', latest_date))}，与近一月汇总分开解读）："
        f"原因={reason}；龙虎榜净买额 {yi_value(r.get('龙虎榜净买额'))}，"
        f"买入额 {yi_value(r.get('龙虎榜买入额'))}，卖出额 {yi_value(r.get('龙虎榜卖出额'))}，"
        f"换手率 {r.get('换手率','—')}%。机构专用席位买入 {yi_value(inst_buy)}，"
        f"卖出 {yi_value(inst_sell)}，机构专用净额 {yi_value(inst_net)}。"
    )


def _sum_by_name(df: pd.DataFrame, amount_col: str, name_token: str) -> float:
    if df is None or len(df) == 0:
        return 0.0
    try:
        rows = df[df["交易营业部名称"].astype(str).str.contains(name_token, regex=False, na=False)]
        return float(pd.to_numeric(rows.get(amount_col), errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def _research_block(ak, code: str) -> str:
    """券商研报评级 + 盈利预测/目标 PE — the institutional/analyst view."""
    try:
        df = _retry(lambda: ak.stock_research_report_em(symbol=code))
    except Exception as e:
        return f"券商研报获取失败：{e}"
    if df is None or len(df) == 0:
        return "近期无券商研报覆盖。"
    df = df.head(8)
    ratings = df["东财评级"].value_counts().to_dict() if "东财评级" in df.columns else {}
    rating_str = "、".join(f"{k}×{v}" for k, v in ratings.items()) or "—"
    lines = [f"券商研报评级（东方财富，近期 {len(df)} 篇）：{rating_str}"]
    for _, r in df.head(4).iterrows():
        inst = r.get("机构", "")
        title = str(r.get("报告名称", ""))[:34]
        rating = r.get("东财评级", "")
        pe26 = r.get("2026-盈利预测-市盈率", "")
        lines.append(f"  - {inst}『{rating}』{title}… (2026E PE {pe26})")
    return "\n".join(lines)


def fetch_cn_sentiment(ticker: str) -> dict:
    """Build a richer A-share sentiment / capital-flow / institutional proxy.

    Returns markdown blocks the sentiment analyst injects in place of the
    (StockTwits, Reddit) slots that are empty for A-shares:

      - ``quant_block``: 千股千评 量化情绪 (综合得分/关注指数/人气排名/机构参与度/主力成本)
      - ``capital_block``: 个股资金流(主力/超大单) + 龙虎榜(游资/机构席位) — smart-money tape
      - ``rating_block``: 券商研报评级 + 盈利预测/目标 PE — the analyst/institutional view
      - ``buzz_block``:  recent 个股新闻 headline stream
    """
    code = to_ak_symbol(ticker)
    ak = _ak()

    # --- 千股千评 quantitative sentiment ---
    quant_lines = []
    try:
        df = ak.stock_comment_em()
        row = df[df["代码"].astype(str).str.zfill(6) == code]
        if len(row):
            r = row.iloc[0]
            def g(k):
                try:
                    return r[k]
                except Exception:
                    return "—"
            quant_lines = [
                f"个股：{g('名称')} ({code})  最新价 {g('最新价')}  涨跌幅 {g('涨跌幅')}%",
                f"综合得分(0-100，越高越偏多)：{g('综合得分')}",
                f"散户关注指数(越高越受关注)：{g('关注指数')}",
                f"东财人气排名：{g('目前排名')}  （排名变动 {g('上升')}，正=升温/负=降温）",
                f"机构参与度：{g('机构参与度')}",
                f"主力成本：{g('主力成本')}  换手率 {g('换手率')}%  市盈率 {g('市盈率')}",
                f"交易日：{g('交易日')}",
            ]
    except Exception as e:
        quant_lines = [f"千股千评获取失败：{e}"]

    if quant_lines:
        quant_block = (
            "东方财富『千股千评』量化情绪（A股散户关注度 + 机构参与度，非英文社媒）：\n"
            + "\n".join(f"- {x}" for x in quant_lines)
            + "\n\n解读要点：综合得分>60 偏多、<40 偏空；关注指数与人气排名上升=散户情绪升温；"
            "机构参与度高+主力成本低于现价=主力浮盈、筹码稳定。"
        )
    else:
        quant_block = f"未在千股千评中找到 {code} 的量化情绪数据。"

    # --- recent headline buzz ---
    try:
        ndf = ak.stock_news_em(symbol=code)
        items = []
        for _, r in ndf.head(12).iterrows():
            t = str(r.get("新闻标题", "")).strip()
            ts = str(r.get("发布时间", "")).strip()
            src = str(r.get("文章来源", "")).strip()
            if t:
                items.append(f"- [{ts}] {t}  ({src})")
        buzz_block = (
            "近期个股新闻/舆情热点（来源：东方财富 / akshare）：\n" + "\n".join(items)
            if items else "近期无个股新闻。"
        )
    except Exception as e:
        buzz_block = f"个股新闻流获取失败：{e}"

    # --- capital-flow + dragon-tiger (smart money) ---
    capital_block = _fund_flow_block(ak, code, ticker) + "\n\n" + _lhb_block(ak, code)

    # --- broker research ratings (institutional view) ---
    rating_block = _research_block(ak, code)

    # --- 雪球 retail-discussion crowding (Xueqiu is a channel; this is a
    #     sentiment signal, so it lives with the Sentiment analyst) ---
    xueqiu_block = xueqiu_discussion_block(ticker)

    return {
        "quant_block": quant_block,
        "capital_block": capital_block,
        "rating_block": rating_block,
        "xueqiu_block": xueqiu_block,
        "buzz_block": buzz_block,
    }


# ---------------------------------------------------------------------------
# Policy & retail-discussion (雪球) — feeds the dedicated Policy Analyst node
# ---------------------------------------------------------------------------
def _xq_code(ticker: str) -> str:
    """``300811.SZ`` -> ``SZ300811`` (Xueqiu hot-ranking code format)."""
    code = to_ak_symbol(ticker)
    mkt = _market_of(ticker).upper()  # sh/sz/bj -> SH/SZ/BJ
    return f"{mkt}{code}"


_POLICY_KW = (
    "政策", "监管", "证监会", "国常会", "发改委", "部委", "补贴", "规划", "国务院",
    "央行", "财政", "降准", "降息", "关税", "出口管制", "国产替代", "信创", "新质生产力",
    "工信部", "招标", "中标", "立项", "纳入", "白名单", "标准", "试点",
)


def xueqiu_discussion_block(ticker: str) -> str:
    """雪球 retail-discussion heat — a RETAIL-CROWDING / SENTIMENT signal.

    Xueqiu is a data *channel*; its discussion-ranking content is a retail
    sentiment signal, so this feeds the Sentiment analyst (not Policy). Returns
    the stock's rank on the 最热门讨论榜 + the market-wide hottest names (theme
    rotation). Empty string for non-A-shares.
    """
    if not is_a_share(ticker):
        return ""
    ak = _ak()
    xq = _xq_code(ticker)
    lines = []
    try:
        tw = _retry(lambda: ak.stock_hot_tweet_xq(symbol="最热门"), tries=3)
        tw = tw.reset_index(drop=True)
        hit = tw[tw["股票代码"].astype(str).str.upper() == xq]
        total = len(tw)
        if len(hit):
            rank = int(hit.index[0]) + 1
            foll = hit.iloc[0].get("关注", "—")
            lines.append(
                f"本股雪球讨论热度：在『最热门讨论榜』中排名第 {rank}/{total}，"
                f"关注度 {foll}。排名越靠前=散户讨论越火热（高位需警惕过热/拥挤）。"
            )
        else:
            lines.append(
                f"本股未进入雪球『最热门讨论榜』前列（共 {total} 只），"
                "散户讨论热度一般（无明显题材炒作过热/拥挤信号）。"
            )
        top = tw.head(8)
        hot_names = "、".join(
            f"{r['股票简称']}({int(r['关注']) if str(r.get('关注','')).replace('.','').isdigit() else r.get('关注','')})"
            for _, r in top.iterrows()
        )
        lines.append(f"当前雪球全市场最热议个股Top8：{hot_names}（反映散户当下在追什么题材/主题）。")
    except Exception as e:
        lines.append(f"雪球讨论榜获取失败：{e}")
    return "雪球（散户社区）讨论热度 / 题材拥挤度：\n" + "\n".join(f"- {x}" for x in lines)


def fetch_cn_policy(ticker: str) -> dict:
    """Data for the Policy analyst (A-shares only) — PURE policy/industrial.

    Returns ``policy_block``: 财新内容精选 (macro/policy) + policy-keyword-filtered
    company news (订单/招标/补贴/监管/国产替代 …). Retail discussion is NOT here —
    that's a sentiment signal handled by the Sentiment analyst (Xueqiu is a
    channel, not a policy dimension).
    """
    ak = _ak()
    code = to_ak_symbol(ticker)

    # --- policy / macro news (财新精选) + company policy-relevant news ---
    pol_lines = []
    try:
        cx = _retry(lambda: ak.stock_news_main_cx(), tries=3)
        for _, r in cx.head(10).iterrows():
            tag = str(r.get("tag", "")).strip()
            summ = str(r.get("summary", "")).strip()
            if summ:
                pol_lines.append(f"- [{tag}] {summ[:80]}")
    except Exception as e:
        pol_lines.append(f"财新政策/宏观精选获取失败：{e}")
    macro_block = "宏观与政策快讯（财新内容精选）：\n" + "\n".join(pol_lines[:10])

    company_pol = []
    try:
        ndf = _retry(lambda: ak.stock_news_em(symbol=code), tries=3)
        for _, r in ndf.iterrows():
            title = str(r.get("新闻标题", "")).strip()
            ts = str(r.get("发布时间", "")).strip()
            if title and any(k in title or k in str(r.get("新闻内容", "")) for k in _POLICY_KW):
                company_pol.append(f"- [{ts}] {title}")
            if len(company_pol) >= 6:
                break
    except Exception as e:
        company_pol.append(f"个股政策相关新闻获取失败：{e}")
    company_block = (
        "本股政策/招标/产业相关事件：\n" + "\n".join(company_pol)
        if company_pol else "本股近期无明显政策/招标/产业政策相关新闻。"
    )

    policy_block = macro_block + "\n\n" + company_block
    return {"policy_block": policy_block}


# ---------------------------------------------------------------------------
# Segment breakdown (主营构成) — per-product / per-region revenue & gross margin
# ---------------------------------------------------------------------------
def get_segment_breakdown(ticker: str) -> str:
    """Per-product / per-region revenue split + gross margin (东财 主营构成).

    Returns a markdown block for the fundamentals analyst. This is the key to
    distinguishing MIX-driven blended-margin moves (a new low-margin line ramping)
    from genuine PRICING/competition pressure — a distinction the line-level
    statements alone can't show. Returns a short note for non-A-shares / no data.
    """
    if not is_a_share(ticker):
        return ""
    ak = _ak()
    xq = _xq_code(ticker)
    try:
        df = _retry(lambda: ak.stock_zygc_em(symbol=xq), tries=4)
    except Exception as e:
        return f"主营构成（分产品/地区营收与毛利率）获取失败：{e}"
    if df is None or len(df) == 0:
        return "无主营构成数据。"

    dates = sorted(df["报告日期"].astype(str).unique(), reverse=True)
    latest = dates[0]
    # YoY comparison: same MM-DD one year earlier (annual vs annual / H1 vs H1),
    # NOT the immediately prior period — a 年报(12-31) vs 半年报(6-30) margin delta
    # is meaningless because the periods aren't comparable.
    prev = None
    if len(latest) >= 10:
        yoy = f"{int(latest[:4]) - 1}{latest[4:]}"
        prev = yoy if yoy in dates else None

    def pct(x):
        try:
            return f"{float(x) * 100:.1f}%"
        except Exception:
            return "—"

    def yi(x):
        try:
            return f"{float(x) / 1e8:.2f}亿"
        except Exception:
            return str(x)

    out = [f"主营构成（来源：东方财富，最新报告期 {latest}）——用于判断毛利率变化是「结构稀释」还是「价格战」："]
    for cls in ("按产品分类", "按行业分类", "按地区分类"):
        seg = df[(df["报告日期"].astype(str) == latest) & (df["分类类型"] == cls)]
        if not len(seg):
            continue
        out.append(f"\n**{cls}**（营收占比 | 毛利率）：")
        for _, r in seg.iterrows():
            name = r.get("主营构成", "")
            rev = r.get("主营收入", 0)
            share = r.get("收入比例", 0)
            gm = r.get("毛利率", "")
            line = f"- {name}：营收 {yi(rev)}（占比 {pct(share)}），毛利率 {pct(gm)}"
            # YoY gross-margin delta for the same segment (same period prior year).
            if prev is not None:
                pseg = df[(df["报告日期"].astype(str) == prev) & (df["分类类型"] == cls)]
                pm = pseg[pseg["主营构成"] == name]
                if len(pm):
                    try:
                        d = (float(gm) - float(pm.iloc[0]["毛利率"])) * 100
                        line += f"（同比 {prev}: {d:+.1f}pct）"
                    except Exception:
                        pass
            out.append(line)
    out.append(
        "\n分析提示：若综合毛利率下滑主要由「低毛利新业务放量、占比上升」驱动（结构稀释），"
        "而各分部自身毛利率稳定，则属于扩张代价、非护城河恶化；若是各分部毛利率普遍下滑，"
        "才是真正的价格战/成本失控信号。"
    )
    return "\n".join(out)
