from tradingagents.agents.analysts.industry_analyst import build_industry_evidence


def test_industry_evidence_selects_company_chain_and_current_regime():
    evidence = build_industry_evidence("300496")

    assert evidence["company"]["name"] == "中科创达"
    assert evidence["company"]["anchor"] == "AI 终端操作系统与智能汽车软件"
    assert evidence["industry_regime"]["label"]
    assert any(link["track"] == "software_apps" for link in evidence["company"]["links"])


def test_industry_evidence_degrades_explicitly_for_untracked_company():
    evidence = build_industry_evidence("AAPL")

    assert evidence["company"]["tracked"] is False
    assert evidence["limitations"]
