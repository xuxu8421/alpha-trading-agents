"""Report Writer (报告整合官) — the final synthesis role.

The analysts each produce their own report with their own headings, tone, and
occasional internal-monologue artefacts ("数据已获取，现在我来撰写…"). Concatenating
those raw outputs yields a report with broken heading hierarchy and AI-thinking
phrases. This role fixes that: it reads ALL upstream material (the four analyst
reports + the A-share policy report + the bull/bear and risk debates + the
trader plan + the final risk verdict) and rewrites it into ONE coherent,
professionally-edited A-share equity research note with a single consistent
structure — no copied sub-titles, no internal-AI phrasing.

It runs last (after the Portfolio Manager) and writes ``final_report``, which
is what the PDF renders. This keeps the PDF a pure renderer of clean editorial
output rather than a stitcher of raw fragments.
"""

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_report_writer(llm):
    """Create the report-writer node (uses the deep-thinking LLM for quality)."""

    def report_writer_node(state):
        ticker = state["company_of_interest"]
        date = state["trade_date"]
        ids = state.get("investment_debate_state", {})
        rds = state.get("risk_debate_state", {})

        materials = f"""【标的】{ticker}　【分析日】{date}

=== 基本面分析（含主营构成/分产品毛利）===
{state.get('fundamentals_report','')}

=== 行情技术面分析 ===
{state.get('market_report','')}

=== 情绪·资金面分析（千股千评/主力资金/龙虎榜/券商研报/雪球）===
{state.get('sentiment_report','')}

=== 政策面分析 ===
{state.get('policy_report','')}

=== 新闻与事件 ===
{state.get('news_report','')}

=== 多空研究员辩论·研究经理裁决 ===
{ids.get('judge_decision','')}

=== 交易员计划 ===
{state.get('trader_investment_plan','')}

=== 风控三方辩论·风控经理最终裁决（含评级与Executive Summary）===
{state.get('final_trade_decision','')}
"""

        system = f"""你是一家精品科技投资机构的【研报主编 / 报告整合官】。下面是针对该 A 股标的、由多位 AI 分析师与风控团队产出的全部原始材料。你的任务是把它们**整体重读、提炼、润色**，整合成**一篇结构统一、行文连贯、专业可读**的中文股票研究报告。

## 硬性要求（务必遵守）
1. **彻底去除 AI 内部独白与过程性语句**：如“数据已获取/已全部获取”“现在我来撰写/下面撰写详细报告”“好的，以下是…”“我现在拥有足够的数据”等，一律删除，不得出现在成品里。
2. **统一标题层级**：整篇只用 `##`（一级章节）和 `###`（二级小节）两层。**不要**把任何分析师自带的大标题（如“XXX 深度技术分析报告”“XXX 基本面研究报告”“分析日期/出品方”这类页眉）抄进来。公司名只在报告最顶部出现一次。
3. **不要逐段照抄**原始材料；要以主编视角**重新组织、合并重复、消除矛盾**，用你自己的话写成通顺的研报语言。保留所有**关键数字**（营收/利润/毛利率/PE/资金流/评级/价位等），数字以正文材料为准，不要自行新算。
4. 结论先行、观点明确，避免模棱两可的套话。
5. **表格适量、克制使用**——只在真正适合对照/速查的地方用表，其余以文字叙述为主：
   - **必须用表格**的只有两处：`二、多空研究结论`（多头/空头/裁决对照表）和 `九、关键数据汇总表`。
   - 其余章节（基本面/技术面/资金面/政策面等）**以文字解读为主**；如确有一组并列的关键价位或估值倍数，可用**一个**精简小表，但**不要每个小节都做表**，更不要把叙述性内容硬塞进表格。
   - 表格用标准 Markdown 语法（表头 + `---` 分隔行）。**首列用简短标签（2–6字），避免过长**；整体一份报告表格数量控制在 3 个以内为宜。

## 固定结构（严格按此输出 Markdown，不要加别的顶层标题）
（在正文最开头，先输出一行 HTML 注释形式的规范决策参数，供排版用，且必须与你正文一致；不要在注释外重复它）
<!--META {{"rating":"增持|买入|中性|持有|减持|卖出 之一", "action":"一句话操作(<=16字)", "entry":"参考买入/介入价位(<=16字，无则写 不建议建仓)", "stop":"止损位(<=16字)", "target":"目标价/合理估值区间(<=18字，无则空)"}}-->

## 摘要与核心结论
（一段 4–6 句：评级与操作建议先行 + 最关键的支撑/风险，让人读完这一段就懂。）

## 一、投资论点
（3–5 条递进式论点，每条加粗一句话主张 + 简短论证；这是报告的骨架。）

## 二、多空研究结论
（提炼多头与空头的核心交锋，以及研究/风控团队为何最终倾向当前评级。可用一个“多头 vs 空头”要点对照。）

## 三、基本面
（成长/盈利质量/财务健康/估值；务必说明毛利率变化是“结构稀释”还是“价格战”，引用分产品毛利数据。）

## 四、行情技术面
（趋势/均线/量价/关键支撑压力位，简洁。）

## 五、资金面 · 情绪 · 机构评级
（主力资金/龙虎榜/千股千评/券商评级/雪球散户拥挤度；重点指出“散户情绪 vs 主力动向”的背离与否。）

## 六、政策面
（产业/监管催化与风险；说明当前处于政策利好/真空/利空。无则如实说明。）

## 七、交易计划
（操作方向、参考买入价/止损/目标、分批与仓位建议；可用要点列出。）

## 八、关键跟踪与风险
（列出会**验证或推翻**当前结论的可跟踪信号，以及主要风险。）

## 九、关键数据汇总表
（**必须是一张 Markdown 表格**，作为全文收尾的速查表，覆盖该公司核心数据。建议列：`类别 | 指标 | 数值 | 简评`，按【成长 / 盈利能力 / 财务健康 / 估值 / 技术面 / 资金·情绪】分组各列 1–3 个最关键指标，数值带单位，简评一句话。所有数值以上文材料为准。）

{get_language_instruction()}

---
以下为原始材料：
{materials}
"""

        result = llm.invoke(system)
        report = result.content if hasattr(result, "content") else str(result)
        return {"messages": [AIMessage(content=report)], "final_report": report}

    return report_writer_node
