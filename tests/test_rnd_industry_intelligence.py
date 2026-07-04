import json

from tradingagents.rnd.industry_intelligence import (
    seed_industry_intelligence,
    validate_industry_intelligence,
)


def test_seed_marks_single_blogger_rotation_as_watch_only():
    brief = seed_industry_intelligence()
    signal = brief["signals"][0]

    assert signal["status"] == "watch"
    assert signal["confidence"] < 50
    assert signal["nature"] == "style_rotation"
    assert all(source["tier"] == "D" for source in signal["sources"])
    assert len(signal["checks"]) >= 3
    assert brief["items"][0]["author"] == "风动幡动还是心动"
    assert brief["items"][0]["system_view"]


def test_validation_merges_new_source_registry_into_old_cache():
    payload = seed_industry_intelligence()
    payload["source_watchlist"] = [payload["source_watchlist"][0]]

    normalized = validate_industry_intelligence(payload)
    names = {source["name"] for source in normalized["source_watchlist"]}

    assert "财联社" in names
    assert "第一财经" in names
    assert "雪球讨论热度" in names


def test_validation_rejects_unclassified_source():
    payload = json.loads(json.dumps(seed_industry_intelligence()))
    payload["signals"][0]["sources"][0]["tier"] = "Z"

    try:
        validate_industry_intelligence(payload)
    except ValueError as exc:
        assert "source tier" in str(exc)
    else:
        raise AssertionError("invalid source tier was accepted")
