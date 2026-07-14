import sqlite3
from unittest.mock import patch

from tradingagents.rnd.market_pulse import (
    _market_phase,
    _normalize_board,
    _rank_boards,
    build_market_pulse,
    latest_market_pulse,
)
from tradingagents.rnd.storage import init_db


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_market_pulse_classifies_board_stages():
    strong = _normalize_board(
        {
            "f12": "BK0001",
            "f14": "人形机器人",
            "f3": 2.2,
            "f6": 80_000_000_000,
            "f7": 4.0,
            "f8": 3.0,
            "f62": 3_000_000_000,
            "f66": 2_000_000_000,
            "f104": 80,
            "f105": 20,
            "f128": "样本龙头",
            "f140": "000001",
        },
        "concept",
    )
    crowded = _normalize_board(
        {
            "f12": "BK0002",
            "f14": "高位题材",
            "f3": 7.0,
            "f6": 60_000_000_000,
            "f7": 10.0,
            "f8": 8.0,
            "f62": 500_000_000,
            "f66": 300_000_000,
            "f104": 45,
            "f105": 5,
        },
        "concept",
    )

    assert strong["stage"] in {"主升", "启动预警"}
    assert crowded["stage"] == "高位拥挤"


def test_market_phase_detects_positive_breadth():
    rows = [
        _normalize_board(
            {
                "f12": f"BK{i:04d}",
                "f14": f"板块{i}",
                "f3": 2.0,
                "f6": 20_000_000_000,
                "f7": 4.0,
                "f8": 3.0,
                "f62": 800_000_000,
                "f104": 60,
                "f105": 20,
            },
            "industry",
        )
        for i in range(12)
    ]

    phase = _market_phase(rows)

    assert phase["score"] > 60
    assert phase["phase"] in {"主线强化", "弱修复", "退潮防守", "主线分歧", "结构轮动"}


def test_rank_boards_returns_starter_candidates():
    rows = [
        _normalize_board(
            {
                "f12": "BK1001",
                "f14": "启动板块",
                "f3": 1.5,
                "f6": 30_000_000_000,
                "f7": 3.0,
                "f8": 2.5,
                "f62": 1_500_000_000,
                "f104": 50,
                "f105": 25,
            },
            "industry",
        )
    ]

    ranked = _rank_boards(rows, "starter")

    assert ranked
    assert ranked[0]["name"] == "启动板块"
    assert "rank_score" in ranked[0]


def test_latest_market_pulse_reads_persisted_payload():
    conn = _conn()

    def fake_fetch(kind):
        return [
            _normalize_board(
                {
                    "f12": "BK2001",
                    "f14": "测试板块",
                    "f3": 1.5,
                    "f6": 30_000_000_000,
                    "f7": 3.0,
                    "f8": 2.5,
                    "f62": 1_500_000_000,
                    "f104": 50,
                    "f105": 25,
                },
                kind,
            )
        ]

    with patch("tradingagents.rnd.market_pulse._fetch_board_rows", fake_fetch):
        first = build_market_pulse(conn, "2026-07-02")
    latest = latest_market_pulse(conn, "2026-07-02")

    assert latest["trade_date"] == "2026-07-02"
    assert latest["phase"] == first["phase"]
