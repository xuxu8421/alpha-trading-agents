"""Minimal local demo runner for TradingAgents (reads .env)."""

import sys

from dotenv import load_dotenv

load_dotenv()  # load .env before importing config so env overrides apply

from tradingagents.dataflows.akshare_cn import is_a_share  # noqa: E402
from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    trade_date = sys.argv[2] if len(sys.argv) > 2 else "2024-05-10"
    position_context = sys.argv[3] if len(sys.argv) > 3 else ""
    config = DEFAULT_CONFIG.copy()

    if is_a_share(ticker):
        strict = bool(config.get("strict_data_mode"))
        # In strict mode, the configured chain contains only the A-share data
        # layer. The shared indicator engine still calculates locally from
        # akshare/Tencent OHLCV; it never asks Yahoo for an A-share proxy.
        cn_chain = "akshare" if strict else "akshare,yfinance"
        config["data_vendors"] = {
            **config["data_vendors"],
            "core_stock_apis": cn_chain,
            "technical_indicators": "akshare" if strict else "akshare,yfinance",
            "fundamental_data": cn_chain,
            "news_data": cn_chain,
        }
        print(
            ">>> A-share detected: market/fundamental/news -> "
            f"{cn_chain}; strict_data_mode={strict}; sentiment -> 千股千评+个股新闻"
        )

    print(
        f">>> provider={config['llm_provider']} deep={config['deep_think_llm']} "
        f"quick={config['quick_think_llm']} lang={config['output_language']}"
    )
    print(f">>> analyzing {ticker} @ {trade_date}\n")

    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate(
        ticker,
        trade_date,
        position_context=position_context,
    )
    print("\n\n================ FINAL DECISION ================\n")
    print(decision)


if __name__ == "__main__":
    main()
