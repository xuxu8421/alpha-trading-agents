from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import RND_HOME, ensure_dirs


INTELLIGENCE_DIR = RND_HOME / "industry_intelligence"
LATEST_PATH = INTELLIGENCE_DIR / "latest.json"

SOURCE_TIERS = {
    "A": "公司公告、交易所、监管机构、公司官网与正式技术文档",
    "B": "产业机构、券商研究、供应链访谈与高质量行业媒体",
    "C": "财经媒体和可追溯的二手报道",
    "D": "公众号、雪球、个人博主与社交平台观点",
}

SOURCE_WATCHLIST = [
    {
        "name": "巨潮资讯",
        "kind": "company_filing",
        "tier": "A",
        "url": "https://www.cninfo.com.cn/",
        "focus": "A股公告、年报、投资者关系记录",
    },
    {
        "name": "上交所 / 深交所",
        "kind": "exchange",
        "tier": "A",
        "url": "https://www.sse.com.cn/",
        "focus": "交易所公告、监管与规则",
    },
    {
        "name": "NVIDIA / Micron / TSMC 官方信息",
        "kind": "global_primary",
        "tier": "A",
        "url": "https://www.nvidia.com/en-us/data-center/",
        "focus": "AI系统架构、存储、封装和技术路线",
    },
    {
        "name": "财联社",
        "kind": "financial_wire",
        "tier": "B",
        "url": "https://www.cls.cn/telegraph",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/8e9c7dfaf07013f4da379dd0f87c3a298f2ed501.xml",
        "focus": "A股快讯、公司事件、资金与题材催化",
    },
    {
        "name": "第一财经",
        "kind": "financial_media",
        "tier": "B",
        "url": "https://www.yicai.com/",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/e2cc4ff2ae914ebfd4150420ece80dd93be7a6d9.xml",
        "focus": "宏观、产业、公司与市场风格复盘",
    },
    {
        "name": "证券时报",
        "kind": "securities_media",
        "tier": "B",
        "url": "https://www.stcn.com/",
        "focus": "政策、上市公司和资本市场动态",
    },
    {
        "name": "中国证券报",
        "kind": "securities_media",
        "tier": "B",
        "url": "https://www.cs.com.cn/",
        "focus": "政策、上市公司和机构观点交叉验证",
    },
    {
        "name": "上海证券报",
        "kind": "securities_media",
        "tier": "B",
        "url": "https://www.cnstock.com/",
        "focus": "交易所市场、上市公司和产业政策",
    },
    {
        "name": "半导体行业观察",
        "kind": "industry_wechat",
        "tier": "B",
        "url": "https://wechat2rss.bestblogs.dev/feed/39f625822b35f7573a7e70d3b27a735a3c0d24a4.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/39f625822b35f7573a7e70d3b27a735a3c0d24a4.xml",
        "focus": "芯片、设备、材料、存储和先进封装",
    },
    {
        "name": "晚点AI",
        "kind": "ai_industry_media",
        "tier": "B",
        "url": "https://wechat2rss.bestblogs.dev/feed/316def62ee3a6d499bf3981ffe22a09bf7256265.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/316def62ee3a6d499bf3981ffe22a09bf7256265.xml",
        "focus": "AI公司、产品、应用商业化和产业访谈",
    },
    {
        "name": "甲子光年",
        "kind": "ai_industry_media",
        "tier": "B",
        "url": "https://wechat2rss.bestblogs.dev/feed/1c4008936645d5c17239d99bba91522cf2bdfa26.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/1c4008936645d5c17239d99bba91522cf2bdfa26.xml",
        "focus": "科技产业、AI商业化和创新公司",
    },
    {
        "name": "远川研究所",
        "kind": "industry_commentary",
        "tier": "C",
        "url": "https://wechat2rss.bestblogs.dev/feed/fae262a71b2c0f867011d3c40e02bff3272d90df.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/fae262a71b2c0f867011d3c40e02bff3272d90df.xml",
        "focus": "产业周期、商业模式和公司历史脉络",
    },
    {
        "name": "饭统戴老板",
        "kind": "industry_commentary",
        "tier": "C",
        "url": "https://wechat2rss.bestblogs.dev/feed/5f4c620560bd63023df9fb7d330aeee524e41676.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/5f4c620560bd63023df9fb7d330aeee524e41676.xml",
        "focus": "产业周期、公司史和宏观叙事",
    },
    {
        "name": "聪明投资者",
        "kind": "investor_interviews",
        "tier": "C",
        "url": "https://wechat2rss.bestblogs.dev/feed/d141c2a7c08d56f573b32c7e2f09b6ee779dc51d.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/d141c2a7c08d56f573b32c7e2f09b6ee779dc51d.xml",
        "focus": "基金经理访谈、投资框架和行业观点",
    },
    {
        "name": "点拾投资",
        "kind": "investor_interviews",
        "tier": "C",
        "url": "https://wechat2rss.bestblogs.dev/feed/e460ce1e8b48d9c4baa4fb762e93e4409c7a14fd.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/e460ce1e8b48d9c4baa4fb762e93e4409c7a14fd.xml",
        "focus": "投资人访谈、行业观点和组合方法",
    },
    {
        "name": "思想钢印",
        "kind": "personal_investment_wechat",
        "tier": "D",
        "url": "https://wechat2rss.bestblogs.dev/feed/9c25c03fc6a13471a096f0737d1cdfe62a7e95bc.xml",
        "feed_url": "https://wechat2rss.bestblogs.dev/feed/9c25c03fc6a13471a096f0737d1cdfe62a7e95bc.xml",
        "focus": "个人投资框架、估值和市场风格假设",
    },
    {
        "name": "雪球讨论热度",
        "kind": "social_sentiment",
        "tier": "D",
        "url": "https://xueqiu.com/",
        "focus": "拥挤度、叙事扩散和散户关注变化",
    },
    {
        "name": "风动幡动还是心动",
        "kind": "wechat_blogger",
        "tier": "D",
        "url": "https://mp.weixin.qq.com/s/JUkQlqaR3jCyVvNw1YC0wg",
        "focus": "市场风格、海外映射和交易线索；只作假设来源",
    },
]


def seed_industry_intelligence() -> dict[str, Any]:
    today = date.today().isoformat()
    return {
        "trade_date": today,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "regime": {
            "label": "硬件强势后的软件扩散观察",
            "status": "watch",
            "score": 18,
            "confidence": 36,
            "horizon": "3-5个交易日",
            "summary": "出现海外AI硬件回落、应用软件反弹的单日线索，但尚不足以确认A股主线完成切换。",
        },
        "signals": [
            {
                "id": "hardware_to_software_rotation",
                "title": "AI硬件向AI应用软件高低切",
                "nature": "style_rotation",
                "status": "watch",
                "confidence": 36,
                "horizon": "3-5个交易日",
                "observation": "文章观察到美股存储、光通信和半导体回落，而Salesforce、Microsoft、Workday、ServiceNow、Palantir、Meta和AppLovin相对走强。",
                "interpretation": "这是资金从拥挤硬件方向向低位软件扩散的假设，不等同于AI硬件订单、资本开支或供给瓶颈发生反转。",
                "why_it_matters": "若A股同步出现软件板块成交占比提升、涨停扩散和相对强度连续走高，短线选股权重应从纯硬件拥挤度转向应用兑现和低位扩散。",
                "affected_tracks": ["算力芯片", "存储与内存", "网络与光通信", "AI软件与应用"],
                "a_share_watch": ["中科创达", "科大讯飞", "金山办公", "用友网络", "恒生电子", "广联达"],
                "checks": [
                    {"name": "软件相对硬件3日强弱", "status": "pending", "rule": "软件代理组合连续3日跑赢硬件代理组合"},
                    {"name": "成交扩散", "status": "pending", "rule": "软件板块成交额占比连续2日提升"},
                    {"name": "市场宽度", "status": "pending", "rule": "软件上涨家数和涨停家数同步扩大"},
                    {"name": "基本面确认", "status": "pending", "rule": "订单、ARR、付费用户或盈利预期出现可验证上修"},
                ],
                "invalidation": "硬件方向在放量回调后快速修复，软件仅单日反弹且成交、宽度和盈利预期均未改善。",
                "sources": [
                    {
                        "name": "风动幡动还是心动",
                        "title": "AI硬件切AI应用软件",
                        "url": "https://mp.weixin.qq.com/s/JUkQlqaR3jCyVvNw1YC0wg",
                        "published_at": "2026-07-01 21:51",
                        "tier": "D",
                        "kind": "公众号观点",
                    }
                ],
            }
        ],
        "items": [
            {
                "id": "wechat-hardware-to-software-20260701",
                "author": "风动幡动还是心动",
                "publisher": "个人公众号",
                "tier": "D",
                "title": "AI硬件切AI应用软件",
                "url": "https://mp.weixin.qq.com/s/JUkQlqaR3jCyVvNw1YC0wg",
                "published_at": "2026-07-01 21:51",
                "summary": "作者观察到美股存储、光通信和半导体走弱，而Salesforce、Microsoft、Workday、ServiceNow、Palantir、Meta和AppLovin等软件与应用方向走强，据此提出7月可能发生AI硬件向AI应用软件高低切。",
                "system_view": "有价值的是跨市场风格切换线索，但当前只有单日价格表现，尚未证明A股软件形成持续主线，也不能据此判断AI硬件基本面反转。",
                "tags": ["风格切换", "AI软件", "海外映射"],
                "status": "watch",
            }
        ],
        "source_watchlist": SOURCE_WATCHLIST,
        "source_tiers": SOURCE_TIERS,
        "quality": {
            "status": "seeded",
            "primary_sources": 0,
            "independent_sources": 1,
            "note": "当前信号来自单一公众号观点，已降级为观察项；每日更新需补充行情和A/B级来源。",
        },
    }


def validate_industry_intelligence(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("industry intelligence payload must be an object")
    if not payload.get("trade_date"):
        raise ValueError("trade_date is required")
    if not isinstance(payload.get("signals"), list):
        raise ValueError("signals must be a list")
    if not isinstance(payload.get("items", []), list):
        raise ValueError("items must be a list")
    for index, signal in enumerate(payload["signals"]):
        for field in ("id", "title", "status", "observation", "interpretation", "checks", "sources"):
            if field not in signal:
                raise ValueError(f"signals[{index}].{field} is required")
        if signal["status"] not in {"watch", "confirmed", "weakening", "rejected"}:
            raise ValueError(f"unsupported signal status: {signal['status']}")
        if not 0 <= float(signal.get("confidence", 0)) <= 100:
            raise ValueError("signal confidence must be between 0 and 100")
        for source in signal.get("sources", []):
            if source.get("tier") not in SOURCE_TIERS:
                raise ValueError(f"unsupported source tier: {source.get('tier')}")
    for index, item in enumerate(payload.get("items", [])):
        for field in ("id", "author", "tier", "title", "url", "summary", "system_view", "status"):
            if not item.get(field):
                raise ValueError(f"items[{index}].{field} is required")
        if item["tier"] not in SOURCE_TIERS:
            raise ValueError(f"unsupported item source tier: {item['tier']}")
    payload.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    existing_sources = payload.get("source_watchlist") or []
    source_by_name = {str(source.get("name")): source for source in SOURCE_WATCHLIST}
    for source in existing_sources:
        source_by_name.setdefault(str(source.get("name")), source)
    payload["source_watchlist"] = list(source_by_name.values())
    payload.setdefault("source_tiers", SOURCE_TIERS)
    payload.setdefault("quality", {})
    return payload


def persist_industry_intelligence(payload: dict[str, Any]) -> Path:
    ensure_dirs()
    INTELLIGENCE_DIR.mkdir(parents=True, exist_ok=True)
    normalized = validate_industry_intelligence(payload)
    dated_path = INTELLIGENCE_DIR / f"{normalized['trade_date']}.json"
    encoded = json.dumps(normalized, ensure_ascii=False, indent=2)
    dated_path.write_text(encoded, encoding="utf-8")
    LATEST_PATH.write_text(encoded, encoding="utf-8")
    return dated_path


def ingest_industry_intelligence(path: Path) -> Path:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return persist_industry_intelligence(payload)


def latest_industry_intelligence() -> dict[str, Any]:
    if LATEST_PATH.exists():
        try:
            return validate_industry_intelligence(json.loads(LATEST_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return seed_industry_intelligence()
