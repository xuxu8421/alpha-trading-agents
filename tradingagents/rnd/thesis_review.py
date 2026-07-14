"""Friday hypothesis review: prediction -> actual -> attribution -> iteration."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


def build_weekly_thesis_review(conn, trade_date: str | None = None) -> dict[str, Any]:
    review_date = trade_date or date.today().isoformat()
    snapshots = list(
        conn.execute(
            """SELECT ts.*, r.degradation_count
            FROM thesis_snapshots ts JOIN runs r ON r.id=ts.run_id
            ORDER BY ts.report_date DESC, ts.ticker"""
        )
    )
    reviews = []
    tasks = []
    for snapshot in snapshots:
        outcome = conn.execute(
            """SELECT * FROM outcomes WHERE run_id=? AND horizon=5
            ORDER BY checked_at DESC LIMIT 1""",
            (snapshot["run_id"],),
        ).fetchone()
        row = _attribute(snapshot, outcome, review_date)
        _upsert_review(conn, row)
        reviews.append(row)
        if row["status"] == "reviewed" and (
            row["expectation_verdict"] == "failed" or row["timing_verdict"] == "failed"
        ):
            task = _create_task(conn, snapshot, row)
            if task:
                tasks.append(task)
    conn.commit()
    return {
        "role": "Friday Thesis Review Agent",
        "review_date": review_date,
        "status": "ready" if any(r["status"] == "reviewed" for r in reviews) else "pending",
        "summary": _summary(reviews),
        "reviews": reviews,
        "tasks_created": tasks,
    }


def _attribute(snapshot, outcome, review_date: str) -> dict[str, Any]:
    ready = outcome is not None and outcome["status"] == "ready"
    ret = float(outcome["return_pct"] or 0) if ready else None
    relative = float(outcome["relative_return_pct"] or 0) if ready else None
    action = snapshot["action"]
    directional = ret if action == "buy" else (-ret if action == "sell" else None)
    expectation_failed = ready and directional is not None and directional <= -5
    timing_failed = ready and relative is not None and relative <= -5
    data_failed = int(snapshot["degradation_count"] or 0) > 0

    # Price outcomes cannot prove which causal layer was wrong. These stay
    # unverified until a matching macro/industry/company KPI is ingested.
    causal = "unverified" if ready else "pending"
    return {
        "snapshot_id": int(snapshot["id"]),
        "review_date": review_date,
        "status": "reviewed" if ready else "pending",
        "macro_verdict": causal,
        "industry_verdict": causal,
        "company_verdict": causal,
        "expectation_verdict": "failed" if expectation_failed else ("supported" if ready else "pending"),
        "timing_verdict": "failed" if timing_failed else ("supported" if ready else "pending"),
        "data_verdict": "failed" if data_failed else "supported",
        "attribution": {
            "outcome_error": expectation_failed,
            "thesis_error": "unverified",
            "industry_error": "unverified",
            "macro_error": "unverified",
            "timing_error": timing_failed,
            "data_error": data_failed,
        },
        "evidence": {
            "return_pct": ret,
            "relative_return_pct": relative,
            "horizon": 5,
            "invalidations": json.loads(snapshot["invalidations"] or "[]"),
            "note": "价格结果只支持方向/时点归因，不能单独证明宏观、行业或公司因果层出错。",
        },
    }


def _upsert_review(conn, row: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO thesis_reviews
        (snapshot_id,review_date,status,macro_verdict,industry_verdict,company_verdict,
         expectation_verdict,timing_verdict,data_verdict,attribution,evidence,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(snapshot_id,review_date) DO UPDATE SET
          status=excluded.status, macro_verdict=excluded.macro_verdict,
          industry_verdict=excluded.industry_verdict, company_verdict=excluded.company_verdict,
          expectation_verdict=excluded.expectation_verdict, timing_verdict=excluded.timing_verdict,
          data_verdict=excluded.data_verdict, attribution=excluded.attribution,
          evidence=excluded.evidence, created_at=excluded.created_at""",
        (
            row["snapshot_id"], row["review_date"], row["status"], row["macro_verdict"],
            row["industry_verdict"], row["company_verdict"], row["expectation_verdict"],
            row["timing_verdict"], row["data_verdict"],
            json.dumps(row["attribution"], ensure_ascii=False),
            json.dumps(row["evidence"], ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def _create_task(conn, snapshot, review: dict[str, Any]) -> dict[str, Any] | None:
    title = f"复核 {snapshot['ticker']} 的预期差与交易时点"
    detail = (
        f"T+5收益 {review['evidence']['return_pct']}%，相对收益 "
        f"{review['evidence']['relative_return_pct']}%。先核验失效条件，再分别检查宏观、行业、公司KPI；"
        "在补齐因果证据前不得把价格下跌直接归因于某一研究层。"
    )
    cursor = conn.execute(
        """INSERT OR IGNORE INTO improvement_tasks
        (created_at,status,priority,source,ticker,module,title,detail,linked_run_id)
        VALUES (?,'open','high','thesis_review',?,'expectation_gap',?,?,?)""",
        (datetime.now().isoformat(timespec="seconds"), snapshot["ticker"], title, detail, snapshot["run_id"]),
    )
    return {"title": title, "detail": detail} if cursor.rowcount else None


def _summary(reviews: list[dict[str, Any]]) -> str:
    ready = [row for row in reviews if row["status"] == "reviewed"]
    failed = [row for row in ready if row["expectation_verdict"] == "failed"]
    return f"已复盘 {len(ready)} 个假设，{len(failed)} 个方向/预期偏差需复核；因果层归因必须等待对应KPI证据。"
