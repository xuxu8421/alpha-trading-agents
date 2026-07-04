from __future__ import annotations


def score_outcome(action: str, outcome: dict, degradation_count: int = 0) -> dict | None:
    if outcome.get("status") != "ready":
        return None

    ret = float(outcome.get("return_pct") or 0)
    rel = outcome.get("relative_return_pct")
    rel = float(rel) if rel is not None else None
    max_fav = float(outcome.get("max_favorable_pct") or 0)
    max_adv = float(outcome.get("max_adverse_pct") or 0)
    action = (action or "unknown").lower()

    direction_score = _direction_score(action, ret)
    relative_score = _direction_score(action, rel) if rel is not None else 55.0
    risk_score = _risk_score(action, max_fav, max_adv)
    execution_score = _execution_score(action, ret, max_fav, max_adv)
    data_score = max(20.0, 100.0 - degradation_count * 18.0)
    total = (
        direction_score * 0.30
        + relative_score * 0.20
        + risk_score * 0.15
        + execution_score * 0.10
        + 70.0 * 0.10
        + 75.0 * 0.10
        + data_score * 0.05
    )
    tags = _error_tags(action, ret, rel, max_fav, max_adv, degradation_count)
    return {
        "total_score": round(total, 2),
        "direction_score": round(direction_score, 2),
        "relative_score": round(relative_score, 2),
        "risk_score": round(risk_score, 2),
        "execution_score": round(execution_score, 2),
        "data_score": round(data_score, 2),
        "error_tags": tags,
        "diagnosis": _diagnosis(action, ret, rel, tags),
    }


def _direction_score(action: str, ret: float | None) -> float:
    if ret is None:
        return 55.0
    if action == "buy":
        return _scaled_positive(ret)
    if action == "sell":
        return _scaled_positive(-ret)
    if action == "hold":
        abs_ret = abs(ret)
        if abs_ret <= 0.02:
            return 100.0
        if abs_ret <= 0.05:
            return 75.0
        return max(20.0, 75.0 - (abs_ret - 0.05) * 600)
    return 50.0


def _scaled_positive(value: float) -> float:
    if value >= 0.08:
        return 100.0
    if value >= 0:
        return 60.0 + value * 500
    return max(0.0, 60.0 + value * 800)


def _risk_score(action: str, max_fav: float, max_adv: float) -> float:
    if action == "buy":
        drawdown = abs(min(max_adv, 0))
        return max(0.0, 100.0 - drawdown * 800)
    if action == "sell":
        adverse_rally = max(max_fav, 0)
        return max(0.0, 100.0 - adverse_rally * 700)
    return max(30.0, 100.0 - max(abs(max_fav), abs(max_adv)) * 600)


def _execution_score(action: str, ret: float, max_fav: float, max_adv: float) -> float:
    # A-share execution realism proxy. Large next-window adverse move after a
    # buy/sell means the report needed more caution around T+1 and limit moves.
    if action == "buy" and max_adv <= -0.095:
        return 35.0
    if action == "sell" and ret < -0.095:
        return 90.0
    if action == "sell" and max_fav >= 0.095:
        return 35.0
    return 75.0


def _error_tags(action: str, ret: float, rel: float | None, max_fav: float, max_adv: float, degradation_count: int) -> list[str]:
    tags: list[str] = []
    if action == "buy" and ret < -0.02:
        tags.append("direction_error")
    if action == "sell" and ret > 0.02:
        tags.append("direction_error")
    if action == "hold" and abs(ret) > 0.05:
        tags.append("horizon_error")
    if rel is not None:
        if action == "buy" and rel < -0.02:
            tags.append("relative_underperformance")
        if action == "sell" and rel > 0.02:
            tags.append("relative_missed_upside")
    if action == "buy" and max_adv <= -0.095:
        tags.append("a_share_execution_risk")
    if action == "sell" and max_fav >= 0.095:
        tags.append("timing_error")
    if degradation_count:
        tags.append("data_gap")
    return tags or ["ok"]


def _diagnosis(action: str, ret: float, rel: float | None, tags: list[str]) -> str:
    pct = f"{ret * 100:+.2f}%"
    rel_text = f"，相对沪深300 {rel * 100:+.2f}%" if rel is not None else ""
    if tags == ["ok"]:
        return f"{action.upper()} 结论在该周期内表现可接受，标的收益 {pct}{rel_text}。"
    return f"{action.upper()} 结论需要复盘：标的收益 {pct}{rel_text}；触发标签：{', '.join(tags)}。"

