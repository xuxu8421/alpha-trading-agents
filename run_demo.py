"""Minimal local demo runner for TradingAgents (reads .env)."""
import sys
from dotenv import load_dotenv

load_dotenv()  # load .env before importing config so env overrides apply

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
trade_date = sys.argv[2] if len(sys.argv) > 2 else "2024-05-10"

config = DEFAULT_CONFIG.copy()

# A-share tickers (300811.SZ / 600519.SS / bare 6-digit) have no English
# news/social coverage — route news + global news through akshare (东方财富),
# falling back to yfinance for anything akshare can't serve. The sentiment
# analyst auto-swaps StockTwits/Reddit for 千股千评 + 个股新闻 on its own.
from tradingagents.dataflows.akshare_cn import is_a_share
if is_a_share(ticker):
    config["data_vendors"] = {**config["data_vendors"], "news_data": "akshare,yfinance"}
    print(">>> A-share detected: news_data -> akshare,yfinance; sentiment -> 千股千评+个股新闻")

print(f">>> provider={config['llm_provider']} deep={config['deep_think_llm']} "
      f"quick={config['quick_think_llm']} lang={config['output_language']}")
print(f">>> analyzing {ticker} @ {trade_date}\n")

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate(ticker, trade_date)

print("\n\n================ FINAL DECISION ================\n")
print(decision)
