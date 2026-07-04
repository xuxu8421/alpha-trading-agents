from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from tradingagents.dataflows.akshare_cn import get_ohlcv_akshare_frame, is_a_share


def latest_a_share_trade_date(ticker: str, today: date | None = None) -> str:
    today = today or date.today()
    start = today - timedelta(days=14)
    df = get_ohlcv_akshare_frame(ticker, start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    if df.empty:
        return previous_weekday(today).strftime("%Y-%m-%d")
    return pd.to_datetime(df["Date"]).max().strftime("%Y-%m-%d")


def previous_weekday(day: date | None = None) -> date:
    day = day or date.today()
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day - timedelta(days=2)
    return day


def evaluate_price_path(ticker: str, report_date: str, horizon: int) -> dict:
    checked_at = datetime.now().isoformat(timespec="seconds")
    if not is_a_share(ticker):
        return {"status": "unsupported", "checked_at": checked_at}

    report_day = datetime.strptime(report_date, "%Y-%m-%d").date()
    end_day = date.today()
    if end_day <= report_day:
        return {"status": "pending", "checked_at": checked_at}

    start = report_day - timedelta(days=10)
    df = get_ohlcv_akshare_frame(ticker, start.strftime("%Y-%m-%d"), end_day.strftime("%Y-%m-%d"))
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    entry_rows = df[df["Date"] <= report_day]
    future_rows = df[df["Date"] > report_day]
    if entry_rows.empty or len(future_rows) < horizon:
        return {"status": "pending", "checked_at": checked_at}

    entry = entry_rows.iloc[-1]
    window = future_rows.iloc[:horizon]
    exit_row = window.iloc[-1]
    entry_close = float(entry["Close"])
    exit_close = float(exit_row["Close"])
    closes = window["Close"].astype(float)
    return_pct = exit_close / entry_close - 1
    max_favorable_pct = closes.max() / entry_close - 1
    max_adverse_pct = closes.min() / entry_close - 1
    benchmark_return_pct = _benchmark_return(report_day, horizon)
    relative_return_pct = (
        return_pct - benchmark_return_pct if benchmark_return_pct is not None else None
    )

    return {
        "status": "ready",
        "entry_date": entry["Date"].isoformat(),
        "exit_date": exit_row["Date"].isoformat(),
        "entry_close": entry_close,
        "exit_close": exit_close,
        "return_pct": return_pct,
        "max_favorable_pct": max_favorable_pct,
        "max_adverse_pct": max_adverse_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "relative_return_pct": relative_return_pct,
        "checked_at": checked_at,
    }


def _benchmark_return(report_day: date, horizon: int) -> float | None:
    try:
        import akshare as ak

        start = (report_day - timedelta(days=10)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")
        df = ak.stock_zh_index_daily_em(symbol="sh000300")
        if df is None or df.empty:
            return None
        date_col = "date" if "date" in df.columns else "日期"
        close_col = "close" if "close" in df.columns else "收盘"
        out = df[[date_col, close_col]].copy()
        out[date_col] = pd.to_datetime(out[date_col]).dt.date
        out[close_col] = pd.to_numeric(out[close_col], errors="coerce")
        out = out[(out[date_col] >= datetime.strptime(start, "%Y%m%d").date()) & (out[date_col] <= datetime.strptime(end, "%Y%m%d").date())]
        entry_rows = out[out[date_col] <= report_day]
        future_rows = out[out[date_col] > report_day]
        if entry_rows.empty or len(future_rows) < horizon:
            return None
        entry_close = float(entry_rows.iloc[-1][close_col])
        exit_close = float(future_rows.iloc[horizon - 1][close_col])
        return exit_close / entry_close - 1
    except Exception:
        return None

