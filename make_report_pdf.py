"""Render a TradingAgents run into a professional HTML + PDF research note.

The report body is the Report Writer's (报告整合官) integrated, polished markdown
(``final_report``) — a single coherent document with consistent ## / ### heading
hierarchy and no AI-internal phrasing. The PDF is a pure renderer: masthead +
rating/metric cards + Executive-Summary callout + the editor's sections. (Falls
back to stitching condensed analyst reports only for old logs without a
final_report.)

Usage: python make_report_pdf.py <TICKER>
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import markdown as md

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HOME = os.path.expanduser("~")
CN_NAME = {"300811.SZ": "铂科新材", "300496.SZ": "中科创达", "002202.SZ": "金风科技",
           "SPCX": "SpaceX"}

# AI-internal / process phrases to strip defensively if any slip through.
_AI_NOISE = re.compile(
    r"^\s*(数据(已)?(非常)?(全面|充分|获取)|所有数据已获取|现在我(来|将)|下面(我来)?撰写|"
    r"好的[，,]|以下是|我现在(拥有|已)|现在我已获得).*$",
    re.M,
)


def md2html(text: str) -> str:
    if not text or not str(text).strip():
        return "<p class='muted'>（无内容）</p>"
    return md.markdown(text, extensions=["tables", "extra", "sane_lists", "nl2br"])


def field(text: str, name: str) -> str:
    m = re.search(rf"\*\*{name}\*\*[:：]\s*([^\n]+)", text or "", re.I)
    return m.group(1).strip() if m else ""


RATING_MAP = {
    "overweight": ("增持", "#1a7f37"), "buy": ("买入", "#1a7f37"),
    "underweight": ("减持", "#c0392b"), "sell": ("卖出", "#c0392b"),
    "neutral": ("中性", "#b8860b"), "hold": ("持有", "#b8860b"),
    "增持": ("增持", "#1a7f37"), "买入": ("买入", "#1a7f37"),
    "减持": ("减持", "#c0392b"), "卖出": ("卖出", "#c0392b"),
    "中性": ("中性", "#b8860b"), "持有": ("持有", "#b8860b"),
}


def resolve_rating(rating, proposal):
    # The Report Writer occasionally leaves the prompt's enum placeholder intact
    # (e.g. "减持|卖出") instead of picking one — split such candidates and try
    # each token so the rating cell never shows a raw "a|b" string.
    cands = []
    for raw in (rating, proposal):
        for tok in re.split(r"[|/、,，\s]+", (raw or "").strip()):
            if tok:
                cands.append(tok.lower())
    for k in cands:
        if k in RATING_MAP:
            return RATING_MAP[k]
    return ((rating or proposal or "—").split("|")[0].strip(), "#0a2540")


def parse_meta(report_md: str):
    """Extract the Report Writer's canonical decision params (HTML-comment META)."""
    m = re.search(r"<!--\s*META\s*(\{.*?\})\s*-->", report_md or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def strip_meta(report_md: str) -> str:
    return re.sub(r"<!--\s*META\s*\{.*?\}\s*-->\s*", "", report_md or "", flags=re.S)


def split_summary(report_md: str):
    """Pull the '摘要/核心结论' section out for the callout; return (summary, rest)."""
    report_md = _AI_NOISE.sub("", report_md or "").strip()
    # Find the summary heading and the next ## heading.
    m = re.search(r"^##\s*(摘要[^\n]*|核心结论[^\n]*)$", report_md, re.M)
    if not m:
        return "", report_md
    start = m.end()
    nxt = re.search(r"^##\s+", report_md[start:], re.M)
    if nxt:
        summary = report_md[start:start + nxt.start()].strip()
        rest = report_md[start + nxt.start():].strip()
    else:
        summary, rest = report_md[start:].strip(), ""
    return summary, rest


def build_html(d: dict) -> str:
    ticker = d["company_of_interest"]
    date = d["trade_date"]
    name = CN_NAME.get(ticker, ticker)
    # A-share routing drives the data-source / disclaimer text: A-shares pull from
    # akshare(东财) + yfinance with 千股千评/资金/政策 proxies, US names are yfinance-only.
    is_cn = bool(re.match(r"^\d{6}(\.(SZ|SS|BJ))?$", str(ticker).strip(), re.I)) or \
        str(ticker).upper().endswith((".SZ", ".SS", ".BJ"))
    src_line = "akshare/东财 + yfinance" if is_cn else "yfinance（美股行情/财报/新闻）"
    disc_src = "东方财富/akshare 与 yfinance" if is_cn else "yfinance"
    disc_proxy = "情绪/资金/政策为 A 股代理指标，" if is_cn else ""
    final = d.get("final_trade_decision", "")
    trader = d.get("trader_investment_decision", "")
    ids = d.get("investment_debate_state", {})

    report_md = d.get("final_report", "")
    meta = parse_meta(report_md)

    # Card values come from the Report Writer's canonical META when present, so
    # the cards match the report body exactly (single source of truth). Fall
    # back to the trader's structured fields for old logs without META.
    m = re.search(r"FINAL TRANSACTION PROPOSAL[:：]\s*\*\*([^*]+)\*\*", trader)
    proposal = m.group(1).strip() if m else ""
    if meta:
        rating_label, rcolor = resolve_rating(meta.get("rating", ""), proposal)
        action = meta.get("action", "") or proposal or "—"
        entry = meta.get("entry", "") or "—"
        stop = meta.get("stop", "") or "—"
        target = meta.get("target", "")
    else:
        rating_raw = field(final, "Rating") or field(ids.get("judge_decision", ""), "Recommendation")
        rating_label, rcolor = resolve_rating(rating_raw, proposal)
        action = field(trader, "Action") or proposal or "—"
        entry = field(trader, "Entry Price") or "—"
        stop = field(trader, "Stop Loss") or "—"
        target = ""

    cards = [("投资评级", f'<span class="rating" style="background:{rcolor}">{rating_label}</span>'),
             ("操作", action),
             ("参考买入价", entry),
             ("止损位", stop)]
    if target:
        cards.append(("目标/合理估值", target))
    card_html = "".join(
        f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in cards)

    summary, rest = split_summary(strip_meta(report_md))
    if report_md:
        summary_html = md2html(summary) if summary else "<p class='muted'>（无摘要）</p>"
        body_html = md2html(rest)
    else:  # fallback for old logs without an integrated report
        summary_html = md2html(field(final, "Executive Summary") or "")
        body_html = md2html(_AI_NOISE.sub("", d.get("investment_plan", "")))

    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{name} {ticker} 研究报告</title>
<style>
  @page {{ size:A4; margin:14mm 14mm 15mm; }}
  *{{ box-sizing:border-box; }}
  :root{{ --navy:#0a2540; --gold:#b8860b; --ink:#1f2328; --line:#d7dce3; --rc:{rcolor}; }}
  body{{ font-family:"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;
         color:var(--ink); line-height:1.62; font-size:11.5px; margin:0; }}
  .masthead{{ background:var(--navy); color:#fff; padding:15px 19px; border-radius:5px;
              display:flex; justify-content:space-between; align-items:flex-end; }}
  .masthead .tag{{ font-size:10px; letter-spacing:3px; color:var(--gold); font-weight:700; }}
  .masthead h1{{ font-family:"Songti SC","Source Han Serif SC",Georgia,serif; font-size:23px; margin:4px 0 2px; }}
  .masthead .meta{{ font-size:10.5px; color:#b9c4d4; }}
  .masthead .ratingbig{{ font-family:Georgia,serif; font-size:20px; font-weight:700; color:var(--rc);
                         background:#fff; padding:3px 15px; border-radius:5px; }}
  .summary{{ display:flex; gap:8px; margin:13px 0 4px; }}
  .card{{ flex:1; background:#f7f9fc; border:1px solid var(--line); border-top:3px solid var(--navy);
          border-radius:6px; padding:8px 11px; }}
  .card .k{{ color:#5b6675; font-size:10px; }}
  .card .v{{ font-size:14px; font-weight:700; margin-top:3px; color:var(--navy); }}
  .card .rating{{ color:#fff; padding:2px 12px; border-radius:4px; font-size:14px; }}
  .callout{{ border:1px solid var(--line); border-left:5px solid var(--gold); background:#fffdf6;
             border-radius:6px; padding:12px 18px; margin:14px 0 6px; }}
  .callout h3{{ font-family:"Songti SC",Georgia,serif; color:var(--navy); margin:0 0 6px; font-size:16px; }}
  .body h2{{ font-family:"Songti SC","Source Han Serif SC",Georgia,serif; font-size:16px; color:var(--navy);
       margin:22px 0 8px; padding-bottom:5px; border-bottom:2px solid var(--navy); page-break-after:avoid; }}
  .body h3{{ font-size:13px; color:#24323f; margin:13px 0 5px; }}
  .body h1{{ font-size:16px; color:var(--navy); }}  /* safety: never expected, but won't break layout */
  table{{ border-collapse:collapse; width:100%; margin:8px 0; font-size:11px; }}
  th,td{{ border:1px solid var(--line); padding:5px 8px; text-align:left; vertical-align:top; }}
  th{{ background:#eef2f7; color:var(--navy); }}
  tr:nth-child(even) td{{ background:#fafbfd; }}
  /* Keep short label cells (first column) on one line — avoids ugly
     "主业升\n级" single-character wraps seen when the column is too narrow. */
  .body table td:first-child, .body table th:first-child{{ white-space:nowrap; }}
  blockquote{{ border-left:3px solid var(--gold); margin:8px 0; padding:2px 12px; color:#444; background:#fafafa; }}
  strong{{ color:#0f2233; }}
  .muted{{ color:#9aa3af; }}
  .disc{{ margin-top:24px; padding-top:10px; border-top:1px solid var(--line); color:#5b6675; font-size:10px; }}
</style></head><body>
  <div class="masthead">
    <div>
      <div class="tag">EQUITY RESEARCH · 多智能体投研</div>
      <h1>{name}（{ticker}）</h1>
      <div class="meta">分析日 {date} · TradingAgents(LangGraph) · DeepSeek-chat · {src_line}</div>
    </div>
    <div class="ratingbig">{rating_label}</div>
  </div>

  <div class="summary">{card_html}</div>

  <div class="callout">
    <h3>摘要与核心结论</h3>
    {summary_html}
  </div>

  <div class="body">{body_html}</div>

  <div class="disc">本报告由 AI 多智能体系统（TradingAgents）经“报告整合官”整合撰写，数据来自{disc_src}，
  {disc_proxy}仅供研究与方法论展示，<b>不构成任何投资建议</b>。生成时间 {gen}。</div>
</body></html>"""


def main():
    ticker = sys.argv[1]
    logs = glob.glob(os.path.join(HOME, ".tradingagents", "logs", ticker,
                                  "TradingAgentsStrategy_logs", "full_states_log_*.json"))
    if not logs:
        print(f"No log found for {ticker}")
        sys.exit(1)
    d = json.load(open(max(logs, key=os.path.getmtime), encoding="utf-8"))
    if not d.get("final_report"):
        print("[warn] no final_report in log — rerun the pipeline so the Report Writer produces it.")
    name = CN_NAME.get(ticker, ticker)
    base = f"TradingAgents_{name}_{ticker}_研究报告"
    html_path = os.path.join(HOME, "Desktop", base + ".html")
    pdf_path = os.path.join(HOME, "Desktop", base + ".pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(d))
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", "file://" + html_path], check=True, capture_output=True)
    print(f"PDF: {pdf_path}  ({os.path.getsize(pdf_path)//1024} KB)")


if __name__ == "__main__":
    main()
