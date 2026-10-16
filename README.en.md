[简体中文](README.md) · [English](README.en.md)

# InvestLab

**Understand your QQQ / TQQQ holdings, market trends, and portfolio risks—make every investment decision with a clear rationale.**

InvestLab is an open-source ETF portfolio monitor and strategy research tool. It brings **holdings, market data, strategies, risk analysis, and historical records** into one workspace, helping investors track allocations, evaluate opportunities, and review decisions over time.

**[Live demo](https://investlab-monitor.vercel.app/)** · [Quick start](#quick-start) · [Features](#features) · [简体中文](README.md)

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Features

| Feature | What you get |
| --- | --- |
| **Portfolio overview** | Track confirmed QQQ, TQQQ, QLD, and cash values, allocation weights, and valuation history |
| **Daily market monitoring** | Follow completed US trading sessions with price sources, dates, and data-quality checks |
| **Allocation insights** | Review step-by-step portfolio references based on long-term trends, volatility, and current holdings |
| **Strategy & risk research** | Compare historical returns, drawdowns, volatility, and transaction-cost assumptions |
| **Scheduled monitoring** | Configure daily research, saved reports, a retry window, and email notifications |
| **Data management** | Keep valuation and transaction history, versioned records, and verified backups |

**Everyday workflow: review your portfolio → check market conditions → examine the rationale → make your investment decision.**

## Try the demo

**[Explore the public InvestLab demo](https://investlab-monitor.vercel.app/)**

Explore the Today's Decision, Strategy Research, and Activity & History views directly in your browser. The public demo uses **synthetic holdings and sample prices** to present the workspace and research flow.

For your own portfolio, [run locally](#quick-start) or [set up a private cloud instance](docs/VERCEL_CLOUD.md).

## Quick start

Requires **Python 3.11+**. The commands below launch a local dashboard with the bundled sample portfolio.

```bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .

investlab --home ./runtime/demo init --demo
investlab --home ./runtime/demo run
investlab --home ./runtime/demo serve
```

Open **http://127.0.0.1:8765**. On Windows PowerShell, activate the virtual environment with `.\\.venv\\Scripts\\Activate.ps1`.

To verify a local research run:

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

To manage your own holdings, follow the [local web guide](docs/LOCAL_WEB.md) and [operations manual](docs/OPERATIONS.md). The user interface and most CLI output are available in Chinese.

## Built for QQQ / TQQQ research

The built-in long-term reference allocation is **60% QQQ + 40% TQQQ**. The monitor combines:

- **Trend**: a 200-day trend to assess market direction.
- **Volatility**: recent volatility and risk measures to evaluate portfolio exposure.
- **Gradual allocation**: an actionable review framework that breaks down long-term targets into incremental steps.
- **Strategy comparison**: historical research using consistent price and fee assumptions.

**Long-term targets, suggested next steps, and actual holdings appear separately**, making changes easier to review. TQQQ targets 3× the Nasdaq-100's daily performance; portfolio analysis considers the corresponding volatility and drawdown exposure.

## Automation and data ownership

InvestLab supports two deployment paths:

| Deployment | Best suited for |
| --- | --- |
| **Local** | Manage records, evaluate strategies, and schedule tasks on your computer or Linux server |
| **Private Vercel cloud** | Access an authenticated dashboard with versioned portfolio history, US-market-session scheduling, and a delayed retry |

Scheduled calculations keep research outputs separate from user-confirmed portfolio records. Reports capture session dates, data checks, and run status. Operators can configure email alerts. **Trade execution remains the investor's decision.**

Deployment guides: [Private cloud](docs/VERCEL_CLOUD.md) · [Daily automation](docs/VERCEL_DAILY_AUTOMATION.md) · [Operations and backups](docs/DAILY_OPERATIONS.md).

## Reproducible research

Data checks, account audits, independent strategy calculations, and historical outcome reviews support transparent research. Each run leaves traceable records for investigating changes and reproducing results.

- [Validation](docs/VALIDATION.md): automated tests, audits, and independent research checks
- [Research methodology](docs/FORMULAS.md): formulas, trading costs, backtesting, and risk assumptions
- [GitHub Actions](https://github.com/wanghaibing07/investlab-monitor/actions): recent build and test results

## Documentation and contributing

| Topic | Read |
| --- | --- |
| System architecture | [Architecture](docs/ARCHITECTURE.md) |
| Portfolio inputs and regular usage | [Local web](docs/LOCAL_WEB.md) · [Operations](docs/OPERATIONS.md) |
| Private deployment and scheduled runs | [Vercel cloud](docs/VERCEL_CLOUD.md) · [Daily monitoring](docs/VERCEL_DAILY_AUTOMATION.md) |
| Alpaca paper account data | [Alpaca Paper Trading](docs/ALPACA_PAPER.md) |
| References, contributions, and feedback | [Upstream references](docs/UPSTREAM_REVIEW.md) · [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

**License:** [MIT](LICENSE). Strategy outputs support investment research, with portfolio decisions made by the investor.
