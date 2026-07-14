"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
    get_research_context_from_state,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.akshare_cn import fetch_cn_sentiment, is_a_share
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all sources. Each fetcher degrades gracefully and returns a
        # string (no exceptions surface from here), so the LLM always sees
        # something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)

        if is_a_share(ticker):
            # A-shares have no usable English social feeds (StockTwits/Reddit
            # return nothing). Swap in akshare CN sources: 千股千评 quant
            # sentiment + 个股新闻 headline buzz.
            cn = fetch_cn_sentiment(ticker)
            system_message = _build_cn_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                quant_block=cn["quant_block"],
                capital_block=cn.get("capital_block", ""),
                rating_block=cn.get("rating_block", ""),
                xueqiu_block=cn.get("xueqiu_block", ""),
                buzz_block=cn["buzz_block"],
            )
        else:
            stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
            reddit_block = fetch_reddit_posts(ticker)
            system_message = _build_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                stocktwits_block=stocktwits_block,
                reddit_block=reddit_block,
            )

        system_message += get_research_context_from_state(state)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}"
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — r/wallstreetbets, r/stocks, r/investing (past 7 days)
Community discussion. Engagement signal via upvote score and comment count. Subreddit character matters (r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight Reddit posts by engagement.** A 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


def _build_cn_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    quant_block: str,
    capital_block: str,
    rating_block: str,
    xueqiu_block: str,
    buzz_block: str,
) -> str:
    """A-share sentiment + capital-flow system message — CN sources (akshare / 东方财富).

    Mirrors :func:`_build_system_message` but swaps the English social feeds
    (StockTwits / Reddit) for A-share equivalents and adds two signals the US
    market doesn't expose this cleanly: the 主力/超大单 + 龙虎榜 capital-flow tape
    (smart money) and 券商研报 broker ratings (the institutional view).
    """
    return f"""You are an A-share market sentiment AND capital-flow analyst. Produce a comprehensive sentiment report for {ticker} for the period {start_date} to {end_date}, drawing on the CN data sources already collected for you (akshare / 东方财富). The A-share market has no usable StockTwits/Reddit feeds, so you instead read four complementary, genuinely A-share-native signals: 千股千评 quant sentiment, the 主力资金/龙虎榜 capital-flow tape, 券商研报 broker ratings, and the live 个股新闻 stream. This makes you the desk's read on BOTH retail emotion and smart-money positioning.

## Data sources (pre-fetched, in this prompt)

### 个股新闻 — Eastmoney per-ticker news, past ~7 days
Event-driven, institutional + media framing.
<start_of_news>
{news_block}
<end_of_news>

### 千股千评 — quantitative retail/institutional sentiment gauge
综合得分 (0–100), 关注指数 (retail attention), 人气排名 + 变动, 机构参与度, 主力成本 vs price. The A-share analogue of a retail-sentiment feed.
<start_of_quant_sentiment>
{quant_block}
<end_of_quant_sentiment>

### 资金面 — 主力/超大单 net flow + 龙虎榜 seats (SMART MONEY TAPE)
This is the most important institutional/hot-money signal in A-shares. 主力净流入 = big-order net buying; 龙虎榜 = 游资 (hot money) and 机构 seat activity.
<start_of_capital_flow>
{capital_block}
<end_of_capital_flow>

### 券商研报评级 — broker analyst ratings + earnings/PE targets (INSTITUTIONAL VIEW)
<start_of_ratings>
{rating_block}
<end_of_ratings>

### 雪球讨论热度 — retail-crowding / theme rotation (RETAIL SENTIMENT)
Whether this stock is a crowded retail topic (rank on the discussion board) and what themes retail is chasing market-wide.
<start_of_xueqiu>
{xueqiu_block}
<end_of_xueqiu>

### 个股新闻热点 — recent headline buzz
<start_of_buzz>
{buzz_block}
<end_of_buzz>

## How to analyze this data (best practices)

1. **综合得分 is the headline sentiment level**: >60 bullish, <40 bearish, ~50 neutral. Cross-check 关注指数 + 人气排名变动 — rising attention + rank means retail is heating up (near highs, a contrarian over-extension signal).

2. **The capital-flow tape is your smart-money read, and it often DIVERGES from retail.** If 主力资金 is net-OUTFLOW (主力净流出) for several days while 关注指数/人气 is spiking, that is institutions distributing into retail euphoria — a classic A-share top pattern; flag it loudly. Conversely, sustained 主力净流入 on a quiet tape can precede a move. Use 龙虎榜: frequent appearances = 游资 speculation (volatile); positive 机构买入净额 = real institutional accumulation.

3. **Broker ratings are the institutional anchor, but read them skeptically** — A-share sell-side skews bullish (买入/增持 dominate). What matters is the implied 目标 PE / earnings path vs the current price, and any rating *changes* or conspicuous *absence* of coverage.

4. **Triangulate the four sources for the real story.** The highest-conviction signal is agreement across retail (千股千评), smart money (资金面), and institutions (研报); the highest-value WARNING is divergence — especially retail-bullish + 主力流出 + stretched valuation.

5. **Identify recurring narrative themes** in the buzz (订单/产能/新产品/政策/行业景气) and distinguish 公告/订单 (events) from 概念炒作 (sentiment).

6. **Be honest about data limits** — note these are proxies, not a full social read; flag any source that errored.

7. **Past sentiment is not predictive.** Frame conclusions as signal for the trader to weigh alongside fundamentals and technicals.

## Output fields

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish.
- **overall_score**: 0 (max bearish) to 10 (max bullish); 5 is neutral. Keep consistent with overall_band.
- **confidence**: low / medium / high, based on data quality.
- **narrative**: Source-by-source breakdown (news / 千股千评 / 资金面 / 研报 / buzz), the retail-vs-smart-money divergence read, dominant themes, catalysts and risks, plus a markdown summary table of key signals (direction, source, supporting evidence).

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
