import sqlite3

from tradingagents.rnd.daily_candidates import (
    DEFAULT_WEIGHTS,
    SEED_UNIVERSE,
    Quote,
    _market_phase,
    _score_candidate,
    _select_dynamic_universe,
    latest_daily_candidates,
    persist_daily_candidates,
)
from tradingagents.rnd.storage import init_db


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_market_phase_detects_hot_and_degraded():
    hot = [
        Quote("000001.SZ", "A", 10, 6.0, 8.0, 10, 2.0, 6.0, "test"),
        Quote("000002.SZ", "B", 10, 1.0, 2.0, 3, 1.0, 2.0, "test"),
        Quote("000003.SZ", "C", 10, 5.2, 5.5, 6, 1.5, 5.0, "test"),
        Quote("000004.SZ", "D", 10, -0.5, 1.0, 2, 0.9, 2.0, "test"),
    ]
    assert _market_phase(hot)["phase"] == "sector_hot"
    degraded = [Quote("000001.SZ", "A", None, None, None, None, None, None, "fallback", "x")]
    assert _market_phase(degraded)["phase"] == "data_degraded"


def test_score_candidate_flags_limit_chase_risk():
    item = SEED_UNIVERSE[0]
    quote = Quote(item["ticker"], item["name"], 10, 9.8, 9.0, 12, 2.1, 10.0, "test")
    row = _score_candidate(
        item,
        quote,
        {"phase": "sector_hot", "avg_change_pct": 2.0, "description": "test"},
        DEFAULT_WEIGHTS,
    )
    codes = {flag["code"] for flag in row["risk_flags"]}
    assert "limit_chase_risk" in codes
    assert row["bucket"] == "风险观察"


def test_persist_and_latest_daily_candidates_round_trip():
    conn = _conn()
    item = SEED_UNIVERSE[0]
    quote = Quote(item["ticker"], item["name"], 10, 2.5, 4.0, 8, 1.4, 5.0, "test")
    market = {"phase": "mixed", "description": "结构行情"}
    row = _score_candidate(item, quote, market, DEFAULT_WEIGHTS)
    persist_daily_candidates(conn, "2026-07-01", [row], market, DEFAULT_WEIGHTS)
    latest = latest_daily_candidates(conn)
    assert latest["trade_date"] == "2026-07-01"
    assert latest["rows"][0]["ticker"] == item["ticker"]
    assert latest["rows"][0]["quote"]["source"] == "test"


def test_persist_daily_candidates_replaces_same_day_batch():
    conn = _conn()
    first = SEED_UNIVERSE[0]
    second = SEED_UNIVERSE[1]
    market = {"phase": "mixed", "description": "old"}
    first_row = _score_candidate(
        first,
        Quote(first["ticker"], first["name"], 10, 2.0, 1.0, 1, 1.0, 2.0, "old"),
        market,
        DEFAULT_WEIGHTS,
    )
    persist_daily_candidates(conn, "2026-07-02", [first_row], market, DEFAULT_WEIGHTS)

    new_market = {"phase": "risk_off", "description": "new", "universe_source": "Eastmoney"}
    second_row = _score_candidate(
        second,
        Quote(second["ticker"], second["name"], 20, -1.0, 2.0, 3, 1.1, 2.0, "new"),
        new_market,
        DEFAULT_WEIGHTS,
    )
    persist_daily_candidates(conn, "2026-07-02", [second_row], new_market, DEFAULT_WEIGHTS)

    rows = conn.execute(
        "SELECT rank, ticker, quote_snapshot, market_snapshot FROM daily_candidates WHERE trade_date=?",
        ("2026-07-02",),
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["rank"] == 1
    assert rows[0]["ticker"] == second["ticker"]
    latest = latest_daily_candidates(conn, "2026-07-02")
    assert latest["rows"][0]["quote"]["source"] == "new"


def test_market_wide_universe_does_not_boost_tracked_pool_names():
    rows = [
        {"f12": "300496", "f14": "中科创达", "f2": 50, "f3": 2, "f6": 200_000_000, "f7": 3, "f8": 2, "f9": 50, "f10": 1.2, "f20": 30_000_000_000, "f62": 1_000_000, "f100": "软件开发"},
        {"f12": "600000", "f14": "市场公司", "f2": 10, "f3": 2, "f6": 900_000_000, "f7": 3, "f8": 2, "f9": 20, "f10": 1.2, "f20": 100_000_000_000, "f62": 5_000_000, "f100": "银行"},
    ]

    selected = _select_dynamic_universe(rows, 2)

    assert [row["name"] for row in selected] == ["市场公司", "中科创达"]
    assert all(row["universe_origin"] == "market_wide_scan" for row in selected)
