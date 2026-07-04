from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, ensure_dirs


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            report_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            action TEXT NOT NULL,
            rating TEXT,
            confidence REAL,
            entry TEXT,
            stop TEXT,
            target TEXT,
            final_report_len INTEGER NOT NULL DEFAULT 0,
            excerpt TEXT,
            log_path TEXT NOT NULL,
            pdf_path TEXT,
            html_path TEXT,
            status TEXT NOT NULL DEFAULT 'recorded',
            degradation_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(ticker, report_date, prompt_version)
        );

        CREATE TABLE IF NOT EXISTS degradation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            optimization_hint TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, module, message),
            FOREIGN KEY(run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            horizon INTEGER NOT NULL,
            status TEXT NOT NULL,
            entry_date TEXT,
            exit_date TEXT,
            entry_close REAL,
            exit_close REAL,
            return_pct REAL,
            max_favorable_pct REAL,
            max_adverse_pct REAL,
            benchmark_return_pct REAL,
            relative_return_pct REAL,
            checked_at TEXT NOT NULL,
            UNIQUE(run_id, horizon),
            FOREIGN KEY(run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            horizon INTEGER NOT NULL,
            total_score REAL NOT NULL,
            direction_score REAL NOT NULL,
            relative_score REAL NOT NULL,
            risk_score REAL NOT NULL,
            execution_score REAL NOT NULL,
            data_score REAL NOT NULL,
            error_tags TEXT NOT NULL,
            diagnosis TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, horizon),
            FOREIGN KEY(run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS improvement_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL,
            source TEXT NOT NULL,
            ticker TEXT,
            module TEXT,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            linked_run_id INTEGER,
            UNIQUE(source, ticker, module, title, linked_run_id)
        );

        CREATE TABLE IF NOT EXISTS daily_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            rank INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            sector TEXT,
            theme TEXT,
            market_cap_yi REAL,
            score REAL NOT NULL,
            bucket TEXT NOT NULL,
            market_phase TEXT,
            strategy_scores TEXT NOT NULL,
            risk_flags TEXT NOT NULL,
            reasons TEXT NOT NULL,
            quote_snapshot TEXT NOT NULL,
            market_snapshot TEXT NOT NULL,
            strategy_weights TEXT NOT NULL,
            source_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS candidate_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            status TEXT NOT NULL,
            entry_close REAL,
            exit_close REAL,
            return_pct REAL,
            max_favorable_pct REAL,
            max_adverse_pct REAL,
            checked_at TEXT NOT NULL,
            UNIQUE(trade_date, ticker, horizon)
        );

        CREATE TABLE IF NOT EXISTS candidate_strategy_weights (
            strategy TEXT PRIMARY KEY,
            weight REAL NOT NULL,
            sample_size INTEGER NOT NULL DEFAULT 0,
            hit_rate_5d REAL,
            avg_return_5d REAL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS call_auction_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            market_snapshot TEXT NOT NULL,
            stock_snapshots TEXT NOT NULL,
            prediction TEXT NOT NULL,
            rule_weights TEXT NOT NULL,
            source_status TEXT NOT NULL,
            UNIQUE(trade_date)
        );

        CREATE TABLE IF NOT EXISTS call_auction_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            status TEXT NOT NULL,
            actual_snapshot TEXT NOT NULL,
            score REAL,
            error_tags TEXT NOT NULL,
            diagnosis TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            UNIQUE(trade_date)
        );

        CREATE TABLE IF NOT EXISTS call_auction_rule_weights (
            rule TEXT PRIMARY KEY,
            weight REAL NOT NULL,
            sample_size INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS data_quality_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            score REAL NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(audit_date)
        );

        CREATE TABLE IF NOT EXISTS market_pulse_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            phase TEXT NOT NULL,
            score REAL NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(trade_date)
        );

        CREATE TABLE IF NOT EXISTS daily_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(trade_date)
        );

        CREATE TABLE IF NOT EXISTS optimization_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(trade_date)
        );
        """
    )
    _ensure_columns(
        conn,
        "daily_candidates",
        {
            "sector": "TEXT",
            "theme": "TEXT",
            "market_cap_yi": "REAL",
        },
    )
    conn.commit()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, spec in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")


def upsert_run(conn: sqlite3.Connection, row: dict) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO runs (
            ticker, name, report_date, created_at, prompt_version, action, rating,
            confidence, entry, stop, target, final_report_len, excerpt, log_path,
            pdf_path, html_path, status, degradation_count
        ) VALUES (
            :ticker, :name, :report_date, :created_at, :prompt_version, :action, :rating,
            :confidence, :entry, :stop, :target, :final_report_len, :excerpt, :log_path,
            :pdf_path, :html_path, :status, :degradation_count
        )
        ON CONFLICT(ticker, report_date, prompt_version) DO UPDATE SET
            name=excluded.name,
            action=excluded.action,
            rating=excluded.rating,
            confidence=excluded.confidence,
            entry=excluded.entry,
            stop=excluded.stop,
            target=excluded.target,
            final_report_len=excluded.final_report_len,
            excerpt=excluded.excerpt,
            log_path=excluded.log_path,
            pdf_path=excluded.pdf_path,
            html_path=excluded.html_path,
            status=excluded.status,
            degradation_count=excluded.degradation_count
        """,
        {**row, "created_at": row.get("created_at") or now},
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT id FROM runs WHERE ticker=? AND report_date=? AND prompt_version=?",
            (row["ticker"], row["report_date"], row["prompt_version"]),
        ).fetchone()["id"]
    )


def replace_degradations(conn: sqlite3.Connection, run_id: int, events: Iterable) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for event in events:
        conn.execute(
            """
            INSERT OR IGNORE INTO degradation_events (
                run_id, module, severity, message, optimization_hint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event.module, event.severity, event.message, event.optimization_hint, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO improvement_tasks (
                created_at, status, priority, source, ticker, module, title, detail, linked_run_id
            )
            SELECT ?, 'open', ?, 'degradation', runs.ticker, ?, ?, ?, ?
            FROM runs WHERE runs.id=?
            """,
            (
                now,
                "high" if event.severity == "high" else "medium",
                event.module,
                f"补强 {event.module} 数据/降级路径",
                f"{event.message}\n\n优化建议：{event.optimization_hint}",
                run_id,
                run_id,
            ),
        )
    conn.commit()


def upsert_outcome(conn: sqlite3.Connection, run_id: int, horizon: int, outcome: dict) -> None:
    conn.execute(
        """
        INSERT INTO outcomes (
            run_id, horizon, status, entry_date, exit_date, entry_close, exit_close,
            return_pct, max_favorable_pct, max_adverse_pct, benchmark_return_pct,
            relative_return_pct, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, horizon) DO UPDATE SET
            status=excluded.status,
            entry_date=excluded.entry_date,
            exit_date=excluded.exit_date,
            entry_close=excluded.entry_close,
            exit_close=excluded.exit_close,
            return_pct=excluded.return_pct,
            max_favorable_pct=excluded.max_favorable_pct,
            max_adverse_pct=excluded.max_adverse_pct,
            benchmark_return_pct=excluded.benchmark_return_pct,
            relative_return_pct=excluded.relative_return_pct,
            checked_at=excluded.checked_at
        """,
        (
            run_id,
            horizon,
            outcome.get("status", "pending"),
            outcome.get("entry_date"),
            outcome.get("exit_date"),
            outcome.get("entry_close"),
            outcome.get("exit_close"),
            outcome.get("return_pct"),
            outcome.get("max_favorable_pct"),
            outcome.get("max_adverse_pct"),
            outcome.get("benchmark_return_pct"),
            outcome.get("relative_return_pct"),
            outcome.get("checked_at"),
        ),
    )
    conn.commit()


def upsert_score(conn: sqlite3.Connection, run_id: int, horizon: int, score: dict) -> None:
    conn.execute(
        """
        INSERT INTO scores (
            run_id, horizon, total_score, direction_score, relative_score, risk_score,
            execution_score, data_score, error_tags, diagnosis, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, horizon) DO UPDATE SET
            total_score=excluded.total_score,
            direction_score=excluded.direction_score,
            relative_score=excluded.relative_score,
            risk_score=excluded.risk_score,
            execution_score=excluded.execution_score,
            data_score=excluded.data_score,
            error_tags=excluded.error_tags,
            diagnosis=excluded.diagnosis,
            created_at=excluded.created_at
        """,
        (
            run_id,
            horizon,
            score["total_score"],
            score["direction_score"],
            score["relative_score"],
            score["risk_score"],
            score["execution_score"],
            score["data_score"],
            json.dumps(score.get("error_tags", []), ensure_ascii=False),
            score.get("diagnosis", ""),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM runs ORDER BY report_date DESC, ticker"))


def latest_dashboard_rows(conn: sqlite3.Connection) -> dict:
    runs = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY report_date DESC, ticker")]
    outcomes = [dict(r) for r in conn.execute("SELECT * FROM outcomes ORDER BY horizon")]
    scores = [dict(r) for r in conn.execute("SELECT * FROM scores ORDER BY horizon")]
    degradations = [dict(r) for r in conn.execute("SELECT * FROM degradation_events ORDER BY created_at DESC")]
    tasks = [dict(r) for r in conn.execute("SELECT * FROM improvement_tasks ORDER BY created_at DESC")]
    candidate_weights = [
        dict(r)
        for r in conn.execute("SELECT * FROM candidate_strategy_weights ORDER BY strategy")
    ]
    optimization = _latest_json_payload(conn, "optimization_reviews")
    return {
        "runs": runs,
        "outcomes": outcomes,
        "scores": scores,
        "degradations": degradations,
        "tasks": tasks,
        "candidate_strategy_weights": candidate_weights,
        "optimization_review": optimization,
    }


def _latest_json_payload(conn: sqlite3.Connection, table: str) -> dict:
    row = conn.execute(f"SELECT payload FROM {table} ORDER BY trade_date DESC, generated_at DESC LIMIT 1").fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        return {}
