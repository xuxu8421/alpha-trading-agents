from tradingagents.rnd.config import STOCK_UNIVERSE
from tradingagents.rnd.industry_chain import build_industry_chain_brief


def test_industry_chain_covers_tracked_universe():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)

    assert len(brief["chains"]) == len(STOCK_UNIVERSE)
    assert {row["ticker"] for row in brief["chains"]} == {row["ticker"] for row in STOCK_UNIVERSE}


def test_industry_chain_uses_first_principle_structure():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)

    assert len(brief["tracks"]) == 10
    for track in brief["tracks"]:
        assert track["summary"]
        assert set(track["layers"]) == {"upstream", "bottlenecks", "integration", "demand"}
        assert all(track["layers"][key] for key in track["layers"])
        assert track["watch"]

    for chain in brief["chains"]:
        assert chain["first_principle"]
        assert chain["watch_signals"]
        assert chain["questions"]

    unmapped = next(row for row in brief["chains"] if row["ticker"] == "003022.SZ")
    assert unmapped["map"] == []


def test_industry_chain_keeps_project_references():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)
    names = {row["name"] for row in brief["references"]}

    assert "AICARDMAP" in names
    assert "stock-industry-chain" in names
    assert "ChainKnowledgeGraph" in names


def test_industry_chain_has_company_index_and_evidence():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)
    statuses = {row["status"] for row in brief["evidence_legend"]}

    assert {"confirmed", "business_fit", "needs_review"} <= statuses
    assert len(brief["company_index"]) == len(STOCK_UNIVERSE)
    assert sum(bool(row["links"]) for row in brief["company_index"]) == len(STOCK_UNIVERSE) - 1
    assert brief["radar"]


def test_industry_chain_recreates_full_research_information_architecture():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)

    assert len(brief["public_companies"]) >= 40
    assert len(brief["technology_routes"]) >= 5
    assert len(brief["learning_path_cards"]) >= 3
    assert len(brief["update_log"]) >= 3
    assert {row["track"] for row in brief["radar"]} == {row["id"] for row in brief["tracks"]}


def test_professional_audit_does_not_force_unrelated_companies_into_ai_hardware():
    brief = build_industry_chain_brief(STOCK_UNIVERSE)
    by_ticker = {row["ticker"]: row for row in brief["company_index"]}

    assert {link["track"] for link in by_ticker["300496.SZ"]["links"]} >= {"software_apps"}
    assert {link["track"] for link in by_ticker["603078.SS"]["links"]} >= {"materials"}
    assert by_ticker["003022.SZ"]["links"] == []
