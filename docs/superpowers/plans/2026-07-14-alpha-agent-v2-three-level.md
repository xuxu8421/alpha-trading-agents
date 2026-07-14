# Alpha Agent V2 Three-Level Research Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Alpha Agent from a sequence of isolated reports into a traceable macro-policy → industry → company research system that preserves the existing dashboard/PDF UI, produces a decision-oriented human report, and reviews its hypotheses every Friday.

**Architecture:** Add macro, industry, financial-report, and expectation-gap stages to the LangGraph before the existing debate and trading stages. Store their outputs as first-class state fields, inject the shared context into downstream specialists, retain the existing report rendering surface, and extend the R&D database with hypothesis-level weekly reviews.

**Tech Stack:** Python 3.10+, LangGraph, LangChain, Pydantic, SQLite, pytest, existing AkShare/Tencent/Sina/Eastmoney data layer.

## Global Constraints

- Preserve the existing dashboard and PDF rendering entry points.
- Keep the v1 graph available on `release/alpha-agent-v1-pre-three-level` and tag `alpha-agent-v1-pre-three-level-2026-07-14`.
- Treat macro, industry, and company analysis as distinct levels connected by explicit transmission paths.
- Financial numbers remain deterministic tool outputs; LLMs interpret rather than invent calculations.
- Every forecast must include horizon, confidence, catalysts, and invalidation conditions.
- Weekly review must distinguish outcome error, thesis error, industry error, macro error, timing error, and data error.
- No future information may enter a historical run.

---

### Task 1: Restore the V1 test contract and define V2 state

**Files:**
- Modify: `tests/test_rnd_market_pulse.py`
- Modify: `tradingagents/agents/utils/agent_states.py`
- Modify: `tradingagents/graph/propagation.py`
- Test: `tests/test_research_context_state.py`

**Interfaces:**
- Produces state fields `macro_report`, `industry_report`, `financial_report`, `expectation_report`, `evidence_ledger`, and `position_context`.

- [ ] Write tests asserting the initial state contains every V2 field and the market-phase test accepts the implementation's current phase vocabulary.
- [ ] Run the focused tests and verify the new state test fails before production changes.
- [ ] Add the V2 fields to `AgentState` and `Propagator.create_initial_state` with empty safe defaults.
- [ ] Run focused tests and the original market-pulse test.
- [ ] Commit the state contract.

### Task 2: Add macro and industry context stages

**Files:**
- Create: `tradingagents/agents/analysts/industry_analyst.py`
- Modify: `tradingagents/agents/analysts/policy_analyst.py`
- Modify: `tradingagents/agents/__init__.py`
- Modify: `tradingagents/graph/setup.py`
- Test: `tests/test_three_level_graph.py`
- Test: `tests/test_industry_analyst.py`

**Interfaces:**
- `create_policy_analyst(llm)` returns both `policy_report` and `macro_report`.
- `create_industry_analyst(llm)` consumes `macro_report`, the existing R&D industry-chain brief, and instrument identity; it produces `industry_report`.
- Graph order begins `Policy Analyst -> Industry Analyst -> selected analysts`.

- [ ] Write failing graph-order and industry-context tests.
- [ ] Verify failures are caused by the missing node and output.
- [ ] Implement a compact industry evidence builder using `build_industry_chain_brief`, `latest_industry_intelligence`, and the tracked company mapping.
- [ ] Upgrade the policy prompt to separate country regime, policy direction, industry transmission, horizon, and invalidation.
- [ ] Register and connect both nodes before the existing specialist chain.
- [ ] Run focused tests and commit.

### Task 3: Propagate industry context and add professional financial-report analysis

**Files:**
- Create: `tradingagents/agents/analysts/financial_report_analyst.py`
- Create: `tradingagents/agents/analysts/financial_reading_framework.py`
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Modify: `tradingagents/agents/analysts/news_analyst.py`
- Modify: `tradingagents/agents/analysts/sentiment_analyst.py`
- Modify: `tradingagents/agents/analysts/fundamentals_analyst.py`
- Modify: `tradingagents/agents/__init__.py`
- Modify: `tradingagents/graph/setup.py`
- Test: `tests/test_financial_report_analyst.py`
- Test: `tests/test_industry_context_propagation.py`

**Interfaces:**
- `create_financial_report_analyst(llm)` consumes annual and quarterly three-statement data plus `industry_report`; it produces `financial_report`.
- `financial_reading_framework(ticker, industry_report)` returns the Tang-style falsification checklist and industry-specific checks.
- Existing specialist prompts receive the same macro and industry context.

- [ ] Write failing tests for the checklist, financial-report prompt, and prompt propagation.
- [ ] Verify tests fail before implementation.
- [ ] Implement the checklist covering audit opinion, balance-sheet assets, liabilities, income quality, cash portrait, notes, management claims, manipulation traces, longitudinal comparison, and peer comparison.
- [ ] Implement deterministic statement prefetch with explicit source limitations and a cite-or-abstain instruction.
- [ ] Insert the financial-report node after the selected specialist chain and before expectations/debate.
- [ ] Add industry-relative instructions to market, news, sentiment, and fundamentals prompts.
- [ ] Run focused tests and commit.

### Task 4: Add expectation-gap synthesis and repair downstream information loss

**Files:**
- Create: `tradingagents/agents/analysts/expectation_analyst.py`
- Modify: `tradingagents/agents/__init__.py`
- Modify: `tradingagents/graph/setup.py`
- Modify: `tradingagents/agents/researchers/bull_researcher.py`
- Modify: `tradingagents/agents/researchers/bear_researcher.py`
- Modify: `tradingagents/agents/managers/research_manager.py`
- Modify: `tradingagents/agents/trader/trader.py`
- Modify: `tradingagents/agents/risk_mgmt/aggressive_debator.py`
- Modify: `tradingagents/agents/risk_mgmt/neutral_debator.py`
- Modify: `tradingagents/agents/risk_mgmt/conservative_debator.py`
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Test: `tests/test_expectation_context.py`

**Interfaces:**
- `create_expectation_analyst(llm)` produces `expectation_report` with macro, industry, company, market-implied, bull/base/bear, catalyst, and invalidation sections.
- Every downstream decision role directly receives macro, industry, financial-report, and expectation reports rather than relying only on conversational summaries.

- [ ] Write failing tests that capture downstream prompts and assert all four contexts are present.
- [ ] Verify the failures.
- [ ] Add and wire the expectation node before Bull/Bear.
- [ ] Inject first-class context into research manager, trader, all risk roles, and portfolio manager.
- [ ] Require Bull and Bear to distinguish facts from forecasts and challenge industry/company assumptions.
- [ ] Run focused tests and commit.

### Task 5: Preserve the UI while rewriting the report for decisions

**Files:**
- Modify: `tradingagents/agents/managers/report_writer.py`
- Modify: `tradingagents/reporting.py`
- Modify: `tests/test_reporting.py`
- Test: `tests/test_report_writer_v2.py`

**Interfaces:**
- The final report keeps the existing `<!--META ...-->` contract used by the PDF/UI.
- The report adds macro-to-industry transmission, industry position/expectations, financial quality, expectation gap, scenario matrix, decision, and invalidation checklist.

- [ ] Write failing tests for V2 material inclusion and report-tree files.
- [ ] Verify failures.
- [ ] Extend report materials and fixed structure without changing the rendering API.
- [ ] Save `macro.md`, `industry.md`, `financial_report.md`, and `expectation.md` under the analyst report tree.
- [ ] Run reporting tests and commit.

### Task 6: Upgrade the Friday review into a hypothesis-learning loop

**Files:**
- Modify: `tradingagents/rnd/storage.py`
- Create: `tradingagents/rnd/thesis_review.py`
- Modify: `tradingagents/rnd/signals.py`
- Modify: `tradingagents/rnd/optimizer.py`
- Modify: `tradingagents/rnd/runner.py`
- Modify: `tradingagents/rnd/dashboard.py`
- Modify: `docs/alpha_rnd_architecture.md`
- Test: `tests/test_rnd_thesis_review.py`
- Test: `tests/test_rnd_storage.py`

**Interfaces:**
- SQLite table `thesis_snapshots` stores report-date hypotheses and validation fields.
- SQLite table `thesis_reviews` stores Friday attribution by macro, industry, company, valuation/expectation, timing, and data quality.
- `build_weekly_thesis_review(conn, trade_date)` returns a dashboard-ready payload and creates improvement tasks only when evidence is sufficient.

- [ ] Write failing migration, extraction, and attribution tests.
- [ ] Verify failures.
- [ ] Add additive SQLite migrations for hypothesis snapshots and reviews.
- [ ] Extract V2 claims from completed graph states during log ingestion.
- [ ] Implement deterministic weekly attribution using returns, relative returns, invalidation text, report degradations, and available industry/macro evidence.
- [ ] Run the thesis review in `weekly` and `optimize` modes.
- [ ] Add a dashboard section without changing the existing visual system.
- [ ] Update the architecture document and commit.

### Task 7: Full verification and GitHub delivery

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Branch: `feature/alpha-agent-v2-three-level`.
- Delivery: pushed branch plus draft pull request targeting `main`.

- [ ] Document V1/V2 branches, graph stages, state fields, Friday loop, and known data limitations.
- [ ] Run `ruff check tradingagents tests` and resolve errors introduced by V2.
- [ ] Run `python3 -m pytest -q` and require zero failures.
- [ ] Inspect `git diff --check` and `git status --short`.
- [ ] Push the feature branch.
- [ ] Open a draft PR with implementation summary, tests, migration notes, and known limitations.

