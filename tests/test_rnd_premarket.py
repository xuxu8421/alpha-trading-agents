from datetime import date

from tradingagents.rnd.premarket import (
    _build_stance,
    _next_weekday,
    _parse_tencent_quotes,
    _select_headlines,
)


def test_next_weekday_handles_weekend_and_after_close():
    assert _next_weekday(date(2026, 6, 28), 10) == date(2026, 6, 29)
    assert _next_weekday(date(2026, 6, 26), 16) == date(2026, 6, 29)
    assert _next_weekday(date(2026, 6, 29), 9) == date(2026, 6, 29)


def test_parse_tencent_quotes_supports_compact_and_full_shapes():
    raw = (
        'v_s_sh000001="1~上证指数~000001~4027.26~-93.02~-2.26~";\n'
        'v_usIXIC="200~纳斯达克~.IXIC~25297.62~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~2026-06-26 17:15:59~-60.98~-0.24~";'
    )

    rows = _parse_tencent_quotes(raw)

    assert rows[0]["name"] == "上证指数"
    assert rows[0]["change_pct"] == -2.26
    assert rows[1]["name"] == "纳斯达克"
    assert rows[1]["quote_time"] == "2026-06-26 17:15:59"


def test_headline_ranking_prioritizes_watchlist_and_policy_terms():
    rows = [
        {"title": "普通公司动态", "summary": "", "published_at": "3"},
        {"title": "央行发布重要政策", "summary": "", "published_at": "2"},
        {"title": "中科创达发布新产品", "summary": "", "published_at": "1"},
    ]
    selected = _select_headlines(rows, [{"name": "中科创达"}])

    assert selected[0]["title"] == "中科创达发布新产品"
    assert selected[1]["title"] == "央行发布重要政策"


def test_stance_is_cautious_when_external_markets_are_weak():
    stance = _build_stance(
        [
            {"name": "纳斯达克", "change_pct": -1.4},
            {"name": "标普500", "change_pct": -1.0},
        ],
        [],
    )

    assert stance["level"] == "谨慎"
