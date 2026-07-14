import sqlite3

from tradingagents.rnd.signals import extract_thesis_snapshot
from tradingagents.rnd.storage import init_db, upsert_thesis_snapshot
from tradingagents.rnd.thesis_review import build_weekly_thesis_review


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_thesis_snapshot_extracts_three_levels_and_expectation():
    snapshot = extract_thesis_snapshot(
        {
            "company_of_interest": "300496",
            "trade_date": "2026-07-10",
            "macro_report": "宏观流动性中性。",
            "industry_report": "端侧AI进入验证期。",
            "financial_report": "经营现金流弱于利润。",
            "expectation_report": "基准情景等待订单；若回款恶化则失效。",
            "final_report": '<!--META {"action":"持有","rating":"持有"}-->',
        }
    )

    assert snapshot["macro_claim"] == "宏观流动性中性。"
    assert "端侧AI" in snapshot["industry_claim"]
    assert "现金流" in snapshot["company_claim"]
    assert snapshot["action"] == "hold"
    assert snapshot["invalidations"]


def test_weekly_review_attributes_only_supported_errors_and_creates_task():
    conn = _conn()
    conn.execute(
        """INSERT INTO runs
        (id,ticker,name,report_date,created_at,prompt_version,action,final_report_len,log_path,degradation_count)
        VALUES (1,'300496.SZ','中科创达','2026-07-03','2026-07-03','v2','buy',100,'x',0)"""
    )
    snapshot_id = upsert_thesis_snapshot(
        conn,
        1,
        {
            "ticker": "300496.SZ",
            "report_date": "2026-07-03",
            "macro_claim": "流动性改善",
            "industry_claim": "软件强于硬件",
            "company_claim": "订单改善",
            "expectation_claim": "预期上修",
            "action": "buy",
            "horizon": "T+5",
            "confidence": 0.7,
            "catalysts": [],
            "invalidations": ["订单不及预期"],
        },
    )
    conn.execute(
        """INSERT INTO outcomes
        (run_id,horizon,status,return_pct,relative_return_pct,checked_at)
        VALUES (1,5,'ready',-9.0,-7.0,'2026-07-10')"""
    )
    conn.commit()

    review = build_weekly_thesis_review(conn, "2026-07-10")
    row = next(item for item in review["reviews"] if item["snapshot_id"] == snapshot_id)

    assert row["expectation_verdict"] == "failed"
    assert row["timing_verdict"] == "failed"
    assert row["macro_verdict"] == "unverified"
    assert review["tasks_created"]

