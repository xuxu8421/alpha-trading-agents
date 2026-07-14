from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RND_HOME = Path(os.getenv("TRADINGAGENTS_RND_DIR", Path.home() / ".tradingagents" / "rnd"))
DB_PATH = Path(os.getenv("TRADINGAGENTS_RND_DB", RND_HOME / "alpha_rnd.sqlite3"))
DASHBOARD_PATH = Path(
    os.getenv("TRADINGAGENTS_RND_DASHBOARD", PROJECT_ROOT / "workbench" / "alpha_rnd_dashboard.html")
)

PROMPT_VERSION = os.getenv("TRADINGAGENTS_RND_PROMPT_VERSION", "a_share_rnd_v0.1")
HORIZONS = (1, 5, 10, 20, 60)
PRIMARY_HORIZON = 5

STOCK_UNIVERSE = [
    {
        "name": "中科创达",
        "ticker": "300496.SZ",
        "pool": "观察池",
        "theme": "AI终端 / 智能汽车软件",
        "role": "成长弹性",
        "cadence": "周五复盘",
    },
    {
        "name": "江化微",
        "ticker": "603078.SS",
        "pool": "观察池",
        "theme": "半导体湿电子化学品",
        "role": "国产替代",
        "cadence": "周五复盘",
    },
    {
        "name": "铂科新材",
        "ticker": "300811.SZ",
        "pool": "观察池",
        "theme": "磁性材料 / AI电源",
        "role": "产业趋势",
        "cadence": "周五复盘",
    },
    {
        "name": "联泓新科",
        "ticker": "003022.SZ",
        "pool": "观察池",
        "theme": "新材料 / 光伏材料",
        "role": "周期拐点",
        "cadence": "周五复盘",
    },
    {
        "name": "紫光股份",
        "ticker": "000938.SZ",
        "pool": "观察池",
        "theme": "数字基础设施 / 算力网络",
        "role": "稳健科技",
        "cadence": "周五复盘",
    },
]

KNOWN_NAMES = {
    "600487.SS": "亨通光电",
    "600378.SH": "昊华科技",
}


def ticker_name(ticker: str) -> str:
    normalized = ticker.upper()
    for item in STOCK_UNIVERSE:
        if item["ticker"].upper() == normalized:
            return item["name"]
    return KNOWN_NAMES.get(normalized, ticker)


def ensure_dirs() -> None:
    RND_HOME.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
