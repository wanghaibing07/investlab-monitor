[简体中文](README.md) · [English](README.en.md)

# InvestLab

**Know your QQQ / TQQQ holdings, market context, and risks before deciding whether to rebalance.**

InvestLab is an **open-source, local-first ETF portfolio monitor and strategy research tool**. It brings confirmed portfolio values, market data, strategy comparisons, and saved research into one place so you can answer: **What do I own? What changed? What should I review next—and why?**

It provides evidence for your decisions. **It does not place trades.**

**[Try the public demo (synthetic data, no login)](https://investlab-monitor.vercel.app/)** · **[Quick start](#quick-start)** · **[Verification](#how-to-check-the-results)** · **[简体中文](README.md)**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What it helps you do

| Your question | What InvestLab shows |
| --- | --- |
| **Where is my money allocated?** | Confirmed CNY values, weights, and valuation history for QQQ, TQQQ, QLD, and cash. |
| **What changed in the market?** | US-market closing data with source and session checks; invalid or stale data is labeled. |
| **Should I consider rebalancing?** | Step-by-step reference weights, reasons, and risk conditions for manual review. |
| **How do strategies compare?** | Historical returns, drawdowns, and volatility on comparable price data and fee assumptions. |
| **Can I review or restore past work?** | Recorded calculations, research evidence, account backups, and recovery checks. |

The normal flow is **check holdings → verify the market date → understand the rules and risks → decide for yourself**.

## Explore it first

**[Open the public demo](https://investlab-monitor.vercel.app/)**. No installation or account required. It includes Today's Decision, Strategy Research, and Activity & History views.

**All accounts, prices, and calculations in the demo are synthetic.** It demonstrates the interface, not live prices or personal investment recommendations. Private accounts are never exposed through the public demo.

To use your own information, choose one of two paths:

- **Run locally:** Get the research engine, independent checks, account imports, and records on your own computer.
- **Deploy your own private cloud:** Use Vercel Authentication to protect personal data and run manual or optionally scheduled research. The author's private dashboard is not a public service or shared demo account.

## Quick start

Requires **Python 3.11+**. These commands use a fictional account and sample market data—no API keys required.

~~~bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .

investlab --home ./runtime/demo init --demo
investlab --home ./runtime/demo run
investlab --home ./runtime/demo serve
~~~

Open **http://127.0.0.1:8765**. Press \`Ctrl+C\` to stop the server. On Windows PowerShell, activate the environment with \`.\.venv\Scripts\Activate.ps1\` instead.

To verify the local demo in a second terminal, run:

~~~bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
~~~

For confirmed holdings, transaction imports, or live market updates, see [local web editing](docs/LOCAL_WEB.md) and [operations](docs/OPERATIONS.md). **A change in portfolio value is not proof of a completed trade**; trades must be explicitly confirmed.

## Core ideas

### 1. Focused on QQQ / TQQQ, not an order-routing platform

The built-in long-term research reference is **60% QQQ + 40% TQQQ**. The monitor combines a 200-day trend and recent volatility with confirmed holdings, producing gradual allocation suggestions with a cap on each suggested TQQQ increase.

This is a research configuration—not a daily instruction to buy and not a universal portfolio. **TQQQ targets 3× the Nasdaq-100's daily return; its multi-day return is not simply 3× the index's cumulative return.**

### 2. Show the evidence behind the conclusion

- Market records include the **session date, source, and qualification status**. Two endpoints from the same vendor do not count as independent sources.
- Account integrity, strategy calculations, and independent recomputation are checked separately. Passing a software test does **not** establish that a strategy will outperform.
- Backtests compare fees, returns, drawdowns, and volatility, while preserving the timing of signals and executions to avoid look-ahead bias.
- Confirmed portfolio valuations and executed transactions stay distinct. A valuation chart is not silently presented as an investment-return chart.

### 3. Support ongoing records and scheduled research

- **Local deployment:** Timers, backups, restoration, and optional SMTP failure emails.
- **Private Vercel deployment:** US trading-session-aware schedules, duplicate-run control tied to account versions, separately stored research results, and a delayed retry. Each deployment must verify its **actual run receipts** before claiming successful operation.
- Automated research does not overwrite confirmed portfolio values or place broker orders. Email delivery requires a separate SMTP setup and test.

See [private cloud setup](docs/VERCEL_CLOUD.md), [Vercel daily automation](docs/VERCEL_DAILY_AUTOMATION.md), and [local scheduling and alerts](docs/DAILY_OPERATIONS.md).

## How to check the results

InvestLab treats two questions separately:

**Does the software follow its stated rules?** Automated tests, ledger audits, independent recalculation, and backup recovery checks provide evidence.

**Will a strategy work in the future?** That requires real out-of-sample market sessions. A single backtest, passing CI run, or successful deployment cannot establish it.

Review the [validation record](docs/VALIDATION.md), [research formulas and assumptions](docs/FORMULAS.md), and [GitHub CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml). Historical test counts are not presented as a permanent claim about the latest code; use the CI evidence for the relevant commit.

## Documentation

| Topic | Start here |
| --- | --- |
| How the system fits together | [Architecture](docs/ARCHITECTURE.md) |
| Entering holdings and confirmed transactions | [Local web](docs/LOCAL_WEB.md) · [Operations](docs/OPERATIONS.md) |
| Strategy formulas, costs, and risk assumptions | [Research methodology](docs/FORMULAS.md) |
| Read-only Alpaca paper account integration | [Alpaca Paper Trading](docs/ALPACA_PAPER.md) |
| Private hosting, schedules, and recovery | [Vercel private cloud](docs/VERCEL_CLOUD.md) · [Daily automation](docs/VERCEL_DAILY_AUTOMATION.md) |
| Computation and CI evidence | [Validation](docs/VALIDATION.md) · [GitHub Actions](https://github.com/wanghaibing07/investlab-monitor/actions) |
| Open-source references, feedback, contributions | [Upstream references](docs/UPSTREAM_REVIEW.md) · [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

## License and data

[MIT License](LICENSE). The public demo contains synthetic data only. Do not commit private accounts, secrets, backups, or restricted third-party data to the public repository.

InvestLab is a research and record-keeping tool, not an automated broker, personalized financial advisor, or replacement for brokerage statements.

*The interface and most CLI output are currently in Chinese; this README provides an English entry point and setup guidance.*
