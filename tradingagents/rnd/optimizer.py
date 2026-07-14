from __future__ import annotations

import json
from datetime import date, datetime
from statistics import mean
from typing import Any

from .call_auction import evaluate_call_auction_prediction, latest_call_auction_outcome
from .config import HORIZONS, STOCK_UNIVERSE
from .daily_candidates import update_candidate_strategy_weights
from .data_auditor import build_data_quality_audit
from .market import evaluate_price_path
from .scoring import score_outcome
from .storage import list_runs, upsert_outcome, upsert_score
from .thesis_review import build_weekly_thesis_review


CANDIDATE_HORIZONS = (1, 3, 5)
MAX_FRESH_REPORT_EVALS = 6
MAX_FRESH_CANDIDATE_EVALS = 8


def build_optimization_review(conn, trade_date: str | None = None) -> dict[str, Any]:
    """Unified Optimization Review Agent.

    This agent closes feedback loops across Alpha R&D modules. It keeps the
    existing specialist agents intact, but makes their outcomes comparable and
    turns weak spots into concrete improvement_tasks.
    """
    trade_date = trade_date or _latest_trade_date(conn) or date.today().isoformat()
    generated_at = datetime.now().isoformat(timespec="seconds")

    reports = _refresh_report_outcomes(conn)
    candidates = _refresh_candidate_outcomes(conn)
    candidate_iteration = update_candidate_strategy_weights(conn)
    auction = _refresh_auction_outcome(conn, trade_date)
    audit = build_data_quality_audit(conn, STOCK_UNIVERSE, trade_date)
    thesis_review = build_weekly_thesis_review(conn, trade_date)

    tasks = []
    tasks.extend(_audit_tasks(conn, audit))
    tasks.extend(_auction_tasks(conn, auction, trade_date))
    tasks.extend(_candidate_tasks(conn, candidates, candidate_iteration))
    tasks.extend(_report_tasks(conn, reports))
    tasks.extend(thesis_review.get("tasks_created", []))

    status = _status(audit, auction, reports, candidates)
    summary = _summary(status, audit, auction, reports, candidates, len(tasks))
    payload = {
        "role": "Optimization Review Agent",
        "trade_date": trade_date,
        "generated_at": generated_at,
        "status": status,
        "summary": summary,
        "reports": reports,
        "candidates": candidates,
        "candidate_iteration": candidate_iteration,
        "auction": auction,
        "audit": {
            "status": audit.get("status"),
            "score": audit.get("score"),
            "summary": audit.get("summary"),
            "issue_count": len(audit.get("issues", [])),
        },
        "thesis_review": thesis_review,
        "tasks_created": tasks,
    }
    _persist_optimization_review(conn, payload)
    return payload


def _persist_optimization_review(conn, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO optimization_reviews (trade_date, generated_at, status, summary, payload)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            generated_at=excluded.generated_at,
            status=excluded.status,
            summary=excluded.summary,
            payload=excluded.payload
        """,
        (
            payload["trade_date"],
            payload["generated_at"],
            payload["status"],
            payload["summary"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()


def _refresh_report_outcomes(conn) -> dict[str, Any]:
    ready_scores = []
    pending = 0
    failed = []
    skipped = 0
    fresh_evals = 0
    for run in list_runs(conn):
        for horizon in HORIZONS:
            outcome = _existing_report_outcome(conn, run["id"], horizon)
            if outcome is None:
                if fresh_evals >= MAX_FRESH_REPORT_EVALS:
                    skipped += 1
                    continue
                fresh_evals += 1
                try:
                    outcome = evaluate_price_path(run["ticker"], run["report_date"], horizon)
                except Exception as exc:
                    failed.append({"ticker": run["ticker"], "horizon": horizon, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                upsert_outcome(conn, run["id"], horizon, outcome)
            score = score_outcome(run["action"], outcome, run["degradation_count"])
            if score:
                upsert_score(conn, run["id"], horizon, score)
                ready_scores.append(
                    {
                        "run_id": run["id"],
                        "ticker": run["ticker"],
                        "name": run["name"],
                        "horizon": horizon,
                        "score": score["total_score"],
                        "tags": score.get("error_tags", []),
                    }
                )
            elif outcome.get("status") == "pending":
                pending += 1
    low = [row for row in ready_scores if float(row["score"]) < 60]
    return {
        "ready_count": len(ready_scores),
        "pending_count": pending,
        "failed_count": len(failed),
        "skipped_count": skipped,
        "failures": failed[:6],
        "low_score_count": len(low),
        "avg_score": round(mean([float(row["score"]) for row in ready_scores]), 2) if ready_scores else None,
        "low_scores": sorted(low, key=lambda row: float(row["score"]))[:8],
    }


def _refresh_candidate_outcomes(conn) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT trade_date, ticker, name, rank
        FROM daily_candidates
        ORDER BY trade_date DESC, rank
        LIMIT 80
        """
    ).fetchall()
    ready = []
    pending = 0
    failed = []
    skipped = 0
    fresh_evals = 0
    for row in rows:
        for horizon in CANDIDATE_HORIZONS:
            outcome = _existing_candidate_outcome(conn, row["trade_date"], row["ticker"], horizon)
            if outcome is None:
                if fresh_evals >= MAX_FRESH_CANDIDATE_EVALS:
                    skipped += 1
                    continue
                fresh_evals += 1
                try:
                    outcome = evaluate_price_path(row["ticker"], row["trade_date"], horizon)
                except Exception as exc:
                    failed.append({"ticker": row["ticker"], "horizon": horizon, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                _upsert_candidate_outcome(conn, row["trade_date"], row["ticker"], horizon, outcome)
            if outcome.get("status") == "ready":
                ready.append(
                    {
                        "trade_date": row["trade_date"],
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "rank": row["rank"],
                        "horizon": horizon,
                        "return_pct": float(outcome.get("return_pct") or 0),
                    }
                )
            elif outcome.get("status") == "pending":
                pending += 1
    by_horizon = {}
    for horizon in CANDIDATE_HORIZONS:
        sample = [row for row in ready if row["horizon"] == horizon]
        by_horizon[str(horizon)] = _candidate_stats(sample)
    return {
        "source_rows": len(rows),
        "ready_count": len(ready),
        "pending_count": pending,
        "failed_count": len(failed),
        "skipped_count": skipped,
        "failures": failed[:6],
        "by_horizon": by_horizon,
    }


def _existing_report_outcome(conn, run_id: int, horizon: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM outcomes WHERE run_id=? AND horizon=? AND status='ready'",
        (run_id, horizon),
    ).fetchone()
    return dict(row) if row else None


def _existing_candidate_outcome(conn, trade_date: str, ticker: str, horizon: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM candidate_outcomes
        WHERE trade_date=? AND ticker=? AND horizon=? AND status='ready'
        """,
        (trade_date, ticker, horizon),
    ).fetchone()
    return dict(row) if row else None


def _upsert_candidate_outcome(conn, trade_date: str, ticker: str, horizon: int, outcome: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO candidate_outcomes (
            trade_date, ticker, horizon, status, entry_close, exit_close,
            return_pct, max_favorable_pct, max_adverse_pct, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, ticker, horizon) DO UPDATE SET
            status=excluded.status,
            entry_close=excluded.entry_close,
            exit_close=excluded.exit_close,
            return_pct=excluded.return_pct,
            max_favorable_pct=excluded.max_favorable_pct,
            max_adverse_pct=excluded.max_adverse_pct,
            checked_at=excluded.checked_at
        """,
        (
            trade_date,
            ticker,
            horizon,
            outcome.get("status", "pending"),
            outcome.get("entry_close"),
            outcome.get("exit_close"),
            outcome.get("return_pct"),
            outcome.get("max_favorable_pct"),
            outcome.get("max_adverse_pct"),
            outcome.get("checked_at", datetime.now().isoformat(timespec="seconds")),
        ),
    )
    conn.commit()


def _candidate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"ready_count": 0, "avg_return_pct": None, "hit_rate": None}
    returns = [float(row["return_pct"]) for row in rows]
    return {
        "ready_count": len(rows),
        "avg_return_pct": round(mean(returns) * 100, 2),
        "hit_rate": round(sum(1 for value in returns if value > 0) / len(returns), 3),
    }


def _refresh_auction_outcome(conn, trade_date: str) -> dict[str, Any]:
    outcome = evaluate_call_auction_prediction(conn, STOCK_UNIVERSE, trade_date)
    if outcome.get("status") == "pending_close":
        stored = latest_call_auction_outcome(conn, trade_date)
        if stored:
            return {**stored, "status": stored.get("status", "ready"), "source": "stored"}
    return outcome


def _audit_tasks(conn, audit: dict[str, Any]) -> list[dict[str, Any]]:
    created = []
    for issue in audit.get("issues", []):
        severity = str(issue.get("severity") or "medium")
        if severity not in {"high", "medium"}:
            continue
        module = str(issue.get("module") or issue.get("ticker") or "data_quality")
        title = f"修复数据审计问题：{module}"
        detail = str(issue.get("message") or "")
        if issue.get("fix"):
            detail += f"\n\n建议：{issue.get('fix')}"
        task = _insert_task(
            conn,
            priority="high" if severity == "high" else "medium",
            source="optimization_review",
            ticker=issue.get("ticker"),
            module=module,
            title=title,
            detail=detail,
        )
        if task:
            created.append(task)
    return created


def _auction_tasks(conn, auction: dict[str, Any], trade_date: str) -> list[dict[str, Any]]:
    status = str(auction.get("status") or "unknown")
    score = auction.get("score")
    if status in {"missing_prediction", "pending_close"}:
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="call_auction",
            title="补齐集合竞价预测收盘校准",
            detail=f"{trade_date} 集合竞价校准状态为 {status}，无法更新规则贡献权重。",
        )
        return [task] if task else []
    if score is not None and float(score) < 60:
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="call_auction",
            title="复盘集合竞价低分预测",
            detail=f"{trade_date} 集合竞价校准分 {score}，需要检查规则贡献、开盘价代理口径和实际盘中路径。",
        )
        return [task] if task else []
    return []


def _candidate_tasks(conn, candidates: dict[str, Any], iteration: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = []
    if candidates.get("failed_count", 0):
        sample = candidates.get("failures", [{}])[0]
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=sample.get("ticker"),
            module="candidate_outcomes",
            title="修复候选股历史行情评估失败",
            detail=f"候选 outcome 评估失败 {candidates.get('failed_count')} 次；示例：{sample.get('error')}",
        )
        if task:
            tasks.append(task)
    if candidates.get("skipped_count", 0):
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="candidate_outcomes",
            title="拆分候选股 outcome 批量补算",
            detail=f"本次为保证复盘稳定，跳过 {candidates.get('skipped_count')} 个缺失候选 outcome；需要单独后台任务分批补齐。",
        )
        if task:
            tasks.append(task)
    if candidates.get("ready_count", 0) < 10:
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="daily_candidates",
            title="补齐每日候选结果样本",
            detail="candidate_outcomes 可用样本少于 10 个，候选策略权重暂时不能可靠自迭代。",
        )
        if task:
            tasks.append(task)
    h1 = (candidates.get("by_horizon") or {}).get("1") or {}
    if h1.get("ready_count", 0) >= 10 and float(h1.get("hit_rate") or 0) < 0.45:
        task = _insert_task(
            conn,
            priority="high",
            source="optimization_review",
            ticker=None,
            module="daily_candidates",
            title="复盘每日候选 T+1 命中率",
            detail=f"T+1 命中率 {h1.get('hit_rate')}，平均收益 {h1.get('avg_return_pct')}%，需要调整候选评分或首页准入门槛。",
        )
        if task:
            tasks.append(task)
    if iteration.get("status") == "insufficient_samples":
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="candidate_strategy_weights",
            title="候选策略权重样本不足",
            detail=f"当前 5 日候选样本 {iteration.get('sample_size', 0)}，暂不更新策略权重。",
        )
        if task:
            tasks.append(task)
    return tasks


def _report_tasks(conn, reports: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = []
    if reports.get("failed_count", 0):
        sample = reports.get("failures", [{}])[0]
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=sample.get("ticker"),
            module="report_outcomes",
            title="修复研报历史行情评估失败",
            detail=f"研报 outcome 评估失败 {reports.get('failed_count')} 次；示例：{sample.get('error')}",
        )
        if task:
            tasks.append(task)
    if reports.get("skipped_count", 0):
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=None,
            module="report_outcomes",
            title="拆分研报 outcome 批量补算",
            detail=f"本次为保证复盘稳定，跳过 {reports.get('skipped_count')} 个缺失研报 outcome；需要单独后台任务分批补齐。",
        )
        if task:
            tasks.append(task)
    for row in reports.get("low_scores", [])[:5]:
        task = _insert_task(
            conn,
            priority="medium",
            source="optimization_review",
            ticker=row.get("ticker"),
            module="weekly_report",
            title=f"复盘低分研报：{row.get('ticker')}",
            detail=(
                f"{row.get('name')} {row.get('horizon')} 日评分 {row.get('score')}，"
                f"标签：{', '.join(row.get('tags') or [])}。"
            ),
            linked_run_id=row.get("run_id"),
        )
        if task:
            tasks.append(task)
    return tasks


def _insert_task(
    conn,
    *,
    priority: str,
    source: str,
    ticker: str | None,
    module: str,
    title: str,
    detail: str,
    linked_run_id: int | None = None,
) -> dict[str, Any] | None:
    existing = conn.execute(
        """
        SELECT id FROM improvement_tasks
        WHERE status='open'
          AND source=?
          AND COALESCE(ticker, '')=COALESCE(?, '')
          AND module=?
          AND title=?
          AND COALESCE(linked_run_id, -1)=COALESCE(?, -1)
        """,
        (source, ticker, module, title, linked_run_id),
    ).fetchone()
    if existing:
        return None
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO improvement_tasks (
            created_at, status, priority, source, ticker, module, title, detail, linked_run_id
        ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?)
        """,
        (now, priority, source, ticker, module, title, detail, linked_run_id),
    )
    conn.commit()
    return {"priority": priority, "module": module, "ticker": ticker, "title": title}


def _latest_trade_date(conn) -> str | None:
    dates = []
    for table, column in (
        ("daily_candidates", "trade_date"),
        ("call_auction_snapshots", "trade_date"),
        ("market_pulse_snapshots", "trade_date"),
        ("data_quality_audits", "audit_date"),
    ):
        try:
            row = conn.execute(f"SELECT MAX({column}) AS d FROM {table}").fetchone()
            if row and row["d"]:
                dates.append(str(row["d"]))
        except Exception:
            continue
    return max(dates) if dates else None


def _status(audit: dict[str, Any], auction: dict[str, Any], reports: dict[str, Any], candidates: dict[str, Any]) -> str:
    if audit.get("status") == "blocked":
        return "blocked"
    if auction.get("status") in {"missing_prediction"}:
        return "blocked"
    if reports.get("low_score_count", 0) or candidates.get("ready_count", 0) < 10:
        return "warning"
    return "ready"


def _summary(
    status: str,
    audit: dict[str, Any],
    auction: dict[str, Any],
    reports: dict[str, Any],
    candidates: dict[str, Any],
    task_count: int,
) -> str:
    auction_text = f"集合竞价校准 {auction.get('status', 'unknown')}"
    if auction.get("score") is not None:
        auction_text += f"，分数 {auction.get('score')}"
    candidate_h1 = (candidates.get("by_horizon") or {}).get("1") or {}
    candidate_text = f"候选样本 {candidates.get('ready_count', 0)}"
    if candidate_h1.get("hit_rate") is not None:
        candidate_text += f"，T+1 命中率 {candidate_h1.get('hit_rate')}"
    report_text = f"研报评分样本 {reports.get('ready_count', 0)}，低分 {reports.get('low_score_count', 0)}"
    return (
        f"{status}：{auction_text}；{candidate_text}；{report_text}；"
        f"数据审计 {audit.get('status')}；新增优化任务 {task_count}。"
    )
