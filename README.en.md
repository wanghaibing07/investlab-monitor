[简体中文](README.md) · [English](README.en.md)

# InvestLab

**See your QQQ / TQQQ holdings, follow the market, and compare investment strategies in one place.**

InvestLab is an open-source investment monitor you can run on your own computer. It helps you answer four practical questions: **What do I hold? What changed today? Why might I adjust my allocation? How did different strategies perform in the past?** You get a clear record of the numbers and reasons; you make the final trading decisions.

**[Live demo (synthetic data)](https://investlab-monitor.vercel.app/)**: No installation required. This is a read-only demonstration snapshot, not live market data or a hosted personal account. Run locally for full functionality.

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Try it](#quick-start) · [What you can do](#what-you-can-do) · [Your own account](#use-your-own-account) · [How results are checked](#how-results-are-checked) · [Docs](#documentation)

## What you can do

The local web dashboard has three main views:

| View | What you see |
| --- | --- |
| **Today's decision** | Last confirmed holdings, target weights, suggested next step, reasons, and market-data freshness |
| **Strategy research** | Historical growth curves, drawdowns, volatility, and trading costs for different rules on the same price history |
| **Activity and history** | Confirmed account transactions, saved calculations, and run history |

A simple workflow: **check your holdings and price date → review the suggested action and why → compare risks → decide for yourself**.

The project also records transactions and reports, supports scheduled runs, backs up your data, and checks its calculations independently. Personal account files can stay in a private directory instead of being uploaded to GitHub.

## Quick start

Requires **Python 3.11+**. The included **fictional account and sample prices** let you explore the dashboard without sharing real holdings. The core demo works offline.

~~~bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .

investlab --home ./runtime/demo init --demo
investlab --home ./runtime/demo run
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo serve
~~~

Open **http://127.0.0.1:8765** to view today's decision, strategy comparisons, and history. Demo results are labeled as simulated. Press `Ctrl+C` to stop the server.

In Windows PowerShell, replace `source .venv/bin/activate` with `.\.venv\Scripts\Activate.ps1`. The other commands stay the same. The CLI and dashboard currently display mostly Chinese text.

To check the demo data, activate the same environment in another terminal and run:

~~~bash
investlab --home ./runtime/demo audit
~~~

## The built-in portfolio rules

The current long-term target is **60% QQQ + 40% TQQQ**. Both ETFs expose you to Nasdaq-100-related risk. **TQQQ targets three times the index's daily return**, so its long-term risk and volatility can be much higher.

The monitor uses a **200-day price trend and 20-day volatility**, alongside your last confirmed holdings, to suggest gradual allocation changes. Each suggested TQQQ increase is capped at **5 percentage points of total assets**. These are built-in rules for analysis, not a one-size-fits-all allocation.

**A target is not a completed trade.** Suggestions do not change your transaction records, and the application does not send orders to a broker. Account records change only when you import confirmed information.

## Alpaca paper account and risk scenarios

- **Interactive demo**: Adjust a hypothetical daily index change and TQQQ allocation in Strategy Research. No orders are possible.
- **Local paper integration**: `alpaca-paper-snapshot` reads only Alpaca Paper Trading balances and positions into a separate private USD report. Your local CNY portfolio is untouched.
- **Research method**: The evidence labels, exposure calculations and scenario caveats draw on Public Equity Investing risk workflows. ChatGPT plugin permissions are not shared with the site.
- Details: [Alpaca paper account integration](docs/ALPACA_PAPER.md).

## Edit confirmed valuations in the private local web app

Opt in to local-only account editing, with explicit confirmation and no order submission:

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab serve --local-edit
```

Visit `http://127.0.0.1:8765`, enter the confirmed CNY valuations for QQQ, TQQQ, QLD and cash, save, then explicitly request a cached or online verified recalculation. Valuations are not treated as executed trades. Run `init` only once; the default `serve` and the public Vercel site remain read-only.

[Local web workflow and security](docs/LOCAL_WEB.md).

## Use your own account

Fill in your actual asset values using the [valuation example](examples/valuation.json), then run:

~~~bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
~~~

- **Valuations** record current asset values; **transactions** record confirmed trades, share counts, costs, and cash movements. Import trades with `ledger-import` using the [transaction example](examples/events.json).
- `run --online` fetches market data, creates the daily assessment, and saves the result. `summary` prints a short summary in Chinese.
- Keep your real account data in a separate private directory. Online price updates contact market-data providers; your account files do not need to be committed to the public repository.

The report shows price dates, sources, and data checks. Multiple endpoints belonging to the same provider are not treated as independent data sources.

## How results are checked

InvestLab checks **whether the software calculates correctly** separately from **whether a strategy will perform well in the future**.

| Question | How InvestLab addresses it |
| --- | --- |
| Are the calculations consistent? | Independently recomputes 10 strategy families at two fee levels: 20 comparisons |
| Do backtests use future information? | Checks when a signal becomes available, when trades execute, and when returns begin |
| Is a backtest my actual return? | Strategy comparisons use historical USD ETF prices; personal results come from confirmed account records |
| Can I recover my data? | Supports backups, restoration, and database/file integrity checks |
| Can it run on a schedule? | Includes [systemd timer](deploy/investlab.timer) and [container setup](deploy/compose.yaml) |

The [validation record](docs/VALIDATION.md), dated **October 15, 2026**, reports **240 passing tests and one skipped optional external-data test**. GitHub CI has exercised Python 3.11–3.13 and the container workflow; 20 independent equity-curve recalculations agreed.

Historical results help compare strategies, but do not predict future returns. The backtests include two simulated trading-fee levels, but exclude taxes and cash interest. Actual account results also depend on transactions, cash flows, and FX rates. See the [research methodology](docs/FORMULAS.md).

## Isolated Vercel private cloud

The separate `investlab-cloud` project uses Vercel Authentication and a private Blob store for immutable versioned account/operation snapshots; it does **not** expose personal data through the public synthetic demo. Cron scheduling remains disabled until real-account confirmation and private runtime verification are completed.

[Private cloud architecture, bootstrap and verification](docs/VERCEL_CLOUD.md).

## Private daily monitoring and alerts

`investlab daily-cycle` performs qualified online data collection, durable audits, independent research verification, and matured outcome evaluation. `investlab daily-status` reports each stage. Failures are persisted as private pending alerts; sending via `notify-pending` requires explicit private SMTP setup. The public Vercel demo never accesses this data.

[Daily operations, scheduling and notifications](docs/DAILY_OPERATIONS.md).

## Everyday commands

Use the same `--home` directory to keep your records together.

| Command | Purpose |
| --- | --- |
| `run` / `summary` | Calculate and save / show a short daily assessment |
| `valuation-import FILE` / `ledger-import FILE` | Import confirmed valuations / transactions |
| `account NAME` | Review account cash, holdings, and costs |
| `research` / `verify` | Research historical strategies / independently recalculate results |
| `audit` / `doctor` | Check stored data / inspect the runtime environment |
| `backup --output FILE.zip` | Back up accounts, reports, and research records |
| `restore FILE.zip --to EMPTY_DIRECTORY` | Restore into a new empty directory |
| `serve` | Open the local read-only dashboard |

For scheduled updates, container deployment, migration, and recovery, see the [operations guide (Chinese)](docs/OPERATIONS.md).

## Documentation

| What you want to learn | Link |
| --- | --- |
| 中文介绍与使用方式 | [简体中文 README](README.md) |
| How the components fit together | [Architecture (Chinese)](docs/ARCHITECTURE.md) |
| Rules, formulas, fees, and backtest assumptions | [Research methodology (Chinese)](docs/FORMULAS.md) |
| Setup, scheduling, backups, and migration | [Operations (Chinese)](docs/OPERATIONS.md) |
| Detailed tests and independent checks | [Validation record (Chinese)](docs/VALIDATION.md) |
| Open-source references and design choices | [Upstream review (Chinese)](docs/UPSTREAM_REVIEW.md) |
| Report an issue or contribute | [Contribution guide](CONTRIBUTING.md#english) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

## License

The source code is published under the [MIT License](LICENSE). Keep account data, price caches, backups, and credentials in private directories. Third-party market-data usage is governed by each provider's terms.
