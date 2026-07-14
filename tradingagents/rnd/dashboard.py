from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from string import Template

from tradingagents.dataflows.akshare_cn import _get_ohlcv_tencent_frame, get_ohlcv_akshare_frame

from .call_auction import latest_call_auction_brief
from .config import DASHBOARD_PATH, STOCK_UNIVERSE, ensure_dirs
from .daily_candidates import latest_daily_candidates
from .daily_review import latest_daily_review
from .data_auditor import latest_data_quality_audit
from .industry_chain import build_industry_chain_brief
from .market_pulse import latest_market_pulse
from .premarket import build_premarket_brief
from .signals import extract_confidence, normalize_action, parse_report_meta
from .storage import latest_dashboard_rows

ARCH_IMAGE = "assets/alpha_rnd_architecture_ai.png"

POOL_POLICY = [
    {
        "stage": "候选池",
        "purpose": "收集主题、行业和事件线索，要求有明确入池理由和可验证催化。",
        "exit": "两周内无法形成可检验假设，或数据源覆盖不足。",
    },
    {
        "stage": "观察池",
        "purpose": "每周固定生成研报和多周期评价，验证信号质量。",
        "exit": "连续两轮结论与走势/风险暴露偏离，进入优化或剔除复查。",
    },
    {
        "stage": "核心池",
        "purpose": "只放通过多周期复盘、数据质量稳定、交易假设清晰的股票。",
        "exit": "基本面假设破坏、流动性恶化、模型持续错判或降级无法修复。",
    },
]

DATA_SOURCES = [
    {
        "layer": "行情/估值",
        "current": "东财直连 + 腾讯 + 新浪交叉校验；AkShare 用于历史K线",
        "status": "已接入",
        "note": "实时价格、涨跌幅、成交额必须至少两源一致；历史 OHLCV 走 akshare/东财。",
    },
    {
        "layer": "财报三表",
        "current": "新浪 FinanceReport2022",
        "status": "已接入",
        "note": "利润表、资产负债表、现金流量表已注册为本土 fundamental_data 源。",
    },
    {
        "layer": "新闻/资金/舆情",
        "current": "东财新闻、千股千评、资金流、龙虎榜、券商研报、雪球讨论热度",
        "status": "已接入",
        "note": "雪球讨论热度已进入 sentiment/policy agent，用作散户拥挤度和题材追逐信号。",
    },
    {
        "layer": "宏观/事件",
        "current": "FRED 可选；巨潮公告规划中",
        "status": "待补强",
        "note": "后续接入国内利率、信用、政策、公告、解禁、分红、融资融券。",
    },
]

SCREENING_PLACEHOLDERS = [
    {
        "name": "强势主题突破",
        "condition": "行业/概念强度进入市场前 20%，个股放量突破 20 日平台，主力资金连续 3 日净流入。",
        "status": "待接入每日候选池",
    },
    {
        "name": "基本面改善低估",
        "condition": "利润率或现金流连续改善，估值低于近三年分位，且近期无重大解禁/减持压力。",
        "status": "待接入财报因子",
    },
    {
        "name": "回调到位反转",
        "condition": "中期趋势未破，短期回撤至关键均线/筹码区，量能收敛后出现资金回流。",
        "status": "待接入技术评分",
    },
]

ARCHITECTURE = {
    "title": "Alpha R&D LangGraph 多智能体协作拓扑",
    "image": ARCH_IMAGE,
    "caption": "真实工作流：Data Auditor -> 国家/宏观政策 -> 行业结构与预期 -> 公司/财报 -> 预期差 -> 多空研究与交易风控 -> 决策报告 -> 周五假设归因，结论和证据沿同一状态总线贯通。",
}

SYSTEM_CADENCE = [
    {"frequency": "常驻", "time": "全天", "module": "工作台服务", "status": "运行中", "note": "launchd 保活，进程退出后自动重启；任务完成后自动刷新静态页面。"},
    {"frequency": "每日", "time": "09:26", "module": "集合竞价预测", "status": "运行中", "note": "交易日 09:25 撮合后生成大盘与股票池开盘结构判断。"},
    {"frequency": "每日", "time": "09:27", "module": "数据检查员", "status": "运行中", "note": "三源校验实时行情，并检查当天候选、竞价、研报复盘数据是否混版。"},
    {"frequency": "每日", "time": "09:35 / 11:35 / 15:20", "module": "市场脉搏官", "status": "运行中", "note": "监控板块资金、情绪阶段、主线/启动/拥挤/退潮板块。"},
    {"frequency": "每日", "time": "15:25", "module": "全市场候选股", "status": "运行中", "note": "收盘后扫描全市场成交与强弱，不使用现有选股池加权。"},
    {"frequency": "每日", "time": "15:45", "module": "统一优化复盘", "status": "运行中", "note": "交易日对照集合竞价、候选股、研报和数据审计结果，写入优化任务并更新权重。"},
    {"frequency": "每日", "time": "18:30", "module": "每日总结与飞书", "status": "待配置", "note": "飞书 Webhook 配置完成后启用；整合候选、竞价、产业情报和风险。"},
    {"frequency": "每日", "time": "19:15", "module": "产业情报", "status": "运行中", "note": "汇总公告、财经媒体、公众号、雪球与个人作者观点。"},
    {"frequency": "每周", "time": "周五 20:30", "module": "三级假设复盘与自迭代", "status": "运行中", "note": "按预测→实际→宏观/行业/公司/预期/时点/数据归因→规则迭代闭环；证据不足的因果层保持未验证。"},
    {"frequency": "按需", "time": "手动", "module": "个股完整研报", "status": "可运行", "note": "新增股票或重大事件时触发多智能体完整研究。"},
]


def build_dashboard(conn, output_path: Path = DASHBOARD_PATH) -> Path:
    ensure_dirs()
    premarket = build_premarket_brief(STOCK_UNIVERSE)
    _sync_premarket_degradations(conn, premarket)
    payload = latest_dashboard_rows(conn)
    _attach_report_previews(payload)
    payload["daily_candidates"] = latest_daily_candidates(conn)
    payload["data_audit"] = latest_data_quality_audit(conn, STOCK_UNIVERSE)
    payload["market_pulse"] = latest_market_pulse(conn)
    payload["universe"] = STOCK_UNIVERSE
    payload["market_data"] = _build_market_data(_market_universe(payload["daily_candidates"]))
    payload["stock_lookup"] = _build_stock_lookup()
    payload["premarket"] = premarket
    payload["call_auction"] = latest_call_auction_brief(conn, STOCK_UNIVERSE)
    payload["daily_review"] = latest_daily_review(
        conn,
        candidates=payload["daily_candidates"],
        auction=payload["call_auction"],
        pulse=payload["market_pulse"],
        audit=payload["data_audit"],
    )
    payload["industry_chain"] = build_industry_chain_brief(STOCK_UNIVERSE)
    payload["pool_policy"] = POOL_POLICY
    payload["data_sources"] = DATA_SOURCES
    payload["screening_placeholders"] = SCREENING_PLACEHOLDERS
    payload["architecture"] = ARCHITECTURE
    payload["cadence"] = SYSTEM_CADENCE
    payload["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_path.write_text(_html(payload), encoding="utf-8")
    return output_path


def _market_universe(daily_candidates: dict) -> list[dict]:
    seen = set()
    rows: list[dict] = []
    for item in STOCK_UNIVERSE + [
        {"ticker": row.get("ticker", ""), "name": row.get("name", "")}
        for row in daily_candidates.get("rows", [])
    ]:
        ticker = str(item.get("ticker", "")).upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(item)
    return rows


def _sync_premarket_degradations(conn, brief: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for source in brief.get("sources", []):
        module = f"premarket_{source.get('name', 'unknown')}"
        if source.get("status") == "ready":
            conn.execute(
                """
                UPDATE improvement_tasks SET status='resolved', created_at=?
                WHERE status='open' AND source='premarket_degradation' AND module=?
                """,
                (now, module),
            )
            continue
        title = f"补强盘前消息源：{source.get('name', 'unknown')}"
        detail = (
            f"状态：{source.get('status')}；缓存条数：{source.get('count', 0)}；"
            f"错误：{source.get('error', 'unknown')}。优化方向：替换失效接口、缩短超时或增加独立备用源。"
        )
        existing = conn.execute(
            """
            SELECT id FROM improvement_tasks
            WHERE status='open' AND source='premarket_degradation' AND module=?
            ORDER BY id DESC LIMIT 1
            """,
            (module,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE improvement_tasks SET created_at=?, detail=? WHERE id=?",
                (now, detail, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO improvement_tasks (
                    created_at, status, priority, source, ticker, module, title, detail, linked_run_id
                ) VALUES (?, 'open', 'medium', 'premarket_degradation', 'MARKET', ?, ?, ?, NULL)
                """,
                (now, module, title, detail),
            )
    conn.commit()


def _build_market_data(universe: list[dict]) -> dict:
    end = datetime.now().date()
    start = end - timedelta(days=190)
    out: dict[str, dict] = {}
    for item in universe:
        ticker = item.get("ticker", "")
        if not ticker:
            continue
        try:
            df = _load_market_data_frame(ticker, start.isoformat(), end.isoformat()).tail(90)
            rows = []
            for _, row in df.iterrows():
                rows.append(
                    {
                        "date": row["Date"].strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                    }
                )
            closes = [r["close"] for r in rows]
            out[ticker] = {
                "source": "AkShare / Eastmoney 前复权日 K",
                "rows": rows,
                "last": closes[-1] if closes else None,
                "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) > 1 and closes[-2] else None,
                "high_20": round(max(closes[-20:]), 2) if closes else None,
                "low_20": round(min(closes[-20:]), 2) if closes else None,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as exc:
            out[ticker] = {
                "source": "AkShare / Eastmoney 前复权日 K",
                "rows": [],
                "error": str(exc),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
    return out


def _load_market_data_frame(ticker: str, start_date: str, end_date: str):
    # Prefer Tencent in the dashboard path so a flaky Eastmoney session does not
    # block auction calibration or data-audit completion.
    try:
        return _get_ohlcv_tencent_frame(ticker, start_date, end_date)
    except Exception:
        return get_ohlcv_akshare_frame(ticker, start_date, end_date)


def _ticker_suffix(code: str) -> str:
    code = str(code or "").strip()
    if code.startswith(("6", "9")):
        return f"{code}.SS"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _build_stock_lookup(limit: int = 7000) -> dict:
    fallback = [
        {"name": item["name"], "ticker": item["ticker"], "source": "tracked"}
        for item in STOCK_UNIVERSE
    ]
    # Full-market lookup is helpful for search, but it should never block the
    # daily calibration/audit pipeline when remote quote vendors are unstable.
    return {
        "status": "fallback",
        "source": "tracked universe fallback",
        "rows": fallback,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _attach_report_previews(payload: dict) -> None:
    for run in payload.get("runs", []):
        report = ""
        log_path = run.get("log_path")
        if log_path:
            try:
                state = json.loads(Path(log_path).read_text(encoding="utf-8"))
                report = state.get("final_report") or state.get("final_trade_decision") or ""
            except Exception:
                report = ""
        run["report_markdown"] = report
        run["report_html"] = _markdown_to_html(report)
        run["front_summary"] = _front_summary(report or run.get("excerpt") or "")
        run["consistency"] = _report_consistency(run, report)


def _markdown_to_html(text: str) -> str:
    text = text or "暂无完整研报内容。"
    text = text.replace("\r\n", "\n")
    try:
        import markdown as md

        return md.markdown(
            text,
            extensions=["tables", "extra", "sane_lists", "nl2br"],
            output_format="html5",
        )
    except Exception:
        safe = html.escape(text)
        safe = safe.replace("\n\n", "</p><p>").replace("\n", "<br>")
        return f"<p>{safe}</p>"


def _front_summary(text: str, limit: int = 260) -> str:
    clean = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    clean = re.sub(r"```.*?```", " ", clean, flags=re.S)
    clean = re.sub(r"^#{1,6}\s*", "", clean, flags=re.M)
    clean = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", clean)
    clean = re.sub(r"[*_`>|]{1,}", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"^(摘要与核心结论|核心结论|摘要)[:：\s]*", "", clean)
    clean = re.sub(r"^评级[:：][^。；;]*[。；;]\s*", "", clean)
    clean = re.sub(r"^本报告对[^，。]{0,40}(给予|给出)[^，。]{0,20}评级[，。]\s*", "", clean)
    clean = re.sub(r"^当前操作建议[:：]?[^。；;]*[。；;]\s*", "", clean)
    clean = clean.replace("---", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit]


def _report_consistency(run: dict, report: str) -> dict:
    meta = parse_report_meta(report)
    parsed = {
        "action": normalize_action(meta.get("action", ""), meta.get("rating", "")),
        "rating": meta.get("rating") or "",
        "confidence": extract_confidence(report),
        "entry": meta.get("entry") or "",
        "stop": meta.get("stop") or "",
        "target": meta.get("target") or "",
    }
    mismatches: list[str] = []
    checked = 0
    for field in ("action", "rating", "entry", "stop", "target"):
        table_value = _clean(run.get(field))
        report_value = _clean(parsed.get(field))
        if field == "action" and report_value == "unknown":
            report_value = ""
        if not table_value or not report_value:
            continue
        checked += 1
        if _compact(table_value).lower() != _compact(report_value).lower():
            mismatches.append(field)
    return {
        "status": "mismatch" if mismatches else "aligned" if checked else "missing",
        "checked": checked,
        "mismatches": mismatches,
        "parsed": parsed,
    }


def _clean(value) -> str:
    return str(value or "").strip()


def _compact(text: str) -> str:
    return "".join(str(text or "").split())


def _html(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = Template(
        r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alpha R&D 工作台</title>
<style>
*{box-sizing:border-box}
html,body{overflow-x:hidden}
body{margin:0;background:#f4f6f8;color:#182331;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
button,input,select{font:inherit}
button{border:1px solid #23699a;background:#23699a;color:#fff;border-radius:6px;padding:6px 10px;cursor:pointer;white-space:nowrap}
button:focus-visible{outline:2px solid #7eb6e5;outline-offset:2px}
button.ghost{background:#fff;color:#23699a;border-color:#bfd0df}
button.tiny{font-size:12px;padding:4px 7px}
.topbar{position:sticky;top:0;z-index:8;background:#101820;color:#d9e3ee;border-bottom:1px solid #0b1118}
.brandRow{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:10px 24px 8px}.brandBlock{min-width:0;display:flex;align-items:baseline;gap:14px}.brand{font-weight:850;font-size:28px;line-height:1;color:#fff;letter-spacing:0}.generated{color:#8fa1b3;font-size:12px;white-space:nowrap}
.statusbar{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.65);background:#f7fafc;border-radius:999px;padding:3px 10px;color:#546476;font-size:12px;line-height:1.2;white-space:nowrap}.chip b{color:#101820;font-size:14px}
.commandRow{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:7px 24px 10px;border-top:1px solid rgba(255,255,255,.08)}
.nav{display:flex;gap:4px}.nav button{background:transparent;border-color:transparent;color:#c5d1dc;text-align:left;padding:7px 10px;border-radius:6px}.nav button.active{background:#203141;color:#fff}.nav button:hover{background:#1a2835}
.topActions{display:flex;gap:7px;align-items:center;justify-content:flex-end;flex:0 0 auto}.topActions button{height:32px}
.topbar button.ghost{background:rgba(255,255,255,.08);color:#eef5fb;border-color:rgba(255,255,255,.26)}
.main{padding:14px 20px 34px;min-width:0}.panel{display:none}.panel.active{display:block}
.section{background:#fff;border:1px solid #dce3ea;border-radius:8px;overflow:hidden}.sectionHead{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border-bottom:1px solid #e5ebf0;background:#fbfcfd}.sectionTitle{font-weight:800;color:#17202a}.sectionBody{padding:12px}
.tableWrap{overflow:auto}table{width:100%;min-width:1060px;border-collapse:collapse;background:#fff}th,td{border-bottom:1px solid #e7edf2;padding:9px 10px;text-align:left;vertical-align:top}th{font-size:12px;color:#4f5f70;background:#f6f8fa;white-space:nowrap}tr:hover td{background:#fbfcfe}
.stockCell{min-width:124px;white-space:nowrap}.themeCell{min-width:220px}.decisionCell{min-width:98px;white-space:nowrap}.levelCell{min-width:190px}.summaryCell{min-width:440px}.opCell{min-width:112px;white-space:nowrap}
.researchList{background:#fff}.researchHead,.researchRow{display:grid;grid-template-columns:150px 100px minmax(360px,1fr) 86px;gap:14px;align-items:start}.researchHead{padding:8px 12px;background:#f6f8fa;border-bottom:1px solid #e7edf2;color:#4f5f70;font-size:12px;font-weight:800}.researchHead span:last-child{text-align:center}.researchRow{padding:11px 12px;border-bottom:1px solid #e7edf2}.researchRow:last-child{border-bottom:0}.researchRow:hover{background:#fbfcfe}.stockBlock{min-width:0}.stockName{font-weight:850;color:#17202a;white-space:nowrap}.stockLink{border:0;background:transparent;color:#17202a;padding:0;font-weight:850;border-radius:3px}.stockLink:hover{text-decoration:underline}.themeLine{font-size:12px;color:#667586;margin-bottom:4px;white-space:normal}.levelInline{display:flex;gap:12px;flex-wrap:wrap;margin-top:5px;color:#667586;font-size:12px}.researchDecision{white-space:nowrap}.rowActions{display:flex;justify-content:center;align-items:flex-start}.rowActions .actions{justify-content:center;align-items:center}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.muted{color:#667586}.small{font-size:12px}.summaryText{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:#2f3d4c;word-break:normal;line-height:1.62}
.badge{display:inline-block;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:800;white-space:nowrap}.buy{background:#e8f6ee;color:#176b3a}.sell{background:#fdecea;color:#b42318}.hold{background:#eef5fb;color:#1f5f8f}.unknown{background:#eef2f6;color:#52606d}
.actions{display:flex;gap:6px;flex-wrap:wrap}.empty{padding:18px;color:#667586;background:#fff;border:1px dashed #ccd6df;border-radius:8px}
.poolActions{display:flex;gap:6px}.rule{border-left:4px solid #23699a;padding:9px 10px;background:#fbfcfd;margin-bottom:8px}.task{border-left:4px solid #9a6700;background:#fff;padding:9px 10px;margin-bottom:8px;border:1px solid #e4eaf1;border-left-width:4px;border-radius:6px}.task.high{border-left-color:#b42318}
.rec{border:1px solid #dce3ea;background:#fff;border-radius:8px;padding:11px;margin-bottom:9px}.recTitle{font-weight:800}.recReason{margin-top:5px;color:#506174;font-size:13px}
.candidateHero{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:13px 16px;border-bottom:1px solid #e5ebf0;background:#fff}.candidateHero h2{margin:0;font-size:18px;color:#17202a}.candidateHero p{margin:3px 0 0;color:#52606d;max-width:980px}.candidateMeta{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.candidateList{background:#fff}.candidateRow{display:grid;grid-template-columns:56px minmax(150px,.8fr) 92px minmax(320px,1.6fr) minmax(230px,1fr) minmax(84px,.35fr);gap:12px;align-items:start;padding:12px 14px;border-bottom:1px solid #e7edf2}.candidateRow>*{min-width:0}.candidateRow:hover{background:#fbfcfe}.candidateRank{font-weight:900;font-size:18px;color:#8794a1}.candidateStock{min-width:0}.candidateName{font-weight:900;color:#17202a}.candidateTheme{margin-top:2px;color:#667586;font-size:12px;line-height:1.45;overflow-wrap:anywhere}.candidateScore b{display:block;font-size:22px;color:#17202a;line-height:1.1}.candidateScore span{display:inline-flex;margin-top:5px;border-radius:999px;background:#eef5fb;color:#1f5f8f;padding:2px 7px;font-size:11px;font-weight:850;white-space:nowrap}.candidateReasons{margin:0;padding-left:17px;color:#273646}.candidateReasons li{margin:0 0 4px;padding-left:1px}.scoreBars{display:grid;gap:5px}.scoreBar{display:grid;grid-template-columns:78px minmax(54px,1fr) 34px;gap:6px;align-items:center;font-size:11px;color:#5c6c7d}.barTrack{height:6px;border-radius:999px;background:#edf2f6;overflow:hidden}.barFill{height:100%;background:#23699a}.riskFlags{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.riskFlags .softChip{background:#fff4df;color:#8a5a00;border-color:#f1d8a8}.candidateAction{overflow-wrap:anywhere}.quoteMini{color:#52606d;font-size:12px;white-space:normal}.candidateRefs{padding:9px 16px;background:#fbfcfd;color:#7a8998;font-size:11px;border-top:1px solid #e5ebf0}.candidateRefs a{color:#55758e}
.auctionHero{padding:15px 18px;border-bottom:1px solid #e5ebf0;background:#fff}.auctionHero h2{margin:0;font-size:20px;color:#17202a}.auctionHero p{margin:5px 0 0;color:#52606d;max-width:1080px}.auctionGrid{display:grid;grid-template-columns:minmax(0,1fr) 360px}.auctionMain{min-width:0}.auctionSide{border-left:1px solid #e5ebf0;background:#fbfcfd}.auctionTimeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-bottom:1px solid #e5ebf0}.auctionStep{padding:12px;border-right:1px solid #e5ebf0;min-width:0}.auctionStep:last-child{border-right:0}.auctionTime{font-weight:900;color:#17202a}.auctionLabel{display:inline-flex;margin:4px 0 7px;border-radius:999px;background:#eef5fb;color:#1f5f8f;padding:2px 8px;font-size:11px;font-weight:850}.auctionStep p{margin:0;color:#52606d;font-size:12px}.auctionBlock{padding:13px 16px;border-bottom:1px solid #e5ebf0}.auctionBlock h3{margin:0 0 8px;color:#17202a;font-size:15px}.factorList{display:grid;gap:8px}.factorItem{border:1px solid #dce5ed;background:#fff;border-radius:8px;padding:10px}.factorTop{display:flex;align-items:center;justify-content:space-between;gap:10px}.factorName{font-weight:900;color:#17202a}.factorWeight{font-size:12px;color:#667586;white-space:nowrap}.factorLogic{margin-top:4px;color:#2f3d4c}.factorBad{margin-top:4px;color:#8a5a00;font-size:12px}.auctionWatch{overflow:auto}.auctionWatch table{min-width:920px}.auctionRefs{padding:9px 16px;background:#fbfcfd;color:#7a8998;font-size:11px}.auctionRefs a{color:#55758e}.roadItem{border-left:4px solid #23699a;background:#fff;border-radius:6px;border:1px solid #dce5ed;border-left-width:4px;padding:9px 10px;margin-bottom:8px}.roadItem b{color:#17202a}
.sourceGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.source{background:#fff;border:1px solid #dce3ea;border-radius:8px;padding:12px}.source h3{font-size:15px;margin:0 0 6px;color:#17202a}.auditIssue.low{border-left-color:#55708a;background:#f7fafc}.llmReview{border:1px solid #dce5ed;border-radius:8px;background:#f8fbfd;padding:12px;margin:12px 0}.llmReviewHead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.llmReview p{margin:0;color:#243447}
.premarketHero{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:14px 16px;border-bottom:1px solid #e5ebf0;background:#fff}.briefDate{font-size:12px;color:#667586;white-space:nowrap}.stance{display:flex;align-items:flex-start;gap:10px;min-width:0}.stanceBadge{flex:0 0 auto;border-radius:999px;padding:3px 9px;background:#eef5fb;color:#1f5f8f;font-size:12px;font-weight:800;white-space:nowrap}.stanceText{font-size:15px;font-weight:750;color:#17202a;max-width:880px}.marketTape{display:grid;grid-template-columns:repeat(6,minmax(126px,1fr));border-bottom:1px solid #e5ebf0;background:#fbfcfd}.tapeItem{padding:10px 12px;border-right:1px solid #e5ebf0;min-width:0}.tapeItem:last-child{border-right:0}.tapeName{display:block;color:#667586;font-size:12px;white-space:nowrap}.tapeValue{font-weight:850;font-size:17px;color:#17202a}.rise{color:#b42318}.fall{color:#16805b}.premarketGrid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(340px,.8fr)}.premarketColumn{min-width:0}.premarketColumn+.premarketColumn{border-left:1px solid #e5ebf0}.briefBlock{padding:12px 16px}.briefBlock+.briefBlock{border-top:1px solid #e5ebf0}.briefTitle{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;font-weight:850;color:#17202a}.briefMeta{font-size:12px;color:#667586;font-weight:400;white-space:nowrap}.feedItem{padding:9px 0;border-bottom:1px solid #edf1f4}.feedItem:last-child{border-bottom:0}.feedTitle{display:block;color:#17202a;font-weight:750;text-decoration:none;line-height:1.5}.feedTitle:hover{color:#1f5f8f;text-decoration:underline}.feedSummary{margin-top:3px;color:#566677;font-size:12px;line-height:1.55}.feedMeta{margin-top:3px;color:#7a8998;font-size:11px}.riskMark{display:inline-block;width:6px;height:6px;border-radius:50%;background:#b42318;margin:0 7px 2px 0}.calendarItem{display:grid;grid-template-columns:48px minmax(0,1fr);gap:9px;padding:8px 0;border-bottom:1px solid #edf1f4}.calendarItem:last-child{border-bottom:0}.calendarTime{font-weight:850;color:#1f5f8f;white-space:nowrap}.calendarEvent{color:#273646}.importance{color:#b17800;font-size:11px;white-space:nowrap}.noticeStock{display:inline-block;color:#1f5f8f;font-size:11px;font-weight:800;margin-right:6px;white-space:nowrap}.hotStrip{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:0}.hotItem{padding:8px 10px;border-right:1px solid #edf1f4;border-bottom:1px solid #edf1f4;min-width:0}.hotItem:nth-child(5n){border-right:0}.hotRank{color:#8995a1;font-size:11px}.hotName{font-weight:800;color:#17202a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sourceFoot{padding:8px 16px;background:#fbfcfd;color:#7a8998;font-size:11px;border-top:1px solid #e5ebf0}.sourceFoot a{color:#55758e}
.chainHero{padding:16px 18px;border-bottom:1px solid #e5ebf0;background:linear-gradient(120deg,#111b22,#172a25);color:#eef7ef}.chainHeroTop{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.chainHero h2{margin:0;color:#fff;font-size:26px;line-height:1.15}.chainHero p{margin:7px 0 0;color:#c8d7d0;line-height:1.65;max-width:920px}.chainTag{display:inline-flex;align-items:center;border-radius:999px;background:#d8ff4f;color:#142016;padding:4px 10px;font-weight:850;font-size:12px;white-space:nowrap}.trackTabs{display:flex;gap:6px;overflow:auto;padding:10px 12px;border-bottom:1px solid #e5ebf0;background:#fbfcfd}.trackBtn{background:#fff;color:#273646;border-color:#d7e1ea}.trackBtn.active{background:#203141;color:#fff;border-color:#203141}.infraLayout{display:grid;grid-template-columns:minmax(0,1fr) 320px;min-height:560px}.infraMain{min-width:0}.infraSide{border-left:1px solid #e5ebf0;background:#fbfcfd;min-width:0}.trackSummary{padding:12px 16px;border-bottom:1px solid #e5ebf0;color:#435366}.chainMap{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-bottom:1px solid #e5ebf0}.chainLayer{padding:12px;border-right:1px solid #e5ebf0;min-width:0}.chainLayer:last-child{border-right:0}.chainLayer h3{margin:0 0 8px;font-size:13px;color:#667586}.nodeBox{border:1px solid #dce5ed;background:#fff;border-radius:6px;padding:7px 8px;margin-bottom:6px;color:#17202a;font-weight:750;font-size:12px;line-height:1.35}.watchPanel{padding:12px 16px;border-bottom:1px solid #e5ebf0}.watchPanel h3,.radarPanel h3,.companyPanel h3,.evidencePanel h3{margin:0 0 8px;font-size:14px;color:#17202a}.chipCloud{display:flex;flex-wrap:wrap;gap:7px}.softChip{display:inline-flex;align-items:center;border:1px solid #dce5ed;background:#f7fafc;color:#2f3d4c;border-radius:999px;padding:3px 9px;font-size:12px;line-height:1.4;white-space:nowrap}.companyPanel,.radarPanel,.evidencePanel{padding:12px 16px;border-bottom:1px solid #e5ebf0}.companyItem{padding:9px 0;border-bottom:1px solid #edf1f4}.companyItem:last-child{border-bottom:0}.companyTop{display:flex;align-items:center;justify-content:space-between;gap:10px}.companyName{font-weight:850;color:#17202a}.linkLine{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:5px;color:#52606d;font-size:12px}.evidence{display:inline-flex;align-items:center;border-radius:999px;padding:2px 7px;font-size:11px;font-weight:800;white-space:nowrap}.evidence.confirmed{background:#e8f6ee;color:#176b3a}.evidence.business_fit{background:#eef5fb;color:#1f5f8f}.evidence.needs_review{background:#fff4df;color:#9a6700}.radarItem{border:1px solid #dce5ed;background:#fff;border-radius:8px;padding:10px;margin-bottom:8px}.radarTitle{font-weight:850;color:#17202a}.radarImpact{margin-top:4px;color:#52606d;font-size:12px;line-height:1.5}.learningList{margin:0;padding-left:18px;color:#273646}.learningList li{margin-bottom:7px}.chainRefs{padding:9px 16px;background:#fbfcfd;color:#7a8998;font-size:11px}.chainRefs a{color:#55758e}
.softChip.ready{background:#e8f6ee;color:#176b3a;border-color:#c6ead4}.softChip.warning{background:#fff4df;color:#8a5a00;border-color:#f1d8a8}.softChip.blocked,.softChip.failed{background:#fdecea;color:#b42318;border-color:#f5c2bd}.auditGrid{display:grid;gap:10px}.auditRow{border:1px solid #dce5ed;border-radius:8px;background:#fff;padding:10px}.auditTop{display:flex;align-items:center;justify-content:space-between;gap:12px}.auditProviders{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}.auditIssue{border-left:4px solid #b42318;background:#fff7f6;border-radius:6px;padding:8px 10px;margin-bottom:7px}.auditIssue.medium{border-left-color:#9a6700;background:#fffaf0}
.pulseHero{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:14px 16px;border-bottom:1px solid #e5ebf0;background:#fff}.pulseHero h2{margin:0;font-size:20px;color:#17202a}.pulseHero p{margin:4px 0 0;color:#52606d;max-width:900px}.pulseScore{min-width:120px;text-align:right}.pulseScore b{display:block;font-size:28px;line-height:1;color:#17202a}.pulseGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:12px}.pulseBlock{border:1px solid #dce5ed;border-radius:8px;background:#fff;overflow:hidden}.pulseBlock h3{margin:0;padding:10px 12px;border-bottom:1px solid #e5ebf0;background:#fbfcfd;color:#17202a;font-size:15px}.pulseList{display:grid}.pulseItem{display:grid;grid-template-columns:minmax(130px,.8fr) 72px 82px minmax(180px,1fr);gap:10px;padding:10px 12px;border-bottom:1px solid #edf1f4;align-items:start}.pulseItem:last-child{border-bottom:0}.pulseName{font-weight:850;color:#17202a}.pulseMeta{font-size:12px;color:#667586}.pulseHint{font-size:12px;color:#52606d;line-height:1.45}.pulseSources{padding:9px 16px;background:#fbfcfd;border-top:1px solid #e5ebf0;color:#7a8998;font-size:11px}.pulseSources a{color:#55758e}
.decisionDesk{display:grid;gap:12px}.decisionHero{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:18px;padding:18px 20px;background:#fff;border:1px solid #dce3ea;border-radius:8px}.decisionHero h1{margin:0;font-size:25px;line-height:1.2;color:#17202a}.decisionHero p{margin:8px 0 0;color:#2f3d4c;font-size:15px;max-width:980px}.decisionMeta{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.decisionScoreCard{border-left:4px solid #23699a;background:#f8fbfd;border-radius:8px;padding:12px}.decisionScoreCard b{display:block;font-size:20px;color:#17202a}.decisionScoreCard span{display:block;color:#667586;font-size:12px;margin-top:4px}.decisionGrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.decisionCard{background:#fff;border:1px solid #dce3ea;border-radius:8px;padding:12px;min-height:112px}.decisionCard h3{margin:0 0 8px;font-size:13px;color:#667586}.decisionCard b{display:block;color:#17202a;font-size:17px}.decisionCard p{margin:6px 0 0;color:#435366;font-size:12px;line-height:1.55}.decisionLayout{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:12px}.hypothesisList{display:grid;gap:10px;padding:12px}.hypothesisCard{border:1px solid #dce5ed;background:#fff;border-radius:8px;padding:12px}.hypothesisTop{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.hypothesisName{font-weight:900;color:#17202a;font-size:16px}.hypothesisMeta{color:#667586;font-size:12px}.gateNote{margin-top:8px;padding:6px 8px;border-radius:6px;background:#f3f7fa;color:#435366;font-size:12px;line-height:1.45}.priority{border-radius:999px;padding:2px 8px;font-size:11px;font-weight:900;white-space:nowrap}.priority.high{background:#e8f6ee;color:#176b3a}.priority.mid{background:#eef5fb;color:#1f5f8f}.priority.low{background:#f0f2f5;color:#5d6875}.hypothesisTriad{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:10px}.hypothesisTriad div{background:#f8fafc;border:1px solid #e1e8ef;border-radius:6px;padding:8px;min-width:0}.hypothesisTriad b{display:block;color:#17202a;font-size:12px;margin-bottom:3px}.hypothesisTriad p{margin:0;color:#3c4b5a;font-size:12px;line-height:1.5}.reviewPanel{background:#fff;border:1px solid #dce3ea;border-radius:8px;overflow:hidden}.reviewPanel h3{margin:0;padding:10px 12px;border-bottom:1px solid #e5ebf0;background:#fbfcfd;color:#17202a;font-size:15px}.reviewBody{padding:12px}.watchStep{border-left:4px solid #23699a;padding:9px 10px;background:#fbfcfd;border-radius:6px;margin-bottom:8px}.watchStep b{display:block;color:#17202a}.watchStep p{margin:3px 0 0;color:#52606d;font-size:12px}.fixItem{border-left:4px solid #9a6700;background:#fffaf0;border-radius:6px;padding:8px 10px;margin-bottom:8px;min-width:0}.fixItem.high{border-left-color:#b42318;background:#fff7f6}.fixItem b{color:#17202a}.fixItem p{margin:3px 0 0;color:#52606d;font-size:12px;overflow-wrap:anywhere}.reviewSummary{padding:10px 12px;background:#fbfcfd;border-top:1px solid #e5ebf0;color:#52606d;font-size:12px}
.industryApp{min-height:calc(100vh - 154px);display:grid;grid-template-columns:210px minmax(0,1fr);border:1px solid #263028;border-radius:8px;overflow:hidden;background:#f4f5f2;color:#171a18}
.industryRail{background:#101612;color:#f7faf7;padding:16px 12px;display:flex;flex-direction:column;min-height:680px}.industryBrand{display:flex;gap:10px;align-items:center;padding:2px 6px 18px}.industryMark{width:34px;height:34px;display:grid;place-items:center;border-radius:6px;background:#d9f45b;color:#171a18;font-weight:950}.industryBrand strong{display:block;font-size:14px}.industryBrand small{display:block;color:#98a39b;font-size:9px;line-height:1.45;margin-top:2px}.industryNav{display:grid;gap:3px}.industryNav button{width:100%;border:0;background:transparent;color:#aab3ac;display:grid;grid-template-columns:19px minmax(0,1fr) auto;align-items:center;gap:8px;min-height:40px;padding:0 10px;text-align:left;border-radius:5px;font-size:12px}.industryNav button:hover{background:#1d261f;color:#fff}.industryNav button.active{background:#263422;color:#fff;box-shadow:inset 3px 0 0 #d9f45b}.industryNavIcon{font:700 10px ui-monospace,SFMono-Regular,Menlo,monospace;color:#d9f45b}.industryNavCount{font:600 9px ui-monospace,SFMono-Regular,Menlo,monospace;color:#78837b}.industryRailNote{margin-top:auto;border-top:1px solid #2b342e;padding:13px 7px 2px;color:#94a097;font-size:9px;line-height:1.6}.industryRailNote b{display:block;color:#eef4ef;font-size:11px}
.industryWorkspace{min-width:0;background:#f4f5f2}.industryToolbar{height:56px;padding:0 22px;border-bottom:1px solid #d9ddd8;display:flex;align-items:center;justify-content:space-between;gap:14px;background:rgba(244,245,242,.96)}.industrySearch{width:min(480px,70%);height:36px;border:1px solid #d1d6d1;background:#fff;border-radius:6px;display:flex;align-items:center;gap:8px;padding:0 11px}.industrySearch input{border:0;outline:0;background:transparent;flex:1;min-width:0;color:#171a18}.industrySearch kbd{font-size:9px}.industryToolbarMeta{font-size:10px;color:#68706a;white-space:nowrap}.industryContent{padding:22px;max-width:1240px;margin:0 auto}.industryPageHead{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:16px}.industryEyebrow{color:#16835c;font:700 10px ui-monospace,SFMono-Regular,Menlo,monospace;text-transform:uppercase}.industryPageHead h2{font-size:29px;line-height:1.15;margin:5px 0;color:#171a18}.industryPageHead p{margin:0;color:#68706a;font-size:12px;line-height:1.65}.industryStats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid #d9ddd8;background:#fff;border-radius:7px;overflow:hidden;margin-bottom:14px}.industryStat{padding:13px 16px;border-right:1px solid #d9ddd8}.industryStat:last-child{border-right:0}.industryStat b{display:block;font:800 18px ui-monospace,SFMono-Regular,Menlo,monospace}.industryStat span{font-size:9px;color:#68706a}
.industryCommand{background:#111713;color:#f6faf5;border:1px solid #303a33;border-radius:8px;padding:18px;display:grid;grid-template-columns:minmax(230px,.62fr) minmax(0,1.38fr);gap:20px;margin-bottom:14px}.industryCommandCopy{align-self:center}.industryCommandCopy h3{font-size:23px;margin:7px 0;color:#fff}.industryCommandCopy p{font-size:11px;color:#aeb9b0;line-height:1.7}.acidButton{background:#d9f45b!important;color:#151b16!important;border-color:#d9f45b!important}.industryBranchGrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.industryBranch{border:1px solid #354039;border-top:3px solid var(--branch,#d9f45b);background:#171e19;border-radius:6px;padding:9px;min-width:0}.industryBranch small{color:#809086;font-size:8px}.industryBranch b{display:block;color:#f2f6f2;font-size:11px;margin:3px 0 7px}.industryLeaf{display:block;width:100%;border:1px solid #303a33;background:#111713;color:#bdc7bf;padding:5px 6px;margin-top:5px;border-radius:3px;text-align:left;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.industryLeaf:hover{border-color:#d9f45b;color:#fff}
.industrySwitcher{display:flex;gap:6px;overflow:auto;margin:0 0 12px}.industrySwitcher button{flex:none;background:#fff;border-color:#cfd5d0;color:#59635c;font-size:10px}.industrySwitcher button.active{background:#171a18;color:#fff;border-color:#171a18}.industryMatrix{border:1px solid #d9ddd8;background:#fff;border-radius:7px;overflow:hidden}.industryMatrixHead,.industryMatrixRow{display:grid;grid-template-columns:52px 170px repeat(4,minmax(130px,1fr));border-bottom:1px solid #e0e4e0}.industryMatrixHead{background:#eef0ec;color:#68706a;font-size:9px;font-weight:800}.industryMatrixHead>*{padding:8px 10px}.industryMatrixRow:last-child{border-bottom:0}.industryMatrixRow.active{background:#f5f8e7}.industryMatrixRow>*{padding:11px 10px;min-width:0}.industryMatrixRow .index{font:800 11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#96ae18}.industryMatrixTitle button{border:0;background:transparent;padding:0;color:#171a18;text-align:left;font-weight:850}.industryMatrixTitle small{display:block;color:#68706a;font-size:9px;margin-top:3px}.industryCellLabel{display:block;color:#7a857d;font-size:8px;margin-bottom:5px}.industryNode{display:block;border:1px solid #d9ddd8;background:#fafbf9;border-radius:3px;padding:5px 6px;margin-bottom:4px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.industrySplit{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;margin-top:14px}.industryBlock{border:1px solid #d9ddd8;background:#fff;border-radius:7px;overflow:hidden}.industryBlockHead{padding:12px 14px;border-bottom:1px solid #d9ddd8;display:flex;align-items:center;justify-content:space-between;gap:10px}.industryBlockHead h3{margin:0;font-size:13px}.industryBlockBody{padding:13px 14px}.industryFocus{border-left:4px solid #ef6a4b}.industryFocus h3{font-size:18px;margin:0 0 7px}.industryFocus p{font-size:11px;color:#68706a;line-height:1.7}.routeLine{display:flex;align-items:center;gap:5px;overflow:auto;padding:7px 0}.routeNode{flex:none;border:1px solid #d9ddd8;background:#f7f8f6;border-radius:4px;padding:6px 8px;font-size:9px}.routeArrow{color:#9ca59e}.industryLibrary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.industryCard{border:1px solid #d9ddd8;background:#fff;border-radius:7px;padding:15px;text-align:left;min-height:148px}.industryCard:hover{border-color:#aeb7af;box-shadow:0 8px 18px rgba(28,33,30,.06)}.industryCardCode{color:#16835c;font:700 9px ui-monospace,SFMono-Regular,Menlo,monospace}.industryCard h3{margin:12px 0 5px;font-size:14px}.industryCard p{color:#68706a;font-size:10px;line-height:1.6}.industryCardMeta{display:flex;justify-content:space-between;gap:8px;color:#7c867f;font-size:9px}.industryCompanyTable{width:100%;min-width:760px;border:1px solid #d9ddd8}.industryCompanyTable th{background:#eef0ec}.industryCompanyTable td,.industryCompanyTable th{border-color:#e0e4e0;font-size:10px}.industryCompanyTable tbody tr{cursor:pointer}.industryCompanyTable tbody tr:hover td{background:#f6f8f3}.industrySearchResults{display:grid;gap:8px}.industrySearchResult{border:1px solid #d9ddd8;background:#fff;border-radius:6px;padding:12px;text-align:left}.industrySearchResult b{display:block}.industrySearchResult span{color:#68706a;font-size:10px}.industryEmpty{border:1px dashed #bfc6c0;background:#fff;padding:24px;text-align:center;color:#68706a;border-radius:7px}.industryRefs{margin-top:13px;color:#7c867f;font-size:9px}.industryRefs a{color:#496a55}
.industryCard h3{font-size:15px}.industryCard p{color:#5f6962;font-size:12px;line-height:1.7}.industryCardMeta,.industrySearchResult span{font-size:10px}.industryCompanyTable td,.industryCompanyTable th{font-size:11px;line-height:1.5}.industryRefs{margin-top:16px;font-size:10px;line-height:1.6}.industryNode,.routeNode{font-size:10px}
.intelRegime{display:grid;grid-template-columns:minmax(0,1fr) 180px;border:1px solid #d9ddd8;background:#fff;border-radius:7px;overflow:hidden;margin-bottom:14px}.intelRegimeMain{padding:18px 20px}.intelRegimeMain h3{margin:5px 0 7px;font-size:21px}.intelRegimeMain p{margin:0;color:#5d6860;font-size:13px;line-height:1.7}.intelScore{border-left:1px solid #d9ddd8;background:#f8f9f6;padding:18px;display:grid;align-content:center;gap:4px}.intelScore b{font:850 28px ui-monospace,SFMono-Regular,Menlo,monospace}.intelScore span{font-size:10px;color:#68706a}.intelStatus{display:inline-flex;width:max-content;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:800}.intelStatus.watch{background:#fff4df;color:#8a5a00}.intelStatus.confirmed{background:#e8f6ee;color:#176b3a}.intelStatus.weakening,.intelStatus.rejected{background:#fdecea;color:#a52a20}
.intelSignal{border:1px solid #d9ddd8;background:#fff;border-radius:7px;overflow:hidden;margin-bottom:14px}.intelSignalHead{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:16px 18px;border-bottom:1px solid #e1e5e1}.intelSignalHead h3{margin:4px 0 0;font-size:18px}.intelMeta{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.intelMeta span{border:1px solid #d9ddd8;border-radius:999px;padding:3px 8px;font-size:10px;white-space:nowrap}.intelTriad{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.intelTriad>div{padding:15px 17px;border-right:1px solid #e1e5e1}.intelTriad>div:last-child{border-right:0}.intelTriad h4{margin:0 0 7px;font-size:12px}.intelTriad p{margin:0;color:#4f5b53;font-size:12px;line-height:1.75}.intelChecks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.intelCheck{border:1px solid #d9ddd8;border-radius:5px;padding:10px;background:#fafbf9}.intelCheckTop{display:flex;justify-content:space-between;gap:8px;font-size:11px;font-weight:800}.intelCheck p{margin:4px 0 0;color:#657068;font-size:10px;line-height:1.55}.intelPending{color:#9a6700}.intelVerified{color:#176b3a}
.intelSource{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:10px;align-items:start;padding:10px 0;border-bottom:1px solid #e7eae7}.intelSource:last-child{border-bottom:0}.sourceTier{width:28px;height:28px;display:grid;place-items:center;border-radius:5px;background:#eef0ec;font-weight:900;font-size:11px}.sourceTier.tierD{background:#fff4df;color:#8a5a00}.intelSource a{color:#17202a;font-weight:800;font-size:12px;text-decoration:none}.intelSource p{margin:3px 0 0;color:#68706a;font-size:10px;line-height:1.5}.intelSource time{font-size:9px;color:#7c867f;white-space:nowrap}.intelCaution{border-left:4px solid #d28a16;background:#fff9ed;padding:12px 14px;border-radius:5px;color:#604713;font-size:11px;line-height:1.65;margin-top:10px}.intelWatchlist{display:flex;gap:6px;flex-wrap:wrap}.intelWatchlist span{border:1px solid #d9ddd8;background:#f7f8f6;border-radius:4px;padding:5px 8px;font-size:10px}.sourceRegistry{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.sourceRegistryItem{border:1px solid #d9ddd8;background:#fff;border-radius:5px;padding:11px}.sourceRegistryItem b{font-size:11px}.sourceRegistryItem p{margin:4px 0 0;color:#68706a;font-size:10px;line-height:1.55}
.intelAuthorGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:14px}.intelAuthorCard{border:1px solid #d9ddd8;background:#fff;border-radius:7px;padding:16px;display:flex;flex-direction:column;min-height:240px}.intelAuthorTop{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.intelAuthor{display:flex;gap:9px;align-items:center}.intelAvatar{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:#171a18;color:#d9f45b;font-weight:900}.intelAuthor b{display:block;font-size:12px}.intelAuthor small{color:#68706a;font-size:9px}.intelAuthorCard h3{margin:14px 0 8px;font-size:16px}.intelAuthorCard>p{margin:0;color:#4f5b53;font-size:12px;line-height:1.75}.intelSystemView{margin-top:12px;padding:10px 11px;background:#f6f8f3;border-left:3px solid #16835c;color:#37433b;font-size:11px;line-height:1.65}.intelCardFoot{margin-top:auto;padding-top:13px;display:flex;align-items:center;justify-content:space-between;gap:10px}.intelTags{display:flex;gap:5px;flex-wrap:wrap}.intelTags span{background:#eef0ec;border-radius:4px;padding:3px 6px;color:#5d6860;font-size:9px}.intelOriginal{color:#2f6fed;font-size:10px;font-weight:700;text-decoration:none;white-space:nowrap}.intelValidationList{display:grid;gap:7px}.intelValidationRow{display:grid;grid-template-columns:minmax(120px,.35fr) minmax(0,1fr) 62px;gap:8px;padding:9px 10px;border:1px solid #d9ddd8;border-radius:5px;background:#fff;font-size:10px;align-items:center}
.cadenceList{border:1px solid #dce3ea;border-radius:7px;overflow:hidden;margin-bottom:18px}.cadenceRow{display:grid;grid-template-columns:88px minmax(0,1fr) 72px;gap:12px;align-items:start;padding:12px 14px;border-bottom:1px solid #e7edf2}.cadenceRow:last-child{border-bottom:0}.cadenceTime{font:800 12px ui-monospace,SFMono-Regular,Menlo,monospace;color:#1f5f8f}.cadenceRow b{font-size:13px}.cadenceRow p{margin:3px 0 0;color:#667586;font-size:11px;line-height:1.55}.cadenceStatus{justify-self:end;border-radius:999px;background:#fff4df;color:#8a5a00;padding:3px 7px;font-size:10px;font-weight:800;white-space:nowrap}.cadenceStatus.ready{background:#e8f6ee;color:#176b3a}
.formGrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.formGrid label,.singleAdd label{font-size:12px;color:#667586}.formGrid input,.formGrid select,.singleAdd input{width:100%;margin-top:3px;border:1px solid #cdd6df;border-radius:6px;background:#fff;padding:8px 10px;color:#17202a}.singleAdd{display:grid;gap:10px;max-width:520px}.resolveHint{border:1px solid #dce3ea;background:#f7fafc;border-radius:8px;padding:10px;color:#2f3d4c}
.chartShell{border:1px solid #dce3ea;border-radius:8px;background:#fff;padding:12px}.quoteStats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.quoteStat{border:1px solid #e1e8ef;border-radius:8px;padding:8px;background:#fbfcfd}.quoteStat b{display:block;color:#17202a;font-size:18px}.chartCanvas{width:100%;height:360px;display:block;background:#fff;border:1px solid #edf1f5;border-radius:6px}.chartSource{margin-top:8px;color:#667586;font-size:12px}
.archImg{display:block;width:100%;height:auto;border:1px solid #d8e2ea;border-radius:8px;background:#f7fafc}
.drawerMask{position:fixed;inset:0;background:rgba(16,24,32,.38);display:none;z-index:20}.drawerMask.open{display:block}.drawer{position:fixed;top:0;right:0;width:min(940px,94vw);height:100vh;background:#fff;box-shadow:-18px 0 42px rgba(16,24,32,.20);z-index:21;transform:translateX(102%);transition:transform .18s ease;display:flex;flex-direction:column}.drawer.open{transform:translateX(0)}.drawerHead{padding:14px 18px;border-bottom:1px solid #dce3ea;background:#f7f9fb;display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.drawerHead h2{margin:0;color:#17202a;font-size:19px}.drawerBody{padding:17px 20px;overflow:auto;color:#1f2933}.drawerBody p,.drawerBody li,.drawerBody td{color:#1f2933}.drawerBody strong{color:#111827;font-weight:800}.drawerBody h1{font-size:22px;color:#111827}.drawerBody h2{font-size:18px;color:#17202a;border-bottom:2px solid #dce3ea;padding-bottom:5px;margin:22px 0 10px}.drawerBody h3{font-size:15px;color:#25364a}.drawerBody ul,.drawerBody ol{margin:8px 0 14px;padding-left:20px}.drawerBody li{margin:0 0 7px;padding-left:2px}.drawerBody li p{margin:0}.drawerBody table{font-size:13px;margin:10px 0;min-width:760px}.drawerBody a{color:#1f5f8f}
@media(max-width:1100px){.brandRow{flex-wrap:wrap;align-items:flex-start}.statusbar{justify-content:flex-start}.commandRow{flex-wrap:wrap}.topActions{flex:1 1 100%;justify-content:flex-start}.sourceGrid{grid-template-columns:1fr}.quoteStats{grid-template-columns:repeat(2,minmax(0,1fr))}.decisionHero,.decisionLayout{grid-template-columns:1fr}.decisionGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.marketTape{grid-template-columns:repeat(3,minmax(126px,1fr))}.pulseGrid{grid-template-columns:1fr}.premarketGrid{grid-template-columns:1fr}.premarketColumn+.premarketColumn{border-left:0;border-top:1px solid #e5ebf0}.infraLayout{grid-template-columns:1fr}.infraSide{border-left:0;border-top:1px solid #e5ebf0}.chainMap{grid-template-columns:repeat(2,minmax(0,1fr))}.chainLayer:nth-child(2n){border-right:0}.candidateRow{grid-template-columns:42px minmax(140px,.9fr) 80px minmax(260px,1.4fr);}.candidateSignals,.candidateAction{grid-column:2 / -1}.candidateAction{display:flex;justify-content:flex-start}.auctionGrid{grid-template-columns:1fr}.auctionSide{border-left:0;border-top:1px solid #e5ebf0}.auctionTimeline{grid-template-columns:repeat(2,minmax(0,1fr))}.auctionStep:nth-child(2n){border-right:0}}
@media(max-width:900px){.researchHead{display:none}.researchRow{grid-template-columns:minmax(0,1fr) auto;gap:7px 10px}.researchDecision{grid-column:2;grid-row:1}.researchMain{grid-column:1 / -1}.rowActions{grid-column:2;grid-row:2;align-self:end}.summaryText{-webkit-line-clamp:3}.levelInline{gap:8px}.stockName{white-space:normal}.candidateHero{display:block}.candidateMeta{justify-content:flex-start;margin-top:7px}.candidateRow{grid-template-columns:36px minmax(0,1fr) 76px;}.candidateReasonsWrap,.candidateSignals{grid-column:2 / -1}.candidateAction{grid-column:3;grid-row:1}}
@media(max-width:700px){.brandRow,.commandRow{padding-left:12px;padding-right:12px}.brandBlock{display:block}.generated{margin-top:5px}.brand{font-size:24px}.commandRow{display:block}.nav{overflow-x:auto}.topActions{justify-content:flex-start;margin-top:8px}.main{padding:12px}.formGrid{grid-template-columns:1fr}.quoteStats{grid-template-columns:1fr}.decisionGrid,.hypothesisTriad{grid-template-columns:1fr}.decisionHero h1{font-size:22px}.chartCanvas{height:300px}.premarketHero{display:block}.briefDate{margin-top:7px}.marketTape{grid-template-columns:repeat(2,minmax(126px,1fr))}.hotStrip{grid-template-columns:repeat(2,minmax(130px,1fr))}.hotItem:nth-child(5n){border-right:1px solid #edf1f4}.hotItem:nth-child(2n){border-right:0}.chainHeroTop{display:block}.chainHero h2{font-size:24px}.trackTabs{padding:8px}.chainMap{grid-template-columns:1fr}.chainLayer{border-right:0;border-bottom:1px solid #e5ebf0}.candidateRow{grid-template-columns:30px minmax(0,1fr);}.candidateScore,.candidateAction{grid-column:2}.candidateAction{grid-row:auto}.quoteMini{white-space:normal}.auctionTimeline{grid-template-columns:1fr}.auctionStep{border-right:0;border-bottom:1px solid #e5ebf0}}
@media(max-width:1100px){.industryApp{grid-template-columns:176px minmax(0,1fr)}.industryContent{padding:16px}.industryCommand{grid-template-columns:1fr}.industryMatrix{overflow:auto}.industryMatrixHead,.industryMatrixRow{min-width:900px}.industrySplit{grid-template-columns:1fr}.industryLibrary{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.industryApp{display:block}.industryRail{min-height:0;padding:10px}.industryBrand,.industryRailNote{display:none}.industryNav{display:flex;overflow:auto}.industryNav button{flex:none;width:auto;grid-template-columns:16px auto}.industryNavCount{display:none}.industryToolbar{padding:0 10px}.industrySearch{width:100%}.industryToolbarMeta{display:none}.industryContent{padding:12px}.industryPageHead{display:block}.industryPageHead h2{font-size:24px}.industryStats{grid-template-columns:repeat(2,minmax(0,1fr))}.industryStat:nth-child(2){border-right:0}.industryStat:nth-child(-n+2){border-bottom:1px solid #d9ddd8}.industryBranchGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.industryLibrary{grid-template-columns:1fr}}
@media(max-width:800px){.intelRegime{grid-template-columns:1fr}.intelScore{border-left:0;border-top:1px solid #d9ddd8}.intelTriad{grid-template-columns:1fr}.intelTriad>div{border-right:0;border-bottom:1px solid #e1e5e1}.intelTriad>div:last-child{border-bottom:0}.intelChecks,.sourceRegistry,.intelAuthorGrid{grid-template-columns:1fr}.intelSignalHead{display:block}.intelMeta{justify-content:flex-start;margin-top:9px}.intelSource{grid-template-columns:34px minmax(0,1fr)}.intelSource time{grid-column:2}.intelValidationRow{grid-template-columns:1fr}.intelValidationRow span:last-child{justify-self:start}}
</style>
</head>
<body>
<header class="topbar">
  <div class="brandRow">
    <div class="brandBlock">
      <div class="brand">Alpha R&D</div>
      <div class="generated">生成时间 $generated_at</div>
    </div>
    <div class="statusbar" id="statusbar"></div>
  </div>
  <div class="commandRow">
    <nav class="nav">
      <button class="active" data-tab="overview">今日决策</button>
      <button data-tab="candidates">每日候选</button>
      <button data-tab="pulse">市场脉搏</button>
      <button data-tab="premarket">盘前消息</button>
      <button data-tab="auction">集合竞价</button>
      <button data-tab="industry">产业链知识</button>
      <button data-tab="review">周五复盘</button>
      <button data-tab="pool">选股池</button>
    </nav>
    <div class="topActions">
      <button class="ghost" data-action="cadence">更新日历</button>
      <button class="ghost" data-action="data-audit">数据检查</button>
      <button class="ghost" data-action="architecture">系统架构</button>
      <button class="ghost" data-action="optimize">优化</button>
      <button data-action="render">刷新</button>
    </div>
  </div>
</header>
<main class="main">
  <section class="panel active" id="overview"></section>
  <section class="panel" id="candidates"></section>
  <section class="panel" id="pulse"></section>
  <section class="panel" id="premarket"></section>
  <section class="panel" id="auction"></section>
  <section class="panel" id="industry"></section>
  <section class="panel" id="review"></section>
  <section class="panel" id="pool"></section>
</main>
<div class="drawerMask" id="drawerMask"></div>
<aside class="drawer" id="drawer">
  <div class="drawerHead">
    <div><h2 id="drawerTitle">预览</h2><div class="muted" id="drawerMeta"></div></div>
    <button class="ghost" data-action="close">关闭</button>
  </div>
  <div class="drawerBody" id="drawerBody"></div>
</aside>
<script id="data" type="application/json">$data</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const CUSTOM_KEY = 'alpha_rnd_custom_pool_v1';
const byRun = Object.fromEntries(DATA.runs.map(function(r){ return [r.id, r]; }));
const lookupRows = (DATA.stock_lookup && DATA.stock_lookup.rows) || [];
let currentTrackId = ((DATA.industry_chain && DATA.industry_chain.tracks && DATA.industry_chain.tracks[0]) || {}).id || '';
let currentIndustryView = 'today';
let industryQuery = '';
function h(v){ return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function(ch){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]); }); }
function actionCls(a){ return ['buy','sell','hold'].includes(a) ? a : 'unknown'; }
function customPool(){ try{return JSON.parse(localStorage.getItem(CUSTOM_KEY) || '[]')}catch(e){return []} }
function saveCustomPool(rows){ localStorage.setItem(CUSTOM_KEY, JSON.stringify(rows)); }
function stockKey(u){ return String(u.ticker || '').toUpperCase() || ('NAME:' + String(u.name || '').trim()); }
function allUniverse(){ const seen = new Set(); return DATA.universe.concat(customPool()).filter(function(u){ const key = stockKey(u); if(!key || key === 'NAME:' || seen.has(key)) return false; seen.add(key); return true; }); }
function findUniverseByTicker(ticker){ return allUniverse().find(function(u){ return String(u.ticker || '').toUpperCase() === String(ticker || '').toUpperCase(); }); }
function normalizeName(v){ return String(v || '').replace(/\s+/g,'').trim().toUpperCase(); }
function resolveStockName(input){
  const raw = String(input || '').trim();
  if(!raw) return null;
  const normalized = normalizeName(raw);
  const tracked = allUniverse().find(function(u){ return normalizeName(u.name) === normalized || normalizeName(u.ticker) === normalized; });
  if(tracked) return Object.assign({source:'tracked'}, tracked);
  const exact = lookupRows.find(function(r){ return normalizeName(r.name) === normalized || normalizeName(r.ticker) === normalized; });
  if(exact) return exact;
  return lookupRows.find(function(r){ return normalizeName(r.name).includes(normalized); }) || null;
}
function latestRun(ticker){ return DATA.runs.filter(function(r){ return r.ticker === ticker; }).sort(function(a,b){ return (b.report_date + b.created_at).localeCompare(a.report_date + a.created_at); })[0]; }
function decisionText(r){ if(!r) return '--'; return r.rating || (r.action === 'buy' ? '买入' : r.action === 'sell' ? '减持' : r.action === 'hold' ? '持有' : '--'); }
function cleanLevel(v){ return String(v || '').replace('不建议建仓','--'); }
function levelText(r){ if(!r) return '--'; return '<span class="small">止损 ' + h(cleanLevel(r.stop) || '--') + '</span><br><span class="small">目标 ' + h(cleanLevel(r.target) || '--') + '</span>'; }
function levelInline(r){ if(!r) return ''; return '<span>止损 ' + h(cleanLevel(r.stop) || '--') + '</span><span>目标 ' + h(cleanLevel(r.target) || '--') + '</span>'; }
function reportButtons(r, includePdf){ if(!r) return '--'; let out = '<div class="actions"><button class="tiny" data-action="report" data-run="' + r.id + '">研报</button>'; if(includePdf !== false && r.pdf_path){ out += '<button class="ghost tiny" data-action="copy" data-text="' + h(r.pdf_path) + '">PDF</button>'; } return out + '</div>'; }
function summaryText(r){ return h(r && r.front_summary ? r.front_summary : '等待下次周度任务生成首份研报'); }
function stockTitle(u){ return '<button class="stockLink" data-action="quote" data-ticker="' + h(u.ticker || '') + '" data-name="' + h(u.name || '') + '">' + h(u.name || '未命名') + '</button><br><span class="mono muted">' + h(u.ticker || '待补全') + '</span>'; }
function renderStatus(){
  const pending = DATA.outcomes.filter(function(o){ return o.status === 'pending'; }).length;
  const openTasks = DATA.tasks.filter(function(t){ return t.status === 'open'; }).length;
  const candidateCount = ((DATA.daily_candidates && DATA.daily_candidates.rows) || []).length;
  const audit = DATA.data_audit || {};
  const items = [['股票池', allUniverse().length], ['候选', candidateCount], ['数据', audit.status || '--'], ['研报', DATA.runs.length], ['待评估', pending], ['优化', openTasks]];
  document.getElementById('statusbar').innerHTML = items.map(function(x){ return '<span class="chip">' + h(x[0]) + '<b>' + h(x[1]) + '</b></span>'; }).join('');
}
function renderOverview(){
  const review = DATA.daily_review || {};
  const decision = review.decision || {};
  const audit = DATA.data_audit || {};
  const pulse = DATA.market_pulse || {};
  const market = review.market_overview || {};
  const sectors = review.sector_overview || {};
  const llm = review.llm_check || {};
  const candidates = (review.candidate_hypotheses || []).slice(0,6);
  const watch = review.watch_plan || [];
  const cards = [
    ['今日状态', decision.stance || '--', decision.action || '等待 Daily Review Agent 生成。'],
    ['集合竞价', decision.auction_stance || '--', '分数 ' + (decision.auction_score || '--') + '；用于判断开盘承接。'],
    ['市场脉搏', decision.pulse_phase || '--', '情绪分 ' + (decision.pulse_score || '--') + '；先定板块再看个股。'],
    ['数据可信度', decision.audit_status || audit.status || '--', audit.summary || '暂无数据审计结论。'],
  ].map(function(x){ return '<div class="decisionCard"><h3>' + h(x[0]) + '</h3><b>' + h(x[1]) + '</b><p>' + h(x[2]) + '</p></div>'; }).join('');
  const indexTape = (market.indices || []).map(function(idx){
    const pct = Number(idx.change_pct || 0); const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
    return '<div class="tapeItem"><span class="tapeName">' + h(idx.name || idx.ticker || '--') + '</span><span class="tapeValue ' + cls + '">' + (pct > 0 ? '+' : '') + h(pct.toFixed(2)) + '%</span><div class="small muted">开盘 ' + h(idx.open_gap_pct === null || idx.open_gap_pct === undefined ? '--' : Number(idx.open_gap_pct).toFixed(2) + '%') + ' · 成交 ' + h(idx.amount_yi === null || idx.amount_yi === undefined ? '--' : Number(idx.amount_yi).toFixed(1) + '亿') + '</div></div>';
  }).join('') || '<div class="empty">暂无指数实时数据。</div>';
  function sectorMini(rows){
    return (rows || []).slice(0,4).map(function(row){
      const pct = Number(row.change_pct || 0); const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
      return '<div class="pulseItem"><div><div class="pulseName">' + h(row.name) + '</div><div class="pulseMeta">' + h(row.label || '') + ' · 领涨 ' + h(row.leader_stock || '--') + '</div></div><div class="' + cls + '">' + (pct > 0 ? '+' : '') + h(pct.toFixed(2)) + '%</div><div><b>' + h(Number(row.rank_score || 0).toFixed(1)) + '</b><div class="pulseMeta">评分</div></div><div class="pulseHint">主力 ' + h(Number(row.main_inflow_yi || 0).toFixed(2)) + ' 亿<br>' + h(row.action_hint || '') + '</div></div>';
    }).join('') || '<div class="empty">暂无板块。</div>';
  }
  const sectorBlocks = [
    ['主线强化', sectors.leaders],
    ['启动预警', sectors.starters],
    ['性价比观察', sectors.value_zones],
    ['高位拥挤', sectors.crowded],
  ].map(function(x){ return '<div class="pulseBlock"><h3>' + h(x[0]) + '</h3><div class="pulseList">' + sectorMini(x[1]) + '</div></div>'; }).join('');
  const hypotheses = candidates.map(function(row){
    const priorityCls = row.priority === '重点观察' ? 'high' : row.priority === '普通观察' ? 'mid' : 'low';
    const tags = (row.tags || []).map(function(t){ return '<span class="softChip">' + h(t) + '</span>'; }).join('');
    const quote = row.quote || {};
    const gate = row.homepage_gate || {};
    const pct = quote.change_pct === null || quote.change_pct === undefined ? '--' : ((Number(quote.change_pct) > 0 ? '+' : '') + Number(quote.change_pct).toFixed(2) + '%');
    return '<div class="hypothesisCard"><div class="hypothesisTop"><div><button class="stockLink hypothesisName" data-action="quote" data-ticker="' + h(row.ticker) + '" data-name="' + h(row.name) + '">' + h(row.name) + '</button><div class="hypothesisMeta">假设分 ' + h(Number(row.hypothesis_score || row.score || 0).toFixed(1)) + ' · 原始#' + h(row.rank) + ' · ' + h(row.ticker) + ' · ' + h(row.sector || row.theme || '') + ' · ' + h(pct) + '</div></div><span class="priority ' + priorityCls + '">' + h(row.priority || '观察') + '</span></div><div class="chipCloud" style="margin-top:8px">' + tags + '</div><div class="gateNote">' + h(gate.reason || '板块匹配后进入首页观察。') + '</div><div class="hypothesisTriad"><div><b>为什么看</b><p>' + h(row.why || '') + '</p></div><div><b>触发条件</b><p>' + h(row.trigger || '') + '</p></div><div><b>失效条件</b><p>' + h(row.invalid || '') + '</p></div></div></div>';
  }).join('') || '<div class="empty">今天没有足够干净的个股观察假设，先看大盘和板块，不硬凑清单。</div>';
  const watchHtml = watch.map(function(x){ return '<div class="watchStep"><b>' + h(x.title) + '</b><p>' + h(x.detail) + '</p></div>'; }).join('') || '<div class="empty">暂无今日观察计划。</div>';
  const reviewSummary = (((review.review || {}).summary) || '复盘样本仍在积累。');
  const llmHtml = '<div class="llmReview"><div class="llmReviewHead"><b>LLM 二次核验</b><span class="softChip ' + h(llm.status || 'skipped') + '">' + h(llm.status || 'skipped') + '</span></div><p>' + h(llm.summary || '未运行') + '</p><div class="muted small">模型：' + h(llm.model || '--') + '</div></div>';
  document.getElementById('overview').innerHTML = '<div class="decisionDesk"><div class="decisionHero"><div><h1>' + h(decision.level || '今日决策') + '</h1><p>' + h(decision.one_liner || '先看大盘，再看板块，最后才看个股。') + '</p><div class="decisionMeta"><span class="softChip">日期 ' + h(review.trade_date || '') + '</span><span class="softChip">候选 ' + h(((DATA.daily_candidates || {}).rows || []).length) + '</span><span class="softChip">主线 ' + h(pulse.phase || '--') + '</span><span class="softChip ' + h(audit.status || '') + '">数据 ' + h(audit.status || '--') + '</span></div></div><div class="decisionScoreCard"><b>Daily Review Agent</b><span>规则判断 + DeepSeek 二次核验。首页只呈现大盘、板块和观察假设。</span><button class="ghost tiny" data-tab-jump="pulse" style="margin-top:10px">看完整板块</button></div></div><div class="decisionGrid">' + cards + '</div><div class="reviewPanel"><h3>今日大盘 · 实时状态</h3><div class="marketTape">' + indexTape + '</div><div class="reviewSummary">' + h(market.expected_path || '') + ' · ' + h(market.note || '') + '</div></div><div class="pulseGrid">' + sectorBlocks + '</div><div class="decisionLayout"><div class="reviewPanel"><h3>板块内个股观察假设</h3><div class="hypothesisList">' + hypotheses + '</div></div><div class="reviewPanel"><h3>今天怎么看</h3><div class="reviewBody">' + watchHtml + '</div><h3>复盘状态</h3><div class="reviewSummary">' + h(reviewSummary) + '</div>' + llmHtml + '</div></div></div>';
}
function strategyName(k){
  return ({emotion:'情绪', sector:'板块', relative_strength:'强弱', capital:'资金', event:'事件', industry_chain:'产业链', technical:'技术', quality:'质量', market_gap:'指数开盘', market_follow:'开盘承接', pool_breadth:'股票池红盘', pool_leadership:'强势队形', crowding_risk:'拥挤风险'})[k] || k;
}
function topStrategyHtml(scores){
  const items = Object.entries(scores || {}).sort(function(a,b){ return Number(b[1])-Number(a[1]); }).slice(0,4);
  return '<div class="scoreBars">' + items.map(function(x){
    const value = Math.max(0, Math.min(100, Number(x[1] || 0)));
    return '<div class="scoreBar"><span>' + h(strategyName(x[0])) + '</span><div class="barTrack"><div class="barFill" style="width:' + value + '%"></div></div><b>' + h(value.toFixed(0)) + '</b></div>';
  }).join('') + '</div>';
}
function candidateQuote(q){
  if(!q || q.change_pct === null || q.change_pct === undefined) return '<span class="muted small">行情降级</span>';
  const pct = Number(q.change_pct || 0);
  const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
  return '<span class="' + cls + '">' + (pct > 0 ? '+' : '') + h(pct.toFixed(2)) + '%</span><br><span class="quoteMini">成交 ' + h((Number(q.amount_yi || 0)).toFixed(1)) + ' 亿 · 换手 ' + h(q.turnover_pct === null || q.turnover_pct === undefined ? '--' : Number(q.turnover_pct).toFixed(1) + '%') + '</span>';
}
function renderCandidates(){
  const data = DATA.daily_candidates || {};
  const rows = data.rows || [];
  const universe = data.universe || data.market || {};
  if(!rows.length){
    document.getElementById('candidates').innerHTML = '<div class="empty">暂无每日候选。运行 candidates 模式后会生成。</div>';
    return;
  }
  const market = data.market || {};
  const refs = (data.references || []).map(function(r){ return '<a href="' + h(r.url) + '" target="_blank" rel="noopener">' + h(r.name) + '</a>'; }).join(' · ');
  const weightText = Object.entries(data.weights || {}).map(function(x){ return strategyName(x[0]) + ' ' + Number(x[1]).toFixed(2); }).join(' / ');
  const cards = rows.map(function(row){
    const flags = (row.risk_flags || []).map(function(f){ return '<span class="softChip">' + h(f.label) + '</span>'; }).join('');
    const reasons = (row.reasons || []).slice(0,4).map(function(x){ return '<li>' + h(x) + '</li>'; }).join('');
    return '<div class="candidateRow"><div class="candidateRank">#' + h(row.rank) + '</div><div class="candidateStock"><button class="stockLink candidateName" data-action="quote" data-ticker="' + h(row.ticker) + '" data-name="' + h(row.name) + '">' + h(row.name) + '</button><div class="mono muted">' + h(row.ticker) + '</div><div class="candidateTheme">' + h(row.sector || '') + ' · ' + h(row.theme || '') + '</div></div><div class="candidateScore"><b>' + h(Number(row.score || 0).toFixed(1)) + '</b><span>' + h(row.bucket) + '</span></div><div class="candidateReasonsWrap"><ul class="candidateReasons">' + reasons + '</ul>' + (flags ? '<div class="riskFlags">' + flags + '</div>' : '') + '</div><div class="candidateSignals">' + topStrategyHtml(row.strategy_scores || {}) + '</div><div class="candidateAction">' + candidateQuote(row.quote || {}) + '</div></div>';
  }).join('');
  document.getElementById('candidates').innerHTML = '<div class="section"><div class="candidateHero"><div><h2>全市场每日候选</h2><p>' + h(market.description || '先扫描全市场活跃股票，再按 A 股题材、资金、情绪、产业链位置与风险约束综合排序。') + '</p></div><div class="candidateMeta"><span class="softChip">日期 ' + h(data.trade_date || '') + '</span><span class="softChip">市场阶段 ' + h(market.phase || 'unknown') + '</span><span class="softChip">扫描 ' + h(universe.market_rows_scanned || universe.universe_size || '--') + '</span><span class="softChip">观察池重合 ' + h(universe.tracked_overlap || 0) + '</span></div></div><div class="candidateList">' + cards + '</div><div class="candidateRefs">候选宇宙：' + h(universe.universe_source || 'unknown') + '；现有选股池不参与加权，仅显示自然重合结果。<br>策略参考：' + refs + '<br>当前权重：' + h(weightText) + '</div></div>';
}
function pulseRows(rows){
  return (rows || []).slice(0,6).map(function(row){
    const pct = Number(row.change_pct || 0); const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
    return '<div class="pulseItem"><div><div class="pulseName">' + h(row.name) + '</div><div class="pulseMeta">' + h(row.kind === 'concept' ? '概念' : '行业') + ' · ' + h(row.stage) + ' · 领涨 ' + h(row.leader_stock || '--') + '</div></div><div class="' + cls + '">' + (pct > 0 ? '+' : '') + h(pct.toFixed(2)) + '%</div><div><b>' + h(Number(row.rank_score || 0).toFixed(1)) + '</b><div class="pulseMeta">评分</div></div><div class="pulseHint">主力 ' + h(Number(row.main_inflow_yi || 0).toFixed(2)) + ' 亿 · 扩散 ' + h(Math.round(Number(row.breadth || 0) * 100)) + '%<br>' + h(row.action_hint || '') + '</div></div>';
  }).join('') || '<div class="empty">暂无符合条件的板块。</div>';
}
function renderMarketPulse(){
  const pulse = DATA.market_pulse || {};
  const stance = pulse.stance || {};
  const sections = pulse.sections || {};
  const sourceLinks = (pulse.sources || []).map(function(s){ return '<a href="' + h(s.url || '#') + '" target="_blank" rel="noopener">' + h(s.name) + '</a>'; }).join(' · ');
  const blocks = [
    ['主线板块', sections.leaders],
    ['启动预警', sections.starters],
    ['性价比观察', sections.value_zones],
    ['高位拥挤', sections.crowded],
    ['退潮板块', sections.retreat],
  ].map(function(x){ return '<div class="pulseBlock"><h3>' + h(x[0]) + '</h3><div class="pulseList">' + pulseRows(x[1]) + '</div></div>'; }).join('');
  document.getElementById('pulse').innerHTML = '<div class="section"><div class="pulseHero"><div><h2>市场脉搏 · ' + h(pulse.phase || '待更新') + '</h2><p>' + h(pulse.summary || '等待市场脉搏官生成。') + '</p><div class="candidateMeta" style="justify-content:flex-start;margin-top:8px"><span class="softChip">日期 ' + h(pulse.trade_date || '') + '</span><span class="softChip">上涨板块 ' + h(Math.round(Number(stance.positive_ratio || 0) * 100)) + '%</span><span class="softChip">资金流入 ' + h(Math.round(Number(stance.fund_positive_ratio || 0) * 100)) + '%</span><span class="softChip">' + h((pulse.source_status || {}).status || 'unknown') + '</span></div></div><div class="pulseScore"><b>' + h(pulse.score || '--') + '</b><span class="muted small">情绪分</span></div></div><div class="pulseGrid">' + blocks + '</div><div class="pulseSources">数据源：' + sourceLinks + '<br>方法：先判断情绪周期，再分主升、启动、拥挤、退潮和性价比观察；社媒源只作叙事扩散，不能替代资金和行情。</div></div>';
}
function renderAuction(){
  const brief = DATA.call_auction || {};
  const pred = brief.prediction || {};
  const steps = (brief.time_windows || []).map(function(x){
    return '<div class="auctionStep"><div class="auctionTime">' + h(x.time) + '</div><span class="auctionLabel">' + h(x.label) + '</span><p>' + h(x.meaning) + '</p><div class="chipCloud" style="margin-top:8px">' + chips(x.watch || []) + '</div></div>';
  }).join('');
  const marketRows = (brief.market || []).map(function(x){
    const gap = Number(x.open_gap_pct || 0); const now = Number(x.current_change_pct || 0); const cls = now > 0 ? 'rise' : now < 0 ? 'fall' : '';
    return '<div class="factorItem"><div class="factorTop"><span class="factorName">' + h(x.name) + '</span><span class="' + cls + '">' + (now > 0 ? '+' : '') + h(now.toFixed(2)) + '%</span></div><div class="factorLogic">开盘缺口 ' + (gap > 0 ? '+' : '') + h(gap.toFixed(2)) + '% · 开盘后 ' + h(Number(x.from_open_pct || 0).toFixed(2)) + '%</div><div class="factorBad">成交额 ' + h(Number(x.amount_yi || 0).toFixed(1)) + ' 亿 · ' + h(x.quote_time || '') + '</div></div>';
  }).join('');
  const stocks = (brief.stocks || []).map(function(x){
    const chg = Number(x.current_change_pct || 0); const cls = chg > 0 ? 'rise' : chg < 0 ? 'fall' : '';
    return '<tr><td class="stockCell"><button class="stockLink" data-action="quote" data-ticker="' + h(x.ticker) + '" data-name="' + h(x.name) + '">' + h(x.name) + '</button><br><span class="mono muted">' + h(x.ticker) + '</span></td><td class="' + cls + '">' + (chg > 0 ? '+' : '') + h(chg.toFixed(2)) + '%</td><td>' + h(Number(x.open_gap_pct || 0).toFixed(2)) + '%</td><td>' + h(Number(x.from_open_pct || 0).toFixed(2)) + '%</td><td>' + h(Number(x.amount_yi || 0).toFixed(1)) + ' 亿</td><td>' + chips(x.features || []) + '</td><td>' + h(x.decision_hint || '') + '</td></tr>';
  }).join('');
  const contributions = Object.entries(pred.rule_contributions || {}).map(function(x){
    const val = Number(x[1] || 0); const cls = val >= 0 ? 'rise' : 'fall';
    return '<div class="roadItem"><b>' + h(strategyName(x[0])) + '</b><div class="' + cls + '">' + (val > 0 ? '+' : '') + h(val.toFixed(2)) + '</div></div>';
  }).join('');
  const risks = (pred.risk_flags || []).map(function(x){ return '<span class="softChip">' + h(x) + '</span>'; }).join('') || '<span class="muted small">暂无关键风险标记</span>';
  const reasons = (pred.reasons || []).map(function(x){ return '<li>' + h(x) + '</li>'; }).join('');
  const outcome = brief.outcome ? '<div class="roadItem"><b>收盘校准 ' + h(brief.outcome.score || '--') + '</b><div class="muted small">' + h(brief.outcome.diagnosis || '') + '</div></div>' : '<div class="roadItem"><b>收盘校准待生成</b><div class="muted small">收盘后自动对比预测和实际走势，并修正规则权重。</div></div>';
  const refs = (brief.references || []).map(function(r){ return '<a href="' + h(r.url) + '" target="_blank" rel="noopener">' + h(r.name) + '</a>'; }).join(' · ');
  document.getElementById('auction').innerHTML = '<div class="section"><div class="auctionHero"><h2>' + h(brief.title || '集合竞价观察') + ' · ' + h(pred.stance || '待预测') + '</h2><p>' + h(pred.expected_path || brief.summary || '') + '</p><div class="candidateMeta" style="justify-content:flex-start;margin-top:8px"><span class="softChip">日期 ' + h(brief.trade_date || '') + '</span><span class="softChip">分数 ' + h(pred.score || '--') + '</span><span class="softChip">置信 ' + h(pred.confidence || 0) + '</span><span class="softChip">' + h((brief.source_status && brief.source_status.status) || 'unknown') + '</span></div></div><div class="auctionTimeline">' + steps + '</div><div class="auctionGrid"><div class="auctionMain"><div class="auctionBlock"><h3>大盘竞价与走势预测</h3><div class="factorList">' + marketRows + '</div></div><div class="auctionBlock auctionWatch"><h3>股票池集合竞价特征</h3><table><thead><tr><th>标的</th><th>现涨跌</th><th>开盘缺口</th><th>开盘后</th><th>成交额</th><th>特征</th><th>处理</th></tr></thead><tbody>' + stocks + '</tbody></table></div><div class="auctionRefs">' + h(brief.data_note || '') + '<br>参考：' + refs + ' · 更新 ' + h(String(brief.generated_at || '').replace('T',' ')) + '</div></div><aside class="auctionSide"><div class="auctionBlock"><h3>预测理由</h3><ol class="learningList">' + reasons + '</ol><div class="riskFlags">' + risks + '</div></div><div class="auctionBlock"><h3>规则贡献</h3>' + contributions + '</div><div class="auctionBlock"><h3>校准</h3>' + outcome + '</div></aside></div></div>';
}
function renderPremarket(){
  const brief = DATA.premarket || {};
  const stance = brief.stance || {level:'待更新', summary:'盘前数据尚未生成。'};
  const tape = (brief.indices || []).map(function(item){
    const pct = Number(item.change_pct || 0);
    const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
    const sign = pct > 0 ? '+' : '';
    return '<div class="tapeItem"><span class="tapeName">' + h(item.name) + '</span><span class="tapeValue">' + h(item.value || '--') + '</span> <span class="small ' + cls + '">' + sign + h(pct.toFixed(2)) + '%</span></div>';
  }).join('');
  const headlines = (brief.headlines || []).map(function(item){
    return '<div class="feedItem"><a class="feedTitle" href="' + h(item.url || '#') + '" target="_blank" rel="noopener">' + (item.risk ? '<span class="riskMark"></span>' : '') + h(item.title) + '</a>' + (item.summary && item.summary !== item.title ? '<div class="feedSummary">' + h(item.summary) + '</div>' : '') + '<div class="feedMeta">' + h(item.published_at || '') + ' · ' + h(item.source || '') + '</div></div>';
  }).join('') || '<div class="empty">暂无可用盘前快讯。</div>';
  const calendar = (brief.calendar || []).map(function(item){
    const stars = item.importance ? '重要度 ' + h(item.importance) : '';
    return '<div class="calendarItem"><div class="calendarTime">' + h(item.time || '待定') + '</div><div><div class="calendarEvent">' + h(item.event) + '</div><div class="feedMeta">' + h(item.region || '') + (stars ? ' · <span class="importance">' + stars + '</span>' : '') + ' · 前值 ' + h(item.previous || '--') + ' / 预期 ' + h(item.expected || '--') + '</div></div></div>';
  }).join('') || '<div class="muted small">当日暂无高重要度经济事件。</div>';
  const watchNews = (brief.watchlist_news || []).map(function(item){
    return '<div class="feedItem"><span class="noticeStock">' + h((item.stocks || []).join(' / ')) + '</span><a class="feedTitle" href="' + h(item.url || '#') + '" target="_blank" rel="noopener">' + h(item.title) + '</a><div class="feedMeta">' + h(item.published_at || '') + ' · ' + h(item.source || '') + '</div></div>';
  });
  const notices = (brief.notices || []).map(function(item){
    return '<div class="feedItem"><span class="noticeStock">' + h(item.stock) + '</span><a class="feedTitle" href="' + h(item.url || '#') + '" target="_blank" rel="noopener">' + h(item.title) + '</a><div class="feedMeta">' + h(item.date || '') + ' · ' + h(item.source || '') + '</div></div>';
  });
  const watchlist = watchNews.concat(notices).join('') || '<div class="muted small">近五日未检索到自选股公告或直接相关新闻。</div>';
  const hot = (brief.hot_stocks || []).map(function(item){
    const pct = Number(item.change_pct || 0); const cls = pct > 0 ? 'rise' : pct < 0 ? 'fall' : '';
    return '<div class="hotItem"><div class="hotRank">#' + h(item.rank) + ' · 讨论 ' + h(item.attention) + '</div><div class="hotName">' + h(item.name) + '</div><div class="small ' + cls + '">' + (pct > 0 ? '+' : '') + h(pct.toFixed(2)) + '%</div></div>';
  }).join('') || '<div class="muted small">雪球讨论榜暂无数据。</div>';
  const ref = brief.reference_project || {};
  document.getElementById('premarket').innerHTML = '<div class="section"><div class="premarketHero"><div class="stance"><span class="stanceBadge">' + h(stance.level) + '</span><div class="stanceText">' + h(stance.summary) + '</div></div><div class="briefDate">' + h(brief.session_label || '') + '<br>更新 ' + h(String(brief.generated_at || '').replace('T',' ')) + '</div></div><div class="marketTape">' + tape + '</div><div class="premarketGrid"><div class="premarketColumn"><div class="briefBlock"><div class="briefTitle">盘前要闻<span class="briefMeta">按自选股、A股与风险关键词排序</span></div>' + headlines + '</div><div class="briefBlock"><div class="briefTitle">雪球热议<span class="briefMeta">讨论热度，不代表投资评级</span></div><div class="hotStrip">' + hot + '</div></div></div><div class="premarketColumn"><div class="briefBlock"><div class="briefTitle">经济日历<span class="briefMeta">' + h(brief.session_date || '') + '</span></div>' + calendar + '</div><div class="briefBlock"><div class="briefTitle">自选股消息<span class="briefMeta">新闻与公告</span></div>' + watchlist + '</div></div></div><div class="sourceFoot">数据：腾讯行情、东方财富快讯/公告、百度财经日历、雪球讨论榜 · 结构化市场上下文参考 <a href="' + h(ref.url || '#') + '" target="_blank" rel="noopener">' + h(ref.name || 'daily_stock_analysis') + '</a>（' + h(ref.license || '') + '）</div></div>';
}
function chainByTicker(ticker){
  const chains = (DATA.industry_chain && DATA.industry_chain.chains) || [];
  return chains.find(function(c){ return c.ticker === ticker; });
}
function trackById(trackId){
  const tracks = (DATA.industry_chain && DATA.industry_chain.tracks) || [];
  return tracks.find(function(t){ return t.id === trackId; }) || tracks[0];
}
function evidenceLabel(status){
  const row = ((DATA.industry_chain && DATA.industry_chain.evidence_legend) || []).find(function(x){ return x.status === status; });
  return row ? row.label : status || '待核验';
}
function chips(items){
  return (items || []).map(function(x){ return '<span class="softChip">' + h(x) + '</span>'; }).join('') || '<span class="muted small">待补全</span>';
}
function industryCompanies(){ return (DATA.industry_chain && DATA.industry_chain.public_companies) || []; }
function companiesForTrack(trackId){ return industryCompanies().filter(function(c){ return (c.tracks || []).includes(trackId); }); }
function industryReferences(){ return ((DATA.industry_chain && DATA.industry_chain.references) || []).map(function(r){ return '<a href="' + h(r.url) + '" target="_blank" rel="noopener">' + h(r.name) + '</a>'; }).join(' · '); }
function industryHeader(kicker, title, subtitle){ return '<div class="industryPageHead"><div><div class="industryEyebrow">' + h(kicker) + '</div><h2>' + h(title) + '</h2><p>' + h(subtitle) + '</p></div></div>'; }
function intelStatusLabel(status){ return ({watch:'观察中',confirmed:'已确认',weakening:'正在减弱',rejected:'已证伪'})[status] || status || '待判断'; }
function intelCheckLabel(status){ return ({pending:'待验证',pass:'已满足',fail:'未满足',mixed:'分化'})[status] || status || '待验证'; }
function industryToday(brief){
  const intel = brief.daily_intelligence || {}; const regime = intel.regime || {}; const signals = intel.signals || []; const items = intel.items || [];
  const itemHtml = items.map(function(item){
    const tags = (item.tags || []).map(function(x){ return '<span>' + h(x) + '</span>'; }).join('');
    return '<article class="intelAuthorCard"><div class="intelAuthorTop"><div class="intelAuthor"><span class="intelAvatar">' + h(String(item.author || '?').slice(0,1)) + '</span><div><b>' + h(item.author) + '</b><small>' + h(item.publisher || '公开来源') + ' · ' + h(item.published_at || '') + '</small></div></div><span class="sourceTier tier' + h(item.tier) + '">' + h(item.tier) + '</span></div><h3>' + h(item.title) + '</h3><p>' + h(item.summary) + '</p><div class="intelSystemView"><b>系统判断：</b>' + h(item.system_view) + '</div><div class="intelCardFoot"><div class="intelTags">' + tags + '</div><a class="intelOriginal" href="' + h(item.url) + '" target="_blank" rel="noopener">查看原文</a></div></article>';
  }).join('') || '<div class="industryEmpty">今日暂未收录新的作者或机构观点。</div>';
  const validations = [];
  signals.forEach(function(signal){ (signal.checks || []).forEach(function(check){ validations.push({signal:signal.title,name:check.name,rule:check.rule || check.value || '',status:check.status}); }); });
  const validationHtml = validations.map(function(row){ const ok = row.status === 'pass'; return '<div class="intelValidationRow"><b>' + h(row.name) + '</b><span>' + h(row.rule) + '</span><span class="' + (ok ? 'intelVerified' : 'intelPending') + '">' + h(intelCheckLabel(row.status)) + '</span></div>'; }).join('') || '<span class="muted small">暂无验证项。</span>';
  const sources = (intel.source_watchlist || []).map(function(src){ return '<div class="sourceRegistryItem"><div><span class="sourceTier tier' + h(src.tier) + '" style="display:inline-grid;margin-right:7px">' + h(src.tier) + '</span><b>' + h(src.name) + '</b></div><p>' + h(src.focus) + '</p></div>'; }).join('');
  const quality = intel.quality || {};
  return industryHeader('DAILY INDUSTRY INTELLIGENCE','今日产业情报','先看总体结论，再逐条阅读不同作者和机构今天提供了什么信息。') + '<div class="intelRegime"><div class="intelRegimeMain"><span class="intelStatus ' + h(regime.status) + '">' + h(intelStatusLabel(regime.status)) + '</span><h3>' + h(regime.label || '等待更新') + '</h3><p>' + h(regime.summary || '') + '</p></div><div class="intelScore"><span>软件相对硬件倾向</span><b>' + (Number(regime.score || 0) > 0 ? '+' : '') + h(regime.score || 0) + '</b><span>置信度 ' + h(regime.confidence || 0) + ' · ' + h(regime.horizon || '') + '</span></div></div><div class="industryBlockHead" style="padding-left:0;padding-right:0;border:0"><h3>今日来源观点</h3><span class="muted small">每张卡片对应一个作者或机构</span></div><div class="intelAuthorGrid">' + itemHtml + '</div><div class="industryBlock"><div class="industryBlockHead"><h3>总体判断的验证条件</h3><span class="muted small">满足后才提高置信度</span></div><div class="industryBlockBody"><div class="intelValidationList">' + validationHtml + '</div></div></div><div class="industrySplit"><div class="industryBlock"><div class="industryBlockHead"><h3>已收集来源</h3><span class="muted small">A事实 → D线索</span></div><div class="industryBlockBody"><div class="sourceRegistry">' + sources + '</div></div></div><div class="industryBlock"><div class="industryBlockHead"><h3>数据质量</h3><span class="intelStatus ' + (quality.status === 'verified' ? 'confirmed' : 'watch') + '">' + h(quality.status || 'unknown') + '</span></div><div class="industryBlockBody"><p class="muted small">' + h(quality.note || '') + '</p><div class="intelCaution">公众号、雪球和个人博主用于发现叙事变化，只有经过行情、公告或多源交叉验证后，才会提高结论置信度。</div></div></div></div>';
}
function industryOverview(brief, tracks){
  const active = trackById(currentTrackId) || tracks[0]; currentTrackId = active.id;
  const bottleneckCount = tracks.reduce(function(total,t){ return total + (((t.layers || {}).bottlenecks || []).length); }, 0);
  const stats = [[tracks.length,'产业链'],[bottleneckCount,'关键环节'],[industryCompanies().length,'A股公司'],[(brief.technology_routes || []).length,'技术路线']].map(function(x){ return '<div class="industryStat"><b>' + h(x[0]) + '</b><span>' + h(x[1]) + '</span></div>'; }).join('');
  const branchColors = ['#54a3ff','#27d17f','#f0a530','#d9f45b'];
  const branches = [['upstream','上游输入'],['bottlenecks','核心瓶颈'],['integration','系统集成'],['demand','需求拉动']].map(function(pair,idx){
    return '<div class="industryBranch" style="--branch:' + branchColors[idx] + '"><small>' + h(pair[1]) + '</small><b>' + h(active.title) + '</b>' + (((active.layers || {})[pair[0]]) || []).map(function(x){ return '<button class="industryLeaf" data-action="industry-view" data-view="bottlenecks">' + h(x) + '</button>'; }).join('') + '</div>';
  }).join('');
  const switcher = tracks.map(function(t){ return '<button class="' + (t.id === active.id ? 'active' : '') + '" data-action="track-pick" data-track="' + h(t.id) + '">' + h(t.title) + ' <span class="industryNavCount">' + h(((t.layers || {}).bottlenecks || []).length) + '</span></button>'; }).join('');
  const matrixHead = '<div class="industryMatrixHead"><span>#</span><span>产业链</span><span>上游输入</span><span>核心瓶颈</span><span>系统集成</span><span>需求拉动</span></div>';
  const matrixRows = tracks.map(function(t,idx){
    const cells = ['upstream','bottlenecks','integration','demand'].map(function(key){ return '<div>' + (((t.layers || {})[key]) || []).map(function(x){ return '<span class="industryNode">' + h(x) + '</span>'; }).join('') + '</div>'; }).join('');
    return '<div class="industryMatrixRow ' + (t.id === active.id ? 'active' : '') + '"><div class="index">' + h(String(idx+1).padStart(2,'0')) + '</div><div class="industryMatrixTitle"><button data-action="track-pick" data-track="' + h(t.id) + '">' + h(t.title) + '</button><small>' + h(companiesForTrack(t.id).length) + ' 家公司</small></div>' + cells + '</div>';
  }).join('');
  const radar = (brief.radar || []).filter(function(r){ return r.track === active.id; })[0];
  const focus = '<div class="industryBlock industryFocus"><div class="industryBlockBody"><div class="industryEyebrow">FOCUSED TRACK</div><h3>' + h(active.title) + '</h3><p>' + h(active.summary) + '</p><div class="chipCloud">' + chips(active.watch) + '</div></div></div>';
  const radarHtml = '<div class="industryBlock"><div class="industryBlockHead"><h3>情报雷达</h3><button class="ghost tiny" data-action="industry-view" data-view="radar">查看全部</button></div><div class="industryBlockBody">' + (radar ? '<b>' + h(radar.title) + '</b><p class="muted small">' + h(radar.impact) + '</p>' : '<span class="muted small">该链条暂无新增情报。</span>') + '</div></div>';
  return industryHeader('AI VALUE CHAIN MAP','AI 产业链结构图','从供给约束到软件商业化，把算力、存储、网络、封装、制造、材料、电力、服务器和应用放在同一套验证框架中。') + '<div class="industryStats">' + stats + '</div><div class="industryCommand"><div class="industryCommandCopy"><div class="industryEyebrow" style="color:#d9f45b">FIRST PRINCIPLES</div><h3>先判断变化发生在哪一层</h3><p>硬件看产能、良率、认证和交付；软件看用户、续费、推理成本和利润兑现。市场风格切换不能替代产业基本面验证。</p><button class="acidButton" data-action="industry-view" data-view="bottlenecks">进入环节库</button></div><div class="industryBranchGrid">' + branches + '</div></div><div class="industrySwitcher">' + switcher + '</div><div class="industryMatrix">' + matrixHead + matrixRows + '</div><div class="industrySplit">' + focus + radarHtml + '</div>';
}
function industryBottlenecks(brief, tracks){
  const rows = []; tracks.forEach(function(t){ (((t.layers || {}).bottlenecks) || []).forEach(function(node){ rows.push({track:t,node:node}); }); });
  const cards = rows.map(function(x){ return '<button class="industryCard" data-action="track-pick" data-track="' + h(x.track.id) + '"><span class="industryCardCode">' + h(x.track.id.toUpperCase()) + '</span><h3>' + h(x.node) + '</h3><p>' + h(x.track.summary) + '</p><div class="industryCardMeta"><span>' + h(x.track.title) + '</span><span>' + h(companiesForTrack(x.track.id).length) + ' 家公司</span></div></button>'; }).join('');
  return industryHeader('BOTTLENECK LIBRARY','关键环节库','按产业链位置理解每个瓶颈，并回查相关公司与验证变量。') + '<div class="industryLibrary">' + cards + '</div>';
}
function industryCompanyIndex(brief){
  const trackNames = Object.fromEntries((brief.tracks || []).map(function(t){ return [t.id,t.title]; }));
  const rows = industryCompanies().map(function(c){ return '<tr data-action="chain-detail" data-ticker="' + h(c.ticker) + '"><td><b>' + h(c.name) + '</b><br><span class="ticker">' + h(c.ticker) + '</span></td><td>' + h(c.role) + '</td><td>' + (c.tracks || []).map(function(id){ return '<span class="role-pill">' + h(trackNames[id] || id) + '</span>'; }).join(' ') + '</td><td><span class="evidence business_fit">业务匹配</span></td></tr>'; }).join('');
  return industryHeader('COMPANY INDEX','A 股公司索引','先确认公司主营与产业链位置，再单独核验收入相关度、客户和订单。') + '<div class="tableWrap"><table class="industryCompanyTable"><thead><tr><th>公司</th><th>产业角色</th><th>所在链条</th><th>证据状态</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}
function industryRoutes(brief){
  const rows = (brief.technology_routes || []).map(function(r){ return '<div class="industryBlock"><div class="industryBlockHead"><h3>' + h(r.title) + '</h3><span class="muted small">判断重点：' + h(r.focus) + '</span></div><div class="industryBlockBody"><div class="routeLine">' + (r.path || []).map(function(x,idx){ return (idx ? '<span class="routeArrow">→</span>' : '') + '<span class="routeNode">' + h(x) + '</span>'; }).join('') + '</div></div></div>'; }).join('');
  return industryHeader('TECHNOLOGY ROUTES','技术路线','用系统目标串起多个环节，避免把单一产品变化误判为完整产业趋势。') + '<div style="display:grid;gap:10px">' + rows + '</div>';
}
function industryRadar(brief){
  const trackNames = Object.fromEntries((brief.tracks || []).map(function(t){ return [t.id,t.title]; }));
  const rows = (brief.radar || []).map(function(r){ return '<div class="industryBlock"><div class="industryBlockBody"><div class="industryEyebrow">' + h(trackNames[r.track] || r.track) + '</div><h3 style="margin:7px 0">' + h(r.title) + '</h3><p class="muted small">' + h(r.impact) + '</p><div class="linkLine"><span class="evidence ' + h(r.status) + '">' + h(evidenceLabel(r.status)) + '</span><span>' + h(r.source_type) + '</span></div></div></div>'; }).join('');
  return industryHeader('INTELLIGENCE RADAR','情报雷达','只保留能改变供需、价格、认证或交付节奏的公开信号。') + '<div class="industryLibrary">' + rows + '</div>';
}
function industryLearning(brief){
  const rows = (brief.learning_path_cards || []).map(function(r){ return '<div class="industryCard"><span class="industryCardCode">STEP ' + h(r.level) + '</span><h3>' + h(r.title) + '</h3><div class="routeLine">' + (r.steps || []).map(function(x,idx){ return (idx ? '<span class="routeArrow">→</span>' : '') + '<span class="routeNode">' + h(x) + '</span>'; }).join('') + '</div></div>'; }).join('');
  return industryHeader('LEARNING PATHS','学习路径','从系统结构到供给瓶颈，再落到 A 股公司的可验证研究顺序。') + '<div style="display:grid;gap:10px">' + rows + '</div>';
}
function industryUpdates(brief){
  const rows = (brief.update_log || []).map(function(r){ return '<div class="industryBlock"><div class="industryBlockBody"><div class="industryEyebrow">' + h(r.date) + '</div><h3 style="margin:7px 0">' + h(r.title) + '</h3><p class="muted small" style="margin:0">' + h(r.detail) + '</p></div></div>'; }).join('');
  return industryHeader('CHANGELOG','更新记录','记录产业链结构、证据等级与公司映射的调整。') + '<div style="display:grid;gap:10px">' + rows + '</div>';
}
function industrySearchPage(brief, tracks, query){
  const q = String(query || '').trim().toLowerCase(); const results = [];
  tracks.forEach(function(t){ const nodes = Object.values(t.layers || {}).flat(); if((t.title + ' ' + t.summary + ' ' + nodes.join(' ')).toLowerCase().includes(q)) results.push({type:'产业链',title:t.title,meta:t.summary,action:'track-pick',value:t.id}); });
  industryCompanies().forEach(function(c){ if((c.name + ' ' + c.ticker + ' ' + c.role).toLowerCase().includes(q)) results.push({type:'公司',title:c.name + ' · ' + c.ticker,meta:c.role,action:'chain-detail',value:c.ticker}); });
  (brief.technology_routes || []).forEach(function(r){ if((r.title + ' ' + r.path.join(' ')).toLowerCase().includes(q)) results.push({type:'技术路线',title:r.title,meta:r.path.join(' → '),action:'industry-view',value:'routes'}); });
  const html = results.map(function(r){ const attr = r.action === 'track-pick' ? 'data-track' : r.action === 'chain-detail' ? 'data-ticker' : 'data-view'; return '<button class="industrySearchResult" data-action="' + h(r.action) + '" ' + attr + '="' + h(r.value) + '"><span>' + h(r.type) + '</span><b>' + h(r.title) + '</b><span>' + h(r.meta) + '</span></button>'; }).join('');
  return industryHeader('SEARCH','搜索结果','关键词：' + query) + '<div class="industrySearchResults">' + (html || '<div class="industryEmpty">没有匹配结果。</div>') + '</div>';
}
function renderIndustry(){
  const brief = DATA.industry_chain || {}; const tracks = brief.tracks || [];
  if(!tracks.length){ document.getElementById('industry').innerHTML = '<div class="empty">暂无产业链知识数据。</div>'; return; }
  const intel = brief.daily_intelligence || {};
  const nav = [['today','NOW','今日情报',(intel.signals || []).length],['map','MAP','产业链总图',tracks.length],['bottlenecks','BOT','环节库',tracks.reduce(function(n,t){ return n + (((t.layers || {}).bottlenecks || []).length); },0)],['routes','RTE','技术路线',(brief.technology_routes || []).length],['companies','CO','公司库',industryCompanies().length],['radar','RAD','情报雷达',(brief.radar || []).length],['learning','LRN','学习路径',(brief.learning_path_cards || []).length],['updates','LOG','更新记录',(brief.update_log || []).length]].map(function(x){ return '<button class="' + (currentIndustryView === x[0] && !industryQuery ? 'active' : '') + '" data-action="industry-view" data-view="' + x[0] + '"><span class="industryNavIcon">' + x[1] + '</span><span>' + x[2] + '</span><span class="industryNavCount">' + x[3] + '</span></button>'; }).join('');
  let content = currentIndustryView === 'today' ? industryToday(brief) : industryOverview(brief,tracks); if(industryQuery) content = industrySearchPage(brief,tracks,industryQuery); else if(currentIndustryView === 'bottlenecks') content = industryBottlenecks(brief,tracks); else if(currentIndustryView === 'routes') content = industryRoutes(brief); else if(currentIndustryView === 'companies') content = industryCompanyIndex(brief); else if(currentIndustryView === 'radar') content = industryRadar(brief); else if(currentIndustryView === 'learning') content = industryLearning(brief); else if(currentIndustryView === 'updates') content = industryUpdates(brief);
  document.getElementById('industry').innerHTML = '<div class="industryApp"><aside class="industryRail"><div class="industryBrand"><span class="industryMark">AI</span><span><strong>AI 产业链地图</strong><small>结构知识与每日市场情报分层呈现</small></span></div><nav class="industryNav">' + nav + '</nav><div class="industryRailNote"><b>每日更新 · ' + h(intel.trade_date || '') + '</b>公开信息独立整理<br>观点必须经过验证</div></aside><div class="industryWorkspace"><div class="industryToolbar"><label class="industrySearch"><span>⌕</span><input id="industrySearchInput" value="' + h(industryQuery) + '" placeholder="搜索技术路线、设备或公司" autocomplete="off"><kbd>⌘ K</kbd></label><span class="industryToolbarMeta">证据分级 · A 股映射 · 每日增量</span></div><div class="industryContent">' + content + '<div class="industryRefs">研究结构参考：' + industryReferences() + '。结构知识、交易风格和公司基本面分层处理；业务匹配不代表已确认客户或订单。</div></div></div></div>';
}
function openChainDetail(ticker){
  const c = chainByTicker(ticker);
  if(!c){
    const company = industryCompanies().find(function(row){ return row.ticker === ticker; });
    if(!company) return;
    const trackNames = Object.fromEntries((((DATA.industry_chain || {}).tracks) || []).map(function(t){ return [t.id,t.title]; }));
    document.getElementById('drawerTitle').textContent = company.name + '产业链资料卡';
    document.getElementById('drawerMeta').textContent = company.ticker + ' · ' + company.role;
    document.getElementById('drawerBody').innerHTML = '<p><strong>产业角色：</strong>' + h(company.role) + '</p><h3>所在链条</h3><div class="chipCloud">' + (company.tracks || []).map(function(id){ return '<span class="softChip">' + h(trackNames[id] || id) + '</span>'; }).join('') + '</div><h3>证据状态</h3><p><span class="evidence business_fit">业务匹配</span> 公司公开主营与该环节相符，但客户、订单、收入占比和盈利弹性仍需通过公告与定期报告逐项核验。</p><h3>研究检查项</h3><ol><li>相关产品收入占比和增速是否足以影响公司整体利润？</li><li>客户认证、量产和交付周期是否有公开证据？</li><li>行业扩产是否会转化为价格、利用率或毛利率改善？</li><li>当前估值是否已经计入乐观预期？</li></ol>';
    openDrawer(); return;
  }
  const linkHtml = (c.map || []).map(function(link){
    return '<li>' + h(link.track_title || link.track) + ' · ' + h(link.node) + ' <span class="evidence ' + h(link.status) + '">' + h(evidenceLabel(link.status)) + '</span></li>';
  }).join('');
  document.getElementById('drawerTitle').textContent = c.name + '产业链知识卡';
  document.getElementById('drawerMeta').textContent = c.ticker + ' · ' + c.anchor;
  document.getElementById('drawerBody').innerHTML = '<p><strong>第一性原理：</strong>' + h(c.first_principle) + '</p><h3>链条位置</h3><ul>' + linkHtml + '</ul><h3>跟踪信号</h3><ul>' + (c.watch_signals || []).map(function(x){ return '<li>' + h(x) + '</li>'; }).join('') + '</ul><h3>核心风险</h3><ul>' + (c.risks || []).map(function(x){ return '<li>' + h(x) + '</li>'; }).join('') + '</ul><h3>下一轮验证问题</h3><ol>' + (c.questions || []).map(function(x){ return '<li>' + h(x) + '</li>'; }).join('') + '</ol>';
  openDrawer();
}
function renderPool(){
  const rows = allUniverse();
  const table = '<div class="tableWrap"><table><thead><tr><th>标的</th><th>池层级</th><th>主题</th><th>角色</th><th>频率</th><th>最近结论</th><th>操作</th></tr></thead><tbody>' + rows.map(function(u){ const r = latestRun(u.ticker); return '<tr><td class="stockCell"><b>' + stockTitle(u) + '</b></td><td class="decisionCell">' + h(u.pool || '观察池') + '</td><td class="themeCell">' + h(u.theme || '') + '</td><td class="decisionCell">' + h(u.role || '') + '</td><td class="decisionCell">' + h(u.cadence || '周五复盘') + '</td><td class="decisionCell">' + (r ? '<span class="badge ' + actionCls(r.action) + '">' + h(decisionText(r)) + '</span>' : '<span class="muted">待生成</span>') + '</td><td class="opCell">' + reportButtons(r) + '</td></tr>'; }).join('') + '</tbody></table></div>';
  document.getElementById('pool').innerHTML = '<div class="section"><div class="sectionHead"><div class="sectionTitle">选股池</div><div class="poolActions"><button class="tiny" data-action="add-stock">手动添加</button><button class="ghost tiny" data-tab-jump="candidates">每日候选</button><button class="ghost tiny" data-action="pool-rules">建池规则</button></div></div>' + table + '</div>';
}
function openReport(id){
  const r = byRun[id]; if(!r) return;
  document.getElementById('drawerTitle').textContent = r.name + '（' + r.ticker + '）';
  document.getElementById('drawerMeta').innerHTML = h(r.report_date) + ' · ' + h(decisionText(r)) + ' · 降级 ' + h(r.degradation_count);
  document.getElementById('drawerBody').innerHTML = r.report_html || '<p>暂无完整研报内容。</p>';
  openDrawer();
}
function fmtNum(v){ return v === null || v === undefined || v === '' ? '--' : h(v); }
function openQuote(ticker, name){
  const stock = findUniverseByTicker(ticker) || {ticker:ticker, name:name};
  const market = ticker ? DATA.market_data[ticker] : null;
  document.getElementById('drawerTitle').textContent = (stock.name || name || '标的行情') + (ticker ? '（' + ticker + '）' : '');
  document.getElementById('drawerMeta').textContent = market ? market.source + ' · ' + (market.updated_at || '') : '缺少股票代码，等待系统补全后拉取行情。';
  if(!market || !market.rows || !market.rows.length){
    document.getElementById('drawerBody').innerHTML = '<div class="empty">暂无可用 K 线。' + h(market && market.error ? market.error : '该标的需要在下次系统刷新时补全代码和行情。') + '</div>';
    openDrawer();
    return;
  }
  const stats = [
    ['最新收盘', market.last],
    ['日涨跌幅', market.change_pct === null || market.change_pct === undefined ? '--' : market.change_pct + '%'],
    ['20日高点', market.high_20],
    ['20日低点', market.low_20],
  ].map(function(x){ return '<div class="quoteStat"><span class="muted small">' + h(x[0]) + '</span><b>' + fmtNum(x[1]) + '</b></div>'; }).join('');
  document.getElementById('drawerBody').innerHTML = '<div class="chartShell"><div class="quoteStats">' + stats + '</div><canvas id="klineCanvas" class="chartCanvas"></canvas><div class="chartSource">数据源：' + h(market.source) + '；点击标的打开，研报按钮只负责研报预览。</div></div>';
  openDrawer();
  requestAnimationFrame(function(){ drawKline(ticker); });
}
function drawKline(ticker){
  const market = DATA.market_data[ticker];
  const rows = market && market.rows ? market.rows : [];
  const canvas = document.getElementById('klineCanvas');
  if(!canvas || !rows.length) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio,0,0,ratio,0,0);
  const w = rect.width, hgt = rect.height;
  ctx.clearRect(0,0,w,hgt);
  const pad = {left:46,right:14,top:14,bottom:28};
  const chartW = w - pad.left - pad.right;
  const chartH = hgt - pad.top - pad.bottom;
  const highs = rows.map(function(r){return r.high});
  const lows = rows.map(function(r){return r.low});
  let maxP = Math.max.apply(null, highs), minP = Math.min.apply(null, lows);
  if(maxP === minP){ maxP += 1; minP -= 1; }
  function y(price){ return pad.top + (maxP - price) / (maxP - minP) * chartH; }
  ctx.strokeStyle = '#e6edf3';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#667586';
  ctx.font = '12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
  for(let i=0;i<=4;i++){
    const yy = pad.top + chartH * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(w-pad.right, yy); ctx.stroke();
    const price = maxP - (maxP - minP) * i / 4;
    ctx.fillText(price.toFixed(2), 4, yy + 4);
  }
  const slot = chartW / rows.length;
  const candleW = Math.max(3, Math.min(9, slot * 0.58));
  rows.forEach(function(r, i){
    const x = pad.left + slot * i + slot / 2;
    const up = r.close >= r.open;
    ctx.strokeStyle = up ? '#c93a3a' : '#138a5b';
    ctx.fillStyle = up ? '#d94a4a' : '#17a06b';
    ctx.beginPath(); ctx.moveTo(x, y(r.high)); ctx.lineTo(x, y(r.low)); ctx.stroke();
    const top = Math.min(y(r.open), y(r.close));
    const bottom = Math.max(y(r.open), y(r.close));
    ctx.fillRect(x - candleW/2, top, candleW, Math.max(1.5, bottom - top));
  });
  ctx.fillStyle = '#667586';
  const first = rows[0].date.slice(5), last = rows[rows.length - 1].date.slice(5);
  ctx.fillText(first, pad.left, hgt - 8);
  ctx.fillText(last, w - pad.right - 38, hgt - 8);
}
function openArchitecture(){
  const sources = DATA.data_sources.map(function(s){ return '<div class="source"><h3>' + h(s.layer) + '</h3><p><b>' + h(s.status) + '</b> · ' + h(s.current) + '</p><p class="muted">' + h(s.note) + '</p></div>'; }).join('');
  document.getElementById('drawerTitle').textContent = DATA.architecture.title;
  document.getElementById('drawerMeta').textContent = DATA.architecture.caption;
  document.getElementById('drawerBody').innerHTML = '<img class="archImg" src="' + h(DATA.architecture.image) + '" alt="A股投研 R&D Agent 系统架构图"><h3>数据源状态</h3><div class="sourceGrid">' + sources + '</div>';
  openDrawer();
}
function openDataAudit(){
  const audit = DATA.data_audit || {};
  const semantic = (((audit.checks || {}).semantic_review) || {});
  const issues = (audit.issues || []).map(function(issue){
    return '<div class="auditIssue ' + h(issue.severity || '') + '"><b>' + h(issue.module || issue.ticker || issue.field || '数据问题') + '</b><div>' + h(issue.message || '') + '</div><div class="muted small">' + h(issue.severity || '') + '</div></div>';
  }).join('') || '<div class="empty">当前未发现需要阻断结论的数据问题。</div>';
  const findings = (semantic.findings || []).map(function(item){
    return '<div class="auditIssue ' + h(item.severity || '') + '"><b>' + h(item.module || 'llm_verification') + '</b><div>' + h(item.message || '') + '</div>' + (item.fix ? '<div class="muted small">建议：' + h(item.fix) + '</div>' : '') + '</div>';
  }).join('') || '<div class="empty">暂无语义核验提醒。</div>';
  const semanticHtml = '<div class="llmReview"><div class="llmReviewHead"><b>LLM 核验员</b><span class="softChip ' + h(semantic.status || 'skipped') + '">' + h(semantic.status || 'skipped') + '</span></div><p>' + h(semantic.summary || '未运行') + '</p><div class="muted small">模型：' + h(semantic.model || '--') + '</div></div><h3>语义核验发现</h3>' + findings;
  const quoteRows = ((((audit.checks || {}).quote_consensus || {}).rows) || []).map(function(row){
    const providers = (row.providers || []).map(function(x){ return '<span class="softChip">' + h(x) + '</span>'; }).join('');
    const spreads = Object.entries(row.spreads || {}).map(function(x){ return h(x[0]) + ' ' + h(Number(x[1]).toFixed(3)); }).join(' / ');
    return '<div class="auditRow"><div class="auditTop"><b>' + h(row.name || row.ticker) + ' · ' + h(row.ticker) + '</b><span class="softChip ' + h(row.status) + '">' + h(row.status) + '</span></div><div class="auditProviders">' + providers + '</div><div class="muted small">' + h(spreads || '无可比字段') + '</div></div>';
  }).join('');
  const sourceRows = ((((audit.checks || {}).source_health || {}).rows) || []).map(function(row){
    return '<div class="auditRow"><div class="auditTop"><b>' + h(row.name) + '</b><span class="softChip ' + h(row.status) + '">' + h(row.status) + '</span></div><div class="muted small">count ' + h(row.count || 0) + (row.error ? ' · ' + h(row.error) : '') + '</div></div>';
  }).join('');
  document.getElementById('drawerTitle').textContent = 'Data Auditor 数据检查员';
  document.getElementById('drawerMeta').textContent = (audit.summary || '') + ' · 评分 ' + (audit.score || '--') + ' · ' + String(audit.generated_at || '').replace('T',' ');
  document.getElementById('drawerBody').innerHTML = '<div class="source"><h3>结论门槛</h3><p>' + h((audit.policy || {}).hard_gate || '') + '</p><p class="muted">' + h((audit.policy || {}).quote_consensus || '') + '</p></div>' + semanticHtml + '<h3>全部问题</h3>' + issues + '<h3>实时行情三源共识</h3><div class="auditGrid">' + quoteRows + '</div><h3>源健康</h3><div class="auditGrid">' + sourceRows + '</div>';
  openDrawer();
}
function openCadence(){
  const groups = ['常驻','每日','每周','按需'].map(function(freq){
    const rows = (DATA.cadence || []).filter(function(x){ return x.frequency === freq; });
    if(!rows.length) return '';
    return '<h3>' + h(freq) + '</h3><div class="cadenceList">' + rows.map(function(row){ return '<div class="cadenceRow"><div class="cadenceTime">' + h(row.time) + '</div><div><b>' + h(row.module) + '</b><p>' + h(row.note) + '</p></div><span class="cadenceStatus ' + (row.status === '运行中' ? 'ready' : '') + '">' + h(row.status) + '</span></div>'; }).join('') + '</div>';
  }).join('');
  document.getElementById('drawerTitle').textContent = '工作台更新日历';
  document.getElementById('drawerMeta').textContent = '日更处理交易状态，周更处理完整研报和模型自迭代。';
  document.getElementById('drawerBody').innerHTML = groups;
  openDrawer();
}
function openOptimize(){
  const review = DATA.optimization_review || {};
  const auction = review.auction || {};
  const candidates = review.candidates || {};
  const h1 = (candidates.by_horizon || {})['1'] || {};
  const iter = review.candidate_iteration || {};
  const reviewHtml = review.trade_date ? '<div class="source"><h3>最近一次日复盘优化</h3><p><b>' + h(review.status || '--') + '</b> · ' + h(review.summary || '') + '</p><div class="quoteStats"><div><span>日期</span><b>' + h(review.trade_date || '--') + '</b></div><div><span>集合竞价</span><b>' + h(auction.status || '--') + '</b><small>评分 ' + h(auction.score || '--') + '</small></div><div><span>候选样本</span><b>' + h(candidates.ready_count || 0) + '</b><small>T+1 命中 ' + h(h1.hit_rate === null || h1.hit_rate === undefined ? '--' : h1.hit_rate) + '</small></div><div><span>策略迭代</span><b>' + h(iter.status || '--') + '</b><small>样本 ' + h(iter.sample_size || 0) + '</small></div></div></div>' : '<div class="empty">暂无日复盘优化记录。收盘后运行 daily-optimize 后会显示。</div>';
  const openTasks = DATA.tasks.filter(function(t){ return t.status === 'open'; });
  const taskHtml = openTasks.length ? openTasks.map(function(t){ return '<div class="task ' + h(t.priority) + '"><b>' + h(t.title) + '</b><br><span class="muted small">' + h(t.priority) + ' · ' + h(t.module || '') + ' · ' + h(t.created_at || '') + '</span><div>' + h(String(t.detail || '')).replaceAll('\\n','<br>') + '</div></div>'; }).join('') : '<div class="empty">暂无开放优化任务</div>';
  document.getElementById('drawerTitle').textContent = '优化任务';
  document.getElementById('drawerMeta').textContent = '每日复盘策略偏差，集合竞价、候选股、研报和数据审计都会进入优化闭环。';
  document.getElementById('drawerBody').innerHTML = reviewHtml + '<h3>开放优化任务</h3>' + taskHtml;
  openDrawer();
}
function openPoolRules(){
  document.getElementById('drawerTitle').textContent = '建池规则';
  document.getElementById('drawerMeta').textContent = '只在选股池页面展示入口。';
  document.getElementById('drawerBody').innerHTML = DATA.pool_policy.map(function(r){ return '<div class="rule"><b>' + h(r.stage) + '</b><br>' + h(r.purpose) + '<br><span class="muted">出池/降级：' + h(r.exit) + '</span></div>'; }).join('');
  openDrawer();
}
function openAddStock(){
  document.getElementById('drawerTitle').textContent = '手动添加股票';
  document.getElementById('drawerMeta').textContent = '只输入名称；系统用 A 股代码名称表补全代码，主题和角色后续由研报链路收集分析。';
  document.getElementById('drawerBody').innerHTML = '<div class="singleAdd"><label>股票名称<input id="addStockName" placeholder="例如 寒武纪 / 亨通光电 / 中科创达" autocomplete="off"></label><div class="resolveHint" id="resolveHint">输入名称后会自动匹配 A 股代码。</div><button data-action="save-stock">保存到选股池</button></div>';
  openDrawer();
  setTimeout(function(){ const input = document.getElementById('addStockName'); if(input) input.focus(); }, 0);
}
function updateResolveHint(){
  const input = document.getElementById('addStockName');
  const hint = document.getElementById('resolveHint');
  if(!input || !hint) return;
  const value = input.value.trim();
  if(!value){ hint.textContent = '输入名称后会自动匹配 A 股代码。'; return; }
  const resolved = resolveStockName(value);
  if(resolved){
    hint.innerHTML = '匹配到：<b>' + h(resolved.name) + '</b> · <span class="mono">' + h(resolved.ticker) + '</span><br><span class="muted small">入池后默认作为候选池，主题/角色由后续研报链路补全。</span>';
  } else {
    hint.innerHTML = '未匹配到精确 A 股代码；会先加入候选池并标记为待补全。';
  }
}
function saveStock(){
  const rawName = (document.getElementById('addStockName') && document.getElementById('addStockName').value.trim()) || '';
  if(!rawName){ alert('股票名称必填'); return; }
  const resolved = resolveStockName(rawName);
  const item = {
    ticker: resolved && resolved.ticker ? String(resolved.ticker).toUpperCase() : '',
    name: resolved && resolved.name ? resolved.name : rawName,
    pool: '候选池',
    theme: '待系统收集分析',
    role: '待研报定义',
    cadence: '周五复盘',
    pending_enrichment: !(resolved && resolved.ticker),
    added_from: 'name_only'
  };
  const rows = customPool().filter(function(x){ return stockKey(x) !== stockKey(item) && normalizeName(x.name) !== normalizeName(item.name); });
  rows.push(item); saveCustomPool(rows); closeDrawer(); render();
}
function openDrawer(){ document.getElementById('drawer').classList.add('open'); document.getElementById('drawerMask').classList.add('open'); }
function closeDrawer(){ document.getElementById('drawer').classList.remove('open'); document.getElementById('drawerMask').classList.remove('open'); }
async function copyText(s){ try{ await navigator.clipboard.writeText(s); } catch(e){ console.warn(e); } }
function switchTab(tab){ document.querySelectorAll('.nav button,.panel').forEach(function(x){ x.classList.remove('active'); }); const btn = document.querySelector('.nav button[data-tab="' + tab + '"]'); if(btn) btn.classList.add('active'); const panel = document.getElementById(tab); if(panel) panel.classList.add('active'); }
function renderThesisReview(){
  const review = DATA.thesis_review || {};
  const rows = (review.reviews || []).map(function(r){
    const evidence = r.evidence || {};
    const verdict = function(v){ return '<span class="softChip ' + h(v) + '">' + h(v || '--') + '</span>'; };
    return '<tr><td><b>' + h(r.ticker || '') + '</b><br><span class="muted small">' + h(r.report_date || '') + ' · ' + h(r.horizon || '') + '</span></td><td>' + h(r.action || '--') + '</td><td>' + verdict(r.macro_verdict) + '</td><td>' + verdict(r.industry_verdict) + '</td><td>' + verdict(r.company_verdict) + '</td><td>' + verdict(r.expectation_verdict) + '</td><td>' + verdict(r.timing_verdict) + '</td><td>' + verdict(r.data_verdict) + '</td><td>' + h(evidence.return_pct === null || evidence.return_pct === undefined ? '--' : evidence.return_pct + '%') + '<br><span class="muted small">相对 ' + h(evidence.relative_return_pct === null || evidence.relative_return_pct === undefined ? '--' : evidence.relative_return_pct + '%') + '</span></td></tr>';
  }).join('');
  const empty = '<div class="empty">暂无可复盘假设。周五任务会在研报产生 T+5 结果后自动归因。</div>';
  const body = rows ? '<div class="tableWrap"><table><thead><tr><th>标的</th><th>动作</th><th>宏观</th><th>行业</th><th>公司</th><th>预期</th><th>时点</th><th>数据</th><th>结果</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : empty;
  document.getElementById('review').innerHTML = '<div class="section"><div class="sectionHead"><div><div class="sectionTitle">周五三级假设复盘</div><div class="muted small">预测 → 实际 → 归因 → 规则迭代；价格不能单独证明宏观、行业或公司因果错误。</div></div><span class="softChip">' + h(review.review_date || '待运行') + '</span></div><div class="sectionBody">' + body + '</div></div>';
}
function render(){ renderStatus(); renderOverview(); renderCandidates(); renderMarketPulse(); renderPremarket(); renderAuction(); renderIndustry(); renderThesisReview(); renderPool(); }
document.addEventListener('click', function(e){
  const jump = e.target.closest('[data-tab-jump]'); if(jump){ switchTab(jump.dataset.tabJump); return; }
  const nav = e.target.closest('.nav button[data-tab]'); if(nav){ switchTab(nav.dataset.tab); return; }
  const btn = e.target.closest('[data-action]'); if(!btn) return;
  const action = btn.dataset.action;
  if(action === 'render') render();
  if(action === 'report') openReport(Number(btn.dataset.run));
  if(action === 'quote') openQuote(btn.dataset.ticker || '', btn.dataset.name || '');
  if(action === 'track-pick'){ currentTrackId = btn.dataset.track || currentTrackId; currentIndustryView = 'map'; industryQuery = ''; renderIndustry(); }
  if(action === 'industry-view'){ currentIndustryView = btn.dataset.view || 'map'; industryQuery = ''; renderIndustry(); }
  if(action === 'chain-detail') openChainDetail(btn.dataset.ticker || '');
  if(action === 'architecture') openArchitecture();
  if(action === 'data-audit') openDataAudit();
  if(action === 'cadence') openCadence();
  if(action === 'optimize') openOptimize();
  if(action === 'pool-rules') openPoolRules();
  if(action === 'add-stock') openAddStock();
  if(action === 'save-stock') saveStock();
  if(action === 'copy') copyText(btn.dataset.text || '');
  if(action === 'close') closeDrawer();
});
document.addEventListener('input', function(e){
  if(e.target && e.target.id === 'addStockName') updateResolveHint();
  if(e.target && e.target.id === 'industrySearchInput'){
    industryQuery = e.target.value;
    renderIndustry();
    const input = document.getElementById('industrySearchInput'); if(input){ input.focus(); input.setSelectionRange(input.value.length,input.value.length); }
  }
});
document.getElementById('drawerMask').addEventListener('click', closeDrawer);
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape'){ closeDrawer(); industryQuery = ''; }
  if((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'){
    const industryPanel = document.getElementById('industry');
    if(industryPanel && industryPanel.classList.contains('active')){ e.preventDefault(); const input = document.getElementById('industrySearchInput'); if(input) input.focus(); }
  }
});
render();
</script>
</body></html>"""
    )
    return template.substitute(data=data, generated_at=html.escape(payload["generated_at"]))
