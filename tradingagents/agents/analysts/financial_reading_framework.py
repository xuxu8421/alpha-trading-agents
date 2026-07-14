"""Professional financial-reading checklist used by the financial agent."""

from __future__ import annotations


def financial_reading_framework(ticker: str, industry_report: str = "") -> str:
    """Build a falsification-first checklist inspired by public Tang Cha'o methods.

    The method is encoded as analysis discipline rather than copied book text:
    eliminate fraud/fragility first, read the balance sheet before profits, and
    validate management narratives with cash, notes, history, and peers.
    """
    industry = (industry_report or "").lower()
    industry_checks = []
    if any(word in industry for word in ("软件", "ai", "汽车", "研发")):
        industry_checks.extend(
            [
                "研发资本化比例、资本化政策变更与无形资产减值",
                "人员成本、合同负债、应收账款与回款周期",
                "软件许可/订阅/项目制收入结构及续费、单客价值",
                "智能汽车业务量价、客户集中度与项目生命周期",
            ]
        )
    if any(word in industry for word in ("制造", "材料", "设备", "半导体")):
        industry_checks.extend(
            ["产能利用率、在建工程转固和折旧压力", "存货跌价、客户认证与应收回款"]
        )
    if not industry_checks:
        industry_checks.append("按行业商业模式补充最能解释收入、利润和现金流的经营指标")

    return f"""## 财报阅读框架（标的 {ticker}）

原则：先排雷、后理解、再估值；数字由确定性工具提供，模型只解释，不补造。

1. 审计意见与报告边界：意见类型、关键审计事项、会计师变更、报告期和数据缺口。
2. 资产负债表优先：货币资金真实性；应收、存货、商誉、无形资产、在建工程质量；受限资产和表外义务。
3. 负债与资本结构：有息债务期限、担保、或有负债、合同负债、融资依赖和偿债安全垫。
4. 利润质量：收入确认、毛利率、费用率、非经常损益、少数股东损益；经营利润是否可重复。
5. 现金流画像：经营现金流与净利润匹配、自由现金流、资本开支、融资现金流和分红能力。
6. 附注与管理层说法：用附注、会计政策和分部数据核验管理层叙事，列出矛盾点。
7. 造假痕迹排雷：利润增而现金不增、应收/存货异常、毛利偏离同业、关联交易、频繁会计估计变更、大存大贷。
8. 五年纵向比较：增长、利润率、现金转换、资本回报和资产结构的趋势与拐点。
9. 同业横向比较：商业模式一致的可比公司，比较增速、毛利、ROIC、现金转换、估值和资产风险。
10. 行业专属检查：{'；'.join(industry_checks)}。
11. 估值只在排雷和盈利质量通过后进行；给出牛/基/熊假设、证据、期限和失效条件。
"""
