from datetime import datetime

from tradingagents.rnd.call_auction import (
    DEFAULT_RULE_WEIGHTS,
    REFERENCES,
    TIME_WINDOWS,
    _predict_market_from_snapshots,
    _score_prediction,
    _should_refresh_today_auction,
    _stock_feature,
)


def test_call_auction_brief_has_core_market_windows():
    windows = {row["time"]: row for row in TIME_WINDOWS}
    reference_names = {row["name"] for row in REFERENCES}

    assert "09:15-09:20" in windows
    assert "09:20-09:25" in windows
    assert "09:25" in windows
    assert "可撤单" in windows["09:15-09:20"]["label"]
    assert "不可撤单" in windows["09:20-09:25"]["label"]
    assert {"eltdx", "TDXPystock"} <= reference_names


def test_predict_market_from_auction_snapshots_detects_strength():
    market = [
        {"symbol": "sh000001", "name": "上证指数", "open_gap_pct": 0.5, "from_open_pct": 0.3, "current_change_pct": 0.8},
        {"symbol": "sz399001", "name": "深证成指", "open_gap_pct": 0.7, "from_open_pct": 0.4, "current_change_pct": 1.1},
        {"symbol": "sz399006", "name": "创业板指", "open_gap_pct": 0.6, "from_open_pct": 0.2, "current_change_pct": 0.9},
    ]
    stocks = [
        {"open_gap_pct": 3.0, "current_change_pct": 4.0},
        {"open_gap_pct": 1.0, "current_change_pct": 2.4},
        {"open_gap_pct": -0.2, "current_change_pct": 0.1},
    ]

    prediction = _predict_market_from_snapshots(market, stocks, DEFAULT_RULE_WEIGHTS)

    assert prediction["direction"] == "up"
    assert prediction["score"] > 56
    assert prediction["rule_contributions"]


def test_stock_feature_marks_crowded_and_follow_through():
    row = {
        "ticker": "300496.SZ",
        "name": "中科创达",
        "open_gap_pct": 5.2,
        "from_open_pct": 1.4,
        "current_change_pct": 7.0,
        "amount_yi": 9.0,
    }
    feature = _stock_feature(row)

    assert "高开强势" in feature["features"]
    assert "开盘继续走强" in feature["features"]
    assert "成交活跃" in feature["features"]


def test_score_prediction_flags_direction_error():
    prediction = {"direction": "up", "stance": "偏强"}
    market = [{"symbol": "sh000001", "current_change_pct": -1.2, "from_open_pct": -1.0}]

    outcome = _score_prediction(prediction, market)

    assert outcome["status"] == "ready"
    assert "direction_error" in outcome["error_tags"]


def test_latest_auction_refresh_window_starts_after_open_call():
    assert not _should_refresh_today_auction(datetime(2026, 7, 2, 9, 24))
    assert _should_refresh_today_auction(datetime(2026, 7, 2, 9, 25))
    assert not _should_refresh_today_auction(datetime(2026, 7, 4, 10, 0))
