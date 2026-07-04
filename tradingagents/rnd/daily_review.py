from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from typing import Any

import requests

from .call_auction import latest_call_auction_brief
from .config import STOCK_UNIVERSE
from .daily_candidates import latest_daily_candidates
from .data_auditor import latest_data_quality_audit
from .market_pulse import latest_market_pulse


BROAD_INDEX_NAMES = {"贵州茅台", "比亚迪", "京东方Ａ", "京东方A", "宁德时代", "中信证券", "恒瑞医药"}
ALWAYS_HOME_BLOCKED = {"贵州茅台"}


def build_daily_review(
    conn,
    trade_date: str | None = None,
    *,
    candidates: dict[str, Any] | None = None,
    auction: dict[str, Any] | None = None,
    pulse: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Daily Review Agent: turn modules into one decision workflow.

    This is deliberately deterministic. It should tell the user what to watch
    today and what the system needs to fix, without hiding behind LLM prose.
    """
    trade_date = trade_date or _latest_trade_date(conn) or date.today().isoformat()
    candidates = candidates or latest_daily_candidates(conn, trade_date)
    auction = auction or latest_call_auction_brief(conn, STOCK_UNIVERSE, trade_date)
    pulse = pulse or latest_market_pulse(conn, trade_date)
    audit = audit or latest_data_quality_audit(conn, STOCK_UNIVERSE)

    decision = _decision_summary(candidates, auction, pulse, audit)
    market_overview = _market_overview(auction, pulse)
    sector_overview = _sector_overview(pulse)
    hypotheses = _candidate_hypotheses(candidates, pulse)
    review = _review_findings(conn, trade_date)
    fixes = _system_fixes(audit, review)
    watch = _watch_plan(decision, pulse, hypotheses, audit)
    llm_check = _llm_review_check(trade_date, decision, market_overview, sector_overview, hypotheses, audit)
    payload = {
        "role": "Daily Review Agent",
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "market_overview": market_overview,
        "sector_overview": sector_overview,
        "watch_plan": watch,
        "candidate_hypotheses": hypotheses,
        "review": review,
        "system_fixes": fixes,
        "llm_check": llm_check,
        "source_status": {
            "candidates": candidates.get("market", {}).get("status") or candidates.get("universe", {}).get("status"),
            "auction": (auction.get("source_status") or {}).get("status"),
            "market_pulse": (pulse.get("source_status") or {}).get("status"),
            "audit": audit.get("status"),
        },
    }
    _persist_daily_review(conn, payload)
    return payload


def latest_daily_review(
    conn,
    trade_date: str | None = None,
    *,
    candidates: dict[str, Any] | None = None,
    auction: dict[str, Any] | None = None,
    pulse: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if any(item is not None for item in (candidates, auction, pulse, audit)):
        return build_daily_review(
            conn,
            trade_date,
            candidates=candidates,
            auction=auction,
            pulse=pulse,
            audit=audit,
        )
    trade_date = trade_date or _latest_trade_date(conn)
    if trade_date:
        row = conn.execute(
            "SELECT payload FROM daily_reviews WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        if row:
            try:
                return json.loads(row["payload"])
            except (TypeError, ValueError):
                pass
    return build_daily_review(
        conn,
        trade_date,
        candidates=candidates,
        auction=auction,
        pulse=pulse,
        audit=audit,
    )


def _latest_trade_date(conn) -> str | None:
    dates = []
    for table in ("daily_candidates", "call_auction_snapshots", "market_pulse_snapshots", "data_quality_audits"):
        col = "audit_date" if table == "data_quality_audits" else "trade_date"
        try:
            row = conn.execute(f"SELECT MAX({col}) AS d FROM {table}").fetchone()
            if row and row["d"]:
                dates.append(str(row["d"]))
        except Exception:
            continue
    return max(dates) if dates else None


def _decision_summary(candidates: dict[str, Any], auction: dict[str, Any], pulse: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    pred = auction.get("prediction") or {}
    market = candidates.get("market") or {}
    auction_dir = str(pred.get("direction") or "")
    auction_stance = str(pred.get("stance") or "待更新")
    pulse_phase = str(pulse.get("phase") or "待更新")
    pulse_score = float(pulse.get("score") or 0)
    audit_status = str(audit.get("status") or "unknown")

    if audit_status == "blocked":
        level = "暂停新开仓"
        stance = "数据阻断，先修数据"
        action = "今天只看不动；关键数据修复前，不把候选股当交易依据。"
    elif auction_dir in {"down", "flat_down"} and pulse_score >= 75:
        level = "轻仓观察"
        stance = "开盘弱，但主线仍强"
        action = "先看板块再选个股，只看主线中军和低位承接，避免高开冲回落和尾盘追涨。"
    elif auction_dir in {"up", "flat_up"} and pulse_score >= 70:
        level = "积极观察"
        stance = "竞价与主线共振"
        action = "优先看主线核心股的分歧转强，仓位仍由数据审计和个股触发条件约束。"
    elif pulse_score >= 70:
        level = "结构机会"
        stance = "主线活跃但开盘信号一般"
        action = "先定板块，再选个股；没有板块确认的候选股不追。"
    else:
        level = "防守筛选"
        stance = "市场信号不够统一"
        action = "降低交易频率，只保留低位、放量、有资金承接的观察项。"

    return {
        "level": level,
        "stance": stance,
        "action": action,
        "market_phase": market.get("phase") or "unknown",
        "auction_stance": auction_stance,
        "auction_score": pred.get("score"),
        "pulse_phase": pulse_phase,
        "pulse_score": pulse.get("score"),
        "audit_status": audit_status,
        "audit_score": audit.get("score"),
        "one_liner": f"{level}：{action}",
    }


def _market_overview(auction: dict[str, Any], pulse: dict[str, Any]) -> dict[str, Any]:
    pred = auction.get("prediction") or {}
    indices = []
    for row in auction.get("market", [])[:4]:
        indices.append(
            {
                "name": row.get("name"),
                "ticker": row.get("ticker"),
                "change_pct": row.get("current_change_pct"),
                "open_gap_pct": row.get("open_gap_pct"),
                "from_open_pct": row.get("from_open_pct"),
                "amount_yi": row.get("amount_yi"),
                "quote_time": row.get("quote_time"),
            }
        )
    stance = pulse.get("stance") or {}
    return {
        "title": "今日大盘",
        "stance": pred.get("stance") or pulse.get("phase") or "待更新",
        "direction": pred.get("direction"),
        "score": pred.get("score"),
        "expected_path": pred.get("expected_path") or pulse.get("summary") or "",
        "indices": indices,
        "breadth": {
            "positive_ratio": stance.get("positive_ratio"),
            "fund_positive_ratio": stance.get("fund_positive_ratio"),
            "strong_count": stance.get("strong_count"),
        },
        "source": "腾讯实时行情 / 东方财富板块资金流",
        "note": "当前集合竞价为开盘价代理，不含逐笔委托和撤单率；板块资金来自东方财富实时板块资金流。",
    }


def _sector_overview(pulse: dict[str, Any]) -> dict[str, Any]:
    sections = pulse.get("sections") or {}
    return {
        "phase": pulse.get("phase"),
        "score": pulse.get("score"),
        "summary": pulse.get("summary"),
        "leaders": _sector_cards(sections.get("leaders"), "主线强化"),
        "starters": _sector_cards(sections.get("starters"), "启动预警"),
        "value_zones": _sector_cards(sections.get("value_zones"), "性价比观察"),
        "crowded": _sector_cards(sections.get("crowded"), "高位拥挤"),
    }


def _sector_cards(rows: list[dict[str, Any]] | None, label: str, limit: int = 10) -> list[dict[str, Any]]:
    out = []
    for row in (rows or [])[:limit]:
        out.append(
            {
                "label": label,
                "name": row.get("name"),
                "kind": row.get("kind"),
                "change_pct": row.get("change_pct"),
                "main_inflow_yi": row.get("main_inflow_yi"),
                "rank_score": row.get("rank_score"),
                "leader_stock": row.get("leader_stock"),
                "action_hint": row.get("action_hint"),
                "breadth": row.get("breadth"),
            }
        )
    return out


def _candidate_hypotheses(candidates: dict[str, Any], pulse: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    rows = candidates.get("rows") or []
    pulse_sections = pulse.get("sections") or {}
    leader_names = {str(row.get("name")) for row in pulse_sections.get("leaders", [])[:12]}
    starter_names = {str(row.get("name")) for row in pulse_sections.get("starters", [])[:12]}
    value_names = {str(row.get("name")) for row in pulse_sections.get("value_zones", [])[:12]}
    crowded_names = {str(row.get("name")) for row in pulse_sections.get("crowded", [])[:12]}
    board_names = leader_names | starter_names | value_names | crowded_names
    out = []
    for row in rows:
        quote = row.get("quote") or row.get("quote_snapshot") or {}
        reasons = row.get("reasons") or []
        risks = row.get("risk_flags") or []
        sector = str(row.get("sector") or "")
        theme = str(row.get("theme") or "")
        related_boards = _related_boards(row, board_names)
        is_leader = bool(related_boards & leader_names)
        is_starter = bool(related_boards & starter_names)
        is_value = bool(related_boards & value_names)
        is_crowded = bool(related_boards & crowded_names)
        change = _num(quote.get("change_pct"))
        amount = _num(quote.get("amount_yi"))
        market_cap = _num(row.get("market_cap_yi"))
        risk_labels = [str(flag.get("label") or flag) for flag in risks]
        trigger = _trigger_text(row, is_leader, is_starter, is_value, related_boards, change, amount)
        invalid = _invalid_text(row, risk_labels, change, related_boards)
        observe = _observe_text(row, amount, reasons)
        gate = _homepage_gate(row, related_boards, is_leader, is_starter, is_value, is_crowded, risks, change, amount, market_cap)
        hypothesis_score = _hypothesis_score(
            row,
            related_boards,
            is_leader,
            is_starter,
            is_value,
            is_crowded,
            risks,
            change,
            amount,
            market_cap,
            gate,
        )
        out.append(
            {
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "bucket": row.get("bucket"),
                "sector": sector,
                "theme": theme,
                "why": observe,
                "trigger": trigger,
                "invalid": invalid,
                "risk_flags": risk_labels,
                "quote": quote,
                "priority": _priority(hypothesis_score),
                "tags": _tags(row, is_leader, is_starter, is_value, related_boards),
                "related_boards": sorted(related_boards),
                "hypothesis_score": round(hypothesis_score, 2),
                "homepage_gate": gate,
            }
        )
    out = sorted(out, key=lambda row: row["hypothesis_score"], reverse=True)
    eligible = [row for row in out if (row.get("homepage_gate") or {}).get("status") == "eligible"]
    secondary = [row for row in out if (row.get("homepage_gate") or {}).get("status") == "secondary"]
    diversified = _diversify_hypotheses(eligible, limit)
    if diversified:
        if len({str((row.get("related_boards") or ["未分类"])[0]) for row in diversified}) == 1 and len(diversified) < 3:
            return []
        return diversified
    return _diversify_hypotheses(secondary, min(3, limit))


def _diversify_hypotheses(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    picked = []
    board_counts: dict[str, int] = {}
    for row in rows:
        boards = row.get("related_boards") or ["未分类"]
        primary = str(boards[0] or "未分类")
        if board_counts.get(primary, 0) >= 2:
            continue
        board_counts[primary] = board_counts.get(primary, 0) + 1
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _trigger_text(
    row: dict[str, Any],
    is_leader: bool,
    is_starter: bool,
    is_value: bool,
    related_boards: set[str],
    change: float | None,
    amount: float | None,
) -> str:
    board = " / ".join(sorted(related_boards)[:2]) or "相关板块"
    amount_rule = "成交额维持 8-80 亿" if amount is not None and amount <= 90 else "成交额不能继续异常放大"
    change_rule = "涨幅控制在 0.5%-4.5%" if change is None or change <= 4.8 else "先等涨幅回落到 4.5%以内"
    if is_leader:
        return f"参考东财板块排名，{board} 仍留在主线强化前 8，主力净流入为正；个股分歧后站回分时均价线，{change_rule}，{amount_rule}。"
    if is_starter or is_value:
        return f"参考东财板块排名，{board} 继续留在启动/性价比前 10，主力净流入不转负；个股不冲高回落，{change_rule}，{amount_rule}。"
    if change is not None and change >= 5:
        return "只看回落承接，不追高；次日缩量不破关键价位才进入观察。"
    return "需要板块确认和资金继续流入，单独异动不作为买点。"


def _invalid_text(row: dict[str, Any], risks: list[str], change: float | None, related_boards: set[str]) -> str:
    board = " / ".join(sorted(related_boards)[:2]) or "相关板块"
    if risks:
        return risks[0] + "；若放量滞涨或板块退潮，直接放弃。"
    if change is not None and change < 0:
        return "大成交仍收跌，说明抛压未消化；不能快速修复则放弃。"
    return f"{board} 跌出对应榜单前 10、主力转净流出，或个股涨幅超过 6.5%后放量滞涨，放弃。"


def _observe_text(row: dict[str, Any], amount: float | None, reasons: list[str]) -> str:
    base = "；".join(str(x) for x in reasons[:2]) if reasons else "全市场活跃线索"
    if amount is not None:
        return f"{base}；成交额约 {amount:.1f} 亿，先看承接质量。"
    return f"{base}；成交额缺失，先降级为待核验线索。"


def _related_boards(row: dict[str, Any], board_names: set[str]) -> set[str]:
    text = f"{row.get('name','')} {row.get('sector','')} {row.get('theme','')}"
    alias = {
        "紫金矿业": {"贵金属", "黄金", "工业金属", "小金属"},
        "三花智控": {"机器人", "机器人执行器", "汽车零部件"},
        "比亚迪": {"乘用车", "底盘与发动机系统"},
        "中国巨石": {"玻纤制造", "玻璃玻纤", "建筑材料"},
        "京东方Ａ": {"光学光电子", "智能家居"},
        "蓝色光标": {"广告营销", "AI应用"},
        "洛阳钼业": {"工业金属", "小金属", "有色金属", "一带一路"},
        "中钨高新": {"小金属", "工业金属", "有色金属"},
    }
    related = {name for name in board_names if name and name in text}
    for token, boards in alias.items():
        if token in text:
            related |= (boards & board_names)
    return related


def _hypothesis_score(
    row: dict[str, Any],
    related_boards: set[str],
    is_leader: bool,
    is_starter: bool,
    is_value: bool,
    is_crowded: bool,
    risks: list[Any],
    change: float | None,
    amount: float | None,
    market_cap: float | None,
    gate: dict[str, str],
) -> float:
    score = float(row.get("score") or 0)
    if related_boards:
        score += 10
    else:
        score -= 18
    if is_leader:
        score += 6
    if is_starter:
        score += 7
    if is_value:
        score += 8
    if is_crowded:
        score -= 7
    if risks:
        score -= 5 + len(risks) * 2
    if change is not None:
        if 0.5 <= change <= 4:
            score += 5
        elif change >= 6.5:
            score -= 8
        elif change < 0:
            score -= 4
    if amount is not None:
        if 8 <= amount <= 70:
            score += 4
        elif amount > 220:
            score -= 18
        elif amount > 120:
            score -= 10
    if market_cap is not None and market_cap >= 2500:
        score -= 10
    if str(row.get("name") or "") in BROAD_INDEX_NAMES:
        score -= 18
    if gate.get("status") == "secondary":
        score -= 8
    elif gate.get("status") == "blocked":
        score -= 35
    return max(0, min(100, score))


def _homepage_gate(
    row: dict[str, Any],
    related_boards: set[str],
    is_leader: bool,
    is_starter: bool,
    is_value: bool,
    is_crowded: bool,
    risks: list[Any],
    change: float | None,
    amount: float | None,
    market_cap: float | None,
) -> dict[str, str]:
    name = str(row.get("name") or "")
    if name in ALWAYS_HOME_BLOCKED:
        return {"status": "blocked", "reason": "宽基权重消费股，不放入首页交易观察位。"}
    if not related_boards:
        return {"status": "blocked", "reason": "未匹配到今日主线、启动或性价比板块。"}
    if name in BROAD_INDEX_NAMES and not is_value:
        return {"status": "blocked", "reason": "大市值宽基权重，仅因成交额活跃不进入首页。"}
    if market_cap is not None and market_cap >= 3500 and not (is_leader or is_value):
        return {"status": "blocked", "reason": "市值过大且缺少板块性价比确认。"}
    if amount is not None and amount >= 220 and not (is_leader or is_value):
        return {"status": "blocked", "reason": "成交额过大但板块关系不足，避免成交额榜误导。"}
    if is_crowded and not is_value:
        return {"status": "secondary", "reason": "相关板块处于高位拥挤，只能看分歧承接。"}
    if risks:
        first = str((risks[0] or {}).get("label") if isinstance(risks[0], dict) else risks[0])
        return {"status": "secondary", "reason": first or "存在风险标签，降级观察。"}
    if change is not None and change >= 6.5:
        return {"status": "secondary", "reason": "日内涨幅偏高，只能等回落承接。"}
    if is_leader or is_value or is_starter:
        return {"status": "eligible", "reason": "与今日板块主线或性价比方向匹配。"}
    return {"status": "secondary", "reason": "板块有关联，但确认度不足。"}


def _priority(score: float) -> str:
    if score >= 62:
        return "重点观察"
    if score >= 54:
        return "普通观察"
    return "低优先级"


def _tags(row: dict[str, Any], is_leader: bool, is_starter: bool, is_value: bool, related_boards: set[str]) -> list[str]:
    tags = []
    if is_leader:
        tags.append("主线相关")
    if is_starter:
        tags.append("启动预警")
    if is_value:
        tags.append("性价比")
    for board in sorted(related_boards):
        if board not in tags:
            tags.append(board)
    scores = row.get("strategy_scores") or {}
    for key, label in (("capital", "资金"), ("relative_strength", "强弱"), ("technical", "技术"), ("quality", "质量")):
        if float(scores.get(key) or 0) >= 68:
            tags.append(label)
    return tags[:4] or [str(row.get("bucket") or "线索")]


def _review_findings(conn, trade_date: str) -> dict[str, Any]:
    auction_outcome = None
    row = conn.execute(
        "SELECT * FROM call_auction_outcomes WHERE trade_date=?",
        (trade_date,),
    ).fetchone()
    if row:
        auction_outcome = dict(row)
        for key in ("actual_snapshot", "error_tags"):
            try:
                auction_outcome[key] = json.loads(auction_outcome[key] or "{}")
            except Exception:
                pass

    candidate_rows = conn.execute(
        """
        SELECT co.*, dc.name, dc.rank
        FROM candidate_outcomes co
        JOIN daily_candidates dc ON dc.trade_date=co.trade_date AND dc.ticker=co.ticker
        WHERE co.trade_date=? AND co.horizon=1 AND co.status='ready'
        ORDER BY dc.rank
        LIMIT 10
        """,
        (trade_date,),
    ).fetchall()
    ready = [dict(row) for row in candidate_rows]
    avg_return = None
    hit_rate = None
    if ready:
        returns = [float(row["return_pct"] or 0) for row in ready]
        avg_return = round(sum(returns) / len(returns), 3)
        hit_rate = round(sum(1 for value in returns if value > 0) / len(returns), 3)

    score_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT r.ticker, r.name, r.rating, r.action, s.horizon, s.total_score, s.diagnosis, s.error_tags
            FROM scores s
            JOIN runs r ON r.id=s.run_id
            WHERE s.horizon IN (1,5)
            ORDER BY s.created_at DESC
            LIMIT 8
            """
        )
    ]
    for row in score_rows:
        try:
            row["error_tags"] = json.loads(row.get("error_tags") or "[]")
        except Exception:
            row["error_tags"] = []

    return {
        "auction_outcome": auction_outcome,
        "candidate_sample": {
            "ready_count": len(ready),
            "avg_return_pct": avg_return,
            "hit_rate": hit_rate,
            "rows": ready[:5],
        },
        "report_scores": score_rows,
        "summary": _review_summary(auction_outcome, ready, score_rows),
    }


def _review_summary(auction_outcome: dict[str, Any] | None, candidate_rows: list[dict[str, Any]], score_rows: list[dict[str, Any]]) -> str:
    parts = []
    if auction_outcome:
        parts.append(f"集合竞价已校准，评分 {auction_outcome.get('score', '--')}。")
    else:
        parts.append("集合竞价尚未完成收盘校准。")
    if candidate_rows:
        returns = [float(row["return_pct"] or 0) for row in candidate_rows]
        parts.append(f"候选股已有 {len(candidate_rows)} 个 1 日样本，平均 {sum(returns)/len(returns):+.2f}%。")
    else:
        parts.append("候选股暂无足够收盘后样本，不能过早调整策略权重。")
    if score_rows:
        weak = [row for row in score_rows if float(row.get("total_score") or 0) < 60]
        parts.append(f"近期研报评分样本 {len(score_rows)} 个，低分 {len(weak)} 个。")
    return "".join(parts)


def _system_fixes(audit: dict[str, Any], review: dict[str, Any]) -> list[dict[str, str]]:
    fixes = []
    for issue in audit.get("issues", [])[:6]:
        severity = str(issue.get("severity") or "medium")
        module = str(issue.get("module") or issue.get("ticker") or "data")
        message = str(issue.get("message") or "")
        if not message:
            continue
        fixes.append(
            {
                "priority": "高" if severity == "high" else "中",
                "module": module,
                "problem": message,
                "next": str(issue.get("fix") or _default_fix(module)),
            }
        )
    if not review.get("candidate_sample", {}).get("ready_count"):
        fixes.append(
            {
                "priority": "中",
                "module": "daily_review",
                "problem": "候选股缺少次日/三日表现样本，无法判断每日推荐是否有增量价值。",
                "next": "补齐 candidate_outcomes 的 T+1/T+3 自动评估，并在首页展示命中率。",
            }
        )
    return fixes[:6]


def _default_fix(module: str) -> str:
    if "call_auction" in module:
        return "补真实竞价委托/撤单数据，或明确标注为开盘价代理。"
    if "daily_candidates" in module:
        return "补齐成交额/换手等核心字段，字段缺失时降级候选优先级。"
    if "quote" in module:
        return "保留腾讯/新浪双源共识，修复东财代理失败路径。"
    return "补数据源、加断言核验，并把降级信息反馈到首页。"


def _watch_plan(
    decision: dict[str, Any],
    pulse: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    audit: dict[str, Any],
) -> list[dict[str, str]]:
    leaders = [row.get("name") for row in (pulse.get("sections") or {}).get("leaders", [])[:3]]
    top = [row for row in hypotheses if row.get("priority") == "重点观察"][:3] or hypotheses[:3]
    plan = [
        {
            "title": "先判断仓位",
            "detail": decision["action"],
        },
        {
            "title": "再看主线",
            "detail": "重点看 " + " / ".join([name for name in leaders if name]) if leaders else "等待市场脉搏确认主线板块。",
        },
        {
            "title": "最后看个股",
            "detail": "优先观察 " + " / ".join([row["name"] for row in top if row.get("name")]) + "；只按触发条件行动。"
            if top
            else "今天个股筛选不硬凑数量，等板块和资金确认后再补观察标的。",
        },
    ]
    if audit.get("status") != "ready":
        plan.append({"title": "数据降级", "detail": audit.get("summary") or "存在数据质量提醒，所有结论降低置信度。"})
    return plan


def _llm_review_check(
    trade_date: str,
    decision: dict[str, Any],
    market: dict[str, Any],
    sectors: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {
            "status": "skipped",
            "model": "deepseek",
            "summary": "未配置 DeepSeek，Daily Review 仅完成规则核验。",
            "findings": [],
        }
    model = os.getenv("RND_AUDITOR_LLM_MODEL", os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-chat")).strip() or "deepseek-chat"
    context = {
        "trade_date": trade_date,
        "decision": decision,
        "market": {
            "stance": market.get("stance"),
            "expected_path": market.get("expected_path"),
            "indices": market.get("indices"),
            "breadth": market.get("breadth"),
        },
        "sectors": {
            "leaders": sectors.get("leaders", [])[:8],
            "starters": sectors.get("starters", [])[:10],
            "value_zones": sectors.get("value_zones", [])[:10],
            "crowded": sectors.get("crowded", [])[:6],
        },
        "stock_hypotheses": [
            {
                "name": row.get("name"),
                "ticker": row.get("ticker"),
                "priority": row.get("priority"),
                "related_boards": row.get("related_boards"),
                "homepage_gate": row.get("homepage_gate"),
                "quote": {
                    "change_pct": (row.get("quote") or {}).get("change_pct"),
                    "amount_yi": (row.get("quote") or {}).get("amount_yi"),
                    "turnover_pct": (row.get("quote") or {}).get("turnover_pct"),
                },
                "trigger": row.get("trigger"),
                "invalid": row.get("invalid"),
                "hypothesis_score": row.get("hypothesis_score"),
            }
            for row in hypotheses[:8]
        ],
        "audit": {
            "status": audit.get("status"),
            "score": audit.get("score"),
            "issues": audit.get("issues", [])[:5],
        },
    }
    prompt = (
        "你是 A 股 Daily Review 的二次核验员。只基于输入 JSON 检查，不要联网，不要编造额外事实。"
        "重点审查：今日决策是否与大盘/板块/数据审计一致；个股候选是否过于像成交额榜；"
        "是否应该先看板块而不是先看个股；触发条件和失效条件是否可执行。"
        "个股候选可以为空；如果为空且原因是板块优先、个股质量门槛不足，不要为了凑清单判为问题。"
        "返回严格 JSON："
        '{"status":"ready|warning|blocked","summary":"一句中文结论",'
        '"findings":[{"severity":"high|medium|low","module":"模块","message":"问题","fix":"建议"}]}。'
        "high 只用于会明显误导交易观察的问题；不要把模型偏好当事实。"
    )
    try:
        request_kwargs = {
            "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            "json": {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            "timeout": 45,
        }
        response = None
        for attempt in range(3):
            try:
                response = requests.post("https://api.deepseek.com/chat/completions", **request_kwargs)
                response.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        assert response is not None
        parsed = json.loads(response.json()["choices"][0]["message"]["content"])
        findings = parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
        return {
            "status": parsed.get("status") if parsed.get("status") in {"ready", "warning", "blocked"} else "warning",
            "model": model,
            "summary": str(parsed.get("summary") or "Daily Review LLM 核验完成。"),
            "findings": findings[:6],
        }
    except Exception as exc:
        return {
            "status": "warning",
            "model": model,
            "summary": f"Daily Review LLM 核验失败：{type(exc).__name__}；已保留规则版结论。",
            "findings": [
                {
                    "severity": "medium",
                    "module": "daily_review_llm",
                    "message": f"DeepSeek Daily Review 核验调用失败：{type(exc).__name__}",
                    "fix": "检查 DeepSeek 网络后重跑 daily-review。",
                }
            ],
        }


def _persist_daily_review(conn, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO daily_reviews (trade_date, generated_at, status, summary, payload)
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
            payload["decision"]["audit_status"],
            payload["decision"]["one_liner"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
