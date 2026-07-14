# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Environment loading intentionally precedes config imports.
load_dotenv()

from tradingagents.dataflows.akshare_cn import is_a_share
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .call_auction import build_call_auction_brief, evaluate_call_auction_prediction
from .config import HORIZONS, PROMPT_VERSION, STOCK_UNIVERSE, ticker_name
from .daily_candidates import build_daily_candidates, update_candidate_strategy_weights
from .daily_review import build_daily_review
from .dashboard import build_dashboard
from .data_auditor import build_data_quality_audit
from .industry_intelligence import (
    ingest_industry_intelligence,
    persist_industry_intelligence,
    seed_industry_intelligence,
)
from .market import evaluate_price_path, latest_a_share_trade_date, previous_weekday
from .market_pulse import build_market_pulse
from .optimizer import build_optimization_review
from .scoring import score_outcome
from .signals import extract_thesis_snapshot, run_summary_from_state, scan_degradations
from .storage import (
    connect,
    list_runs,
    replace_degradations,
    upsert_outcome,
    upsert_run,
    upsert_score,
    upsert_thesis_snapshot,
)
from .thesis_review import build_weekly_thesis_review


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="A-share report R&D loop")
    parser.add_argument(
        "--mode",
        choices=[
            "init",
            "ingest",
            "evaluate",
            "dashboard",
            "weekly",
            "run-reports",
            "candidates",
            "auction",
            "auction-evaluate",
            "data-audit",
            "daily-review",
            "daily-optimize",
            "optimize",
            "market-pulse",
            "industry-intelligence",
            "thesis-review",
        ],
        default="weekly",
    )
    parser.add_argument("--date", help="Analysis date, defaults to latest A-share trading date")
    parser.add_argument("--tickers", nargs="*", help="Override ticker list")
    parser.add_argument("--skip-reports", action="store_true", help="For weekly mode, only ingest/evaluate/dashboard")
    parser.add_argument("--industry-input", type=Path, help="Validated daily industry-intelligence JSON")
    args = parser.parse_args(argv)

    conn = connect()
    if args.mode in {"init", "ingest", "evaluate", "dashboard", "weekly", "optimize", "daily-optimize"}:
        ingest_existing_logs(conn)
    if args.mode in {"evaluate", "weekly"}:
        evaluate_all(conn)
    if args.mode in {"candidates", "weekly"}:
        candidate_result = build_daily_candidates(conn, args.date)
        iteration = update_candidate_strategy_weights(conn)
        print(
            "Daily candidates: "
            f"{len(candidate_result.get('rows', []))} @ {candidate_result.get('trade_date')} "
            f"({candidate_result.get('market', {}).get('phase', 'unknown')}); "
            f"iteration={iteration.get('status')}"
        )
    if args.mode in {"auction", "weekly"}:
        auction = build_call_auction_brief(STOCK_UNIVERSE, conn, args.date)
        prediction = auction.get("prediction", {})
        print(
            "Call auction: "
            f"{auction.get('trade_date')} {prediction.get('stance', 'unknown')} "
            f"score={prediction.get('score', '--')} confidence={prediction.get('confidence', '--')}"
        )
    if args.mode == "auction-evaluate":
        outcome = evaluate_call_auction_prediction(conn, STOCK_UNIVERSE, args.date)
        print(
            "Call auction evaluation: "
            f"{outcome.get('trade_date')} {outcome.get('status')} "
            f"score={outcome.get('score', '--')}"
        )
    if args.mode in {"data-audit", "weekly"}:
        audit = build_data_quality_audit(conn, STOCK_UNIVERSE, args.date)
        print(
            "Data audit: "
            f"{audit.get('audit_date')} {audit.get('status')} "
            f"score={audit.get('score', '--')} issues={len(audit.get('issues', []))}"
        )
    if args.mode in {"market-pulse", "weekly"}:
        pulse = build_market_pulse(conn, args.date)
        print(
            "Market pulse: "
            f"{pulse.get('trade_date')} {pulse.get('phase')} "
            f"score={pulse.get('score', '--')}"
        )
    if args.mode in {"daily-review", "weekly"}:
        review = build_daily_review(conn, args.date)
        decision = review.get("decision", {})
        print(
            "Daily review: "
            f"{review.get('trade_date')} {decision.get('level', '--')} "
            f"audit={decision.get('audit_status', '--')}"
        )
    if args.mode == "optimize":
        review = build_optimization_review(conn, args.date)
        print(
            "Optimization review: "
            f"{review.get('trade_date')} {review.get('status')} "
            f"tasks={len(review.get('tasks_created', []))}"
        )
    if args.mode == "daily-optimize":
        print("Daily optimization cycle: start")
        pulse = build_market_pulse(conn, args.date)
        print(f"  market-pulse: {pulse.get('trade_date')} {pulse.get('phase')} score={pulse.get('score', '--')}")
        candidate_result = build_daily_candidates(conn, args.date)
        print(
            "  candidates: "
            f"{len(candidate_result.get('rows', []))} @ {candidate_result.get('trade_date')} "
            f"({candidate_result.get('market', {}).get('phase', 'unknown')})"
        )
        auction_outcome = evaluate_call_auction_prediction(conn, STOCK_UNIVERSE, args.date)
        print(
            "  auction-evaluate: "
            f"{auction_outcome.get('trade_date')} {auction_outcome.get('status')} "
            f"score={auction_outcome.get('score', '--')}"
        )
        optimization = build_optimization_review(conn, args.date)
        print(
            "  optimization: "
            f"{optimization.get('trade_date')} {optimization.get('status')} "
            f"tasks={len(optimization.get('tasks_created', []))}"
        )
        daily_review = build_daily_review(conn, args.date)
        decision = daily_review.get("decision", {})
        print(
            "  daily-review: "
            f"{daily_review.get('trade_date')} {decision.get('level', '--')} "
            f"audit={decision.get('audit_status', '--')}"
        )
    if args.mode == "industry-intelligence":
        intelligence_path = (
            ingest_industry_intelligence(args.industry_input)
            if args.industry_input
            else persist_industry_intelligence(seed_industry_intelligence())
        )
        print(f"Industry intelligence: {intelligence_path}")
    if args.mode in {"run-reports", "weekly"} and not args.skip_reports:
        run_reports(conn, args.tickers, args.date)
        ingest_existing_logs(conn)
        evaluate_all(conn)
    if args.mode in {"weekly", "thesis-review"}:
        thesis_review = build_weekly_thesis_review(conn, args.date)
        print(
            "Friday thesis review: "
            f"{thesis_review.get('review_date')} {thesis_review.get('status')} "
            f"reviewed={len(thesis_review.get('reviews', []))} "
            f"tasks={len(thesis_review.get('tasks_created', []))}"
        )
    if args.mode in {
        "init",
        "ingest",
        "evaluate",
        "dashboard",
        "weekly",
        "run-reports",
        "candidates",
        "auction",
        "auction-evaluate",
        "data-audit",
        "daily-review",
        "daily-optimize",
        "optimize",
        "market-pulse",
        "industry-intelligence",
        "thesis-review",
    }:
        try:
            path = build_dashboard(conn)
            print(f"Dashboard: {path}")
        except Exception as exc:
            print(f"[warn] Dashboard refresh skipped: {exc}")
    return 0


def ingest_existing_logs(conn) -> int:
    base = Path.home() / ".tradingagents" / "logs"
    count = 0
    for path in base.glob("*/TradingAgentsStrategy_logs/full_states_log_*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warn] failed to read {path}: {exc}")
            continue
        summary = run_summary_from_state(state)
        ticker = summary["ticker"] or path.parents[1].name
        events = scan_degradations(state)
        run_id = upsert_run(
            conn,
            {
                "ticker": ticker,
                "name": ticker_name(ticker),
                "report_date": summary["report_date"] or _date_from_log(path),
                "prompt_version": PROMPT_VERSION,
                "action": summary["action"],
                "rating": summary["rating"],
                "confidence": summary["confidence"],
                "entry": summary["entry"],
                "stop": summary["stop"],
                "target": summary["target"],
                "final_report_len": summary["final_report_len"],
                "excerpt": summary["excerpt"],
                "log_path": str(path),
                "pdf_path": _desktop_pdf_path(ticker),
                "html_path": _desktop_html_path(ticker),
                "status": "recorded",
                "degradation_count": len(events),
            },
        )
        replace_degradations(conn, run_id, events)
        upsert_thesis_snapshot(conn, run_id, extract_thesis_snapshot(state))
        count += 1
    print(f"Ingested logs: {count}")
    return count


def evaluate_all(conn) -> None:
    for run in list_runs(conn):
        for horizon in HORIZONS:
            outcome = evaluate_price_path(run["ticker"], run["report_date"], horizon)
            upsert_outcome(conn, run["id"], horizon, outcome)
            score = score_outcome(run["action"], outcome, run["degradation_count"])
            if score:
                upsert_score(conn, run["id"], horizon, score)
    print("Evaluation refreshed.")


def run_reports(conn, tickers: list[str] | None, analysis_date: str | None) -> None:
    selected = tickers or [item["ticker"] for item in STOCK_UNIVERSE]
    if not _has_llm_key():
        _record_missing_key_tasks(conn, selected)
        print("[warn] LLM API key is missing; skipped report generation and refreshed dashboard.")
        return
    date_str = analysis_date or latest_a_share_trade_date(selected[0])
    for ticker in selected:
        if _has_run(conn, ticker, date_str):
            print(f"[skip] {ticker} already has run for {date_str}")
            continue
        print(f"[run] {ticker} @ {date_str}")
        config = DEFAULT_CONFIG.copy()
        if is_a_share(ticker):
            config["data_vendors"] = {
                **config["data_vendors"],
                "core_stock_apis": "akshare,yfinance",
                "fundamental_data": "akshare,yfinance",
                "news_data": "akshare,yfinance",
            }
        try:
            ta = TradingAgentsGraph(debug=False, config=config)
            ta.propagate(ticker, date_str)
            _render_pdf(ticker)
        except Exception as exc:
            _record_run_failure(conn, ticker, exc)
            print(f"[error] {ticker} failed: {exc}")


def _has_run(conn, ticker: str, report_date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM runs WHERE ticker=? AND report_date=? AND prompt_version=?",
        (ticker, report_date, PROMPT_VERSION),
    ).fetchone()
    return row is not None


def _has_llm_key() -> bool:
    provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER", DEFAULT_CONFIG.get("llm_provider", "openai")).lower()
    key_map = {
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env = key_map.get(provider)
    if not env:
        return True
    return bool(os.getenv(env))


def _record_missing_key_tasks(conn, tickers: list[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for ticker in tickers:
        conn.execute(
            """
            INSERT OR IGNORE INTO improvement_tasks (
                created_at, status, priority, source, ticker, module, title, detail, linked_run_id
            ) VALUES (?, 'open', 'high', 'automation', ?, 'llm_config', ?, ?, NULL)
            """,
            (
                now,
                ticker,
                "配置 LLM key 后生成首批周度研报",
                "周度 R&D 自动化已运行，但当前环境缺少所选 provider 的 API key。不会保存密钥；请通过 .env 或系统环境变量配置。",
            ),
        )
    conn.commit()


def _record_run_failure(conn, ticker: str, exc: Exception) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR IGNORE INTO improvement_tasks (
            created_at, status, priority, source, ticker, module, title, detail, linked_run_id
        ) VALUES (?, 'open', 'high', 'run_failure', ?, 'weekly_runner', ?, ?, NULL)
        """,
        (
            now,
            ticker,
            f"{ticker} 周度研报生成失败",
            f"{type(exc).__name__}: {exc}",
        ),
    )
    conn.commit()


def _render_pdf(ticker: str) -> None:
    script = Path(__file__).resolve().parents[2] / "make_report_pdf.py"
    subprocess.run([sys.executable, str(script), ticker], check=False)


def _desktop_pdf_path(ticker: str) -> str:
    name = ticker_name(ticker)
    path = Path.home() / "Desktop" / f"TradingAgents_{name}_{ticker}_研究报告.pdf"
    return str(path) if path.exists() else ""


def _desktop_html_path(ticker: str) -> str:
    name = ticker_name(ticker)
    path = Path.home() / "Desktop" / f"TradingAgents_{name}_{ticker}_研究报告.html"
    return str(path) if path.exists() else ""


def _date_from_log(path: Path) -> str:
    stem = path.stem.replace("full_states_log_", "")
    try:
        datetime.strptime(stem, "%Y-%m-%d")
        return stem
    except ValueError:
        return previous_weekday().strftime("%Y-%m-%d")


if __name__ == "__main__":
    raise SystemExit(main())
