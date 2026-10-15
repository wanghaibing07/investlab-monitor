[简体中文](README.md) · [English](README.en.md)

# InvestLab

**Track your QQQ and TQQQ holdings, follow prices, and compare investment strategies.**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

InvestLab uses market prices and your holdings to suggest allocation changes and saves the calculations for review. View the results in a terminal or web dashboard. Your data stays on your computer, and you decide which trades to make.

[Quick start](#quick-start) · [Features](#features) · [Use your own account](#use-your-own-account) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md#english)

## Quick start

Requires **Python 3.11 or later**. The core application uses the Python standard library. Try it with the included simulated account and sample prices; market calculations run offline.

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

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) to see your holdings, allocation suggestions, strategy return charts, and history. Demo data is labeled as simulated. Press `Ctrl+C` to stop the server. Git ignores `runtime/`.

On Windows PowerShell, replace the activation command with `.\.venv\Scripts\Activate.ps1`; the remaining commands are unchanged. You can also invoke `.\.venv\Scripts\investlab.exe` directly. **The CLI and dashboard are currently primarily in Chinese.** This README provides the English project and usage guide.

In another terminal with the same virtual environment activated, verify the demo:

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

`verify` recalculates 20 strategy/cost combinations with an independent algorithm and writes the full result to `runtime/demo/data/verification.json`.

## Features

| Feature | What you can do |
| --- | --- |
| Follow prices | Update QQQ/TQQQ closing prices and see data dates, sources, and errors |
| Manage holdings | Record valuations and confirmed trades separately, keep correction history, and avoid duplicate entries |
| Review allocation suggestions | See the next target weights based on trends, volatility, and confirmed holdings |
| Compare strategies | Explore historical results for ten strategy families, including fixed 60/40, risk parity, volatility targeting, mean reversion, and momentum |
| Check calculations | Independently verify return curves, trading costs, risk allocation, and the timing of historical signals |
| Back up and restore | Save accounts, reports, and calculation inputs; check file and database integrity before restoration |
| Schedule updates | Run scheduled updates on your own host using container and systemd configurations |

## Default rules

The long-term target is **60% QQQ + 40% TQQQ**. Suggestions use a 200-day trend and 20-day volatility measure. Each suggested TQQQ increase is limited to 5 percentage points of total assets, starting from the last confirmed holdings. Account records update when you import a new valuation or confirmed transactions.

## Use your own account

Keep real runtime data outside the source repository. Create a valuation file from your own confirmed records using [valuation.json](examples/valuation.json) as the format reference. All supplied account examples are fictional.

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
```

Fill in your valuation file before running these commands. Valuations record asset values; confirmed transactions provide shares, costs, and trades. Import transactions with `ledger-import`; see [events.json](examples/events.json).

The application checks prices against the latest completed US equity session. A price conflict prompts a data review before new suggestions are generated. Yahoo's two endpoints count as one source; independent checks are reported separately. Macro data helps explain risk, while ETF monitoring can run on its own.

An existing complete v5.5 project can be migrated to a new directory without changing its original account database:

```bash
investlab --home /private/investlab migrate /path/to/qqq-tqqq-clean
investlab --home /private/investlab audit
```

Migration checks data consistency table by table and preserves historical reports, account records, and research inputs.

## Daily commands

Use the same `--home` directory throughout. Place `--json` before the subcommand for machine-readable output.

| Command | Purpose |
| --- | --- |
| `run --online --independent-check --require-current` | Retrieve prices, calculate, persist, read back, and verify a local backup; return a nonzero exit code when data checks fail |
| `run` / `summary` | Recalculate from cached data / print a short daily summary in Chinese |
| `refresh-macro` / `research` / `evaluate` | Update four macro explanatory series / generate strategy research / score forecasts whose outcome periods have ended |
| `valuation-import FILE` / `ledger-import FILE` | Import confirmed valuations / confirmed transactions |
| `account NAME` | Replay cash, shares, known costs, and realized P&L by account and currency |
| `verify` / `audit` | Independently recalculate results / check database integrity, relationships, and evidence hashes |
| `freeze` | Record the code version and data date for later comparisons |
| `backup --output FILE.zip` | Save a consistent database snapshot, research evidence, and file hashes |
| `restore FILE.zip --to EMPTY_DIRECTORY` | Validate and restore into an empty directory |
| `doctor` / `serve` | Inspect the runtime / start the local read-only dashboard |
| `export --output FILE.json` | Export the current report; the export contains private data |

## Backups and deployment

```bash
investlab --home /private/investlab backup --output /private/backup.zip
investlab --home /private/investlab restore /private/backup.zip --to /private/restore-check
investlab --home /private/restore-check audit
investlab --home /private/restore-check doctor
```

Backups use SQLite's native backup API and include research evidence and a file manifest. Restoration validates paths, hashes, settings, and the database in a staging directory before an atomic switch to an empty target. Keep at least one backup on another machine.

Use the CLI on a persistent host for scheduled runs. [systemd templates](deploy/investlab.timer) and [container configuration](deploy/compose.yaml) are included. Select one scheduler to avoid duplicate runs. The container template runs the CLI with a persistent volume; it does not expose a public dashboard. The dashboard listens on `127.0.0.1`; use SSH local port forwarding for remote access.

Private backups can include a `SOURCE.json` file identifying the code version used. Restore that version alongside the saved data to reproduce earlier results.

## Validation and research notes

The v6.0.1 suite has **240 passing tests and 1 skipped optional issuer-NAV test**, whose input data is not redistributed. GitHub CI covers Python 3.11, 3.12, and 3.13, plus execution, independent verification, and auditing across read-only containers sharing a persistent volume.

On identical frozen prices, all summary fields agree between the original and refactored engines for ten strategies at two cost levels. Independent replay of 20 equity paths has a maximum relative difference of approximately `3.3e-14`. The [validation record](docs/VALIDATION.md) lists the checks and their results.

Research uses USD ETF adjusted market closes. A signal at close t executes at close t+1; a new position starts earning returns from t+2. Costs are compared at 15 / 50 basis points per side. Taxes and cash interest are not modeled. Actual CNY account returns require complete share counts, cash flows, and same-date FX rates.

Historical backtests help compare strategies. Actual investment results also depend on future prices, trading costs, and execution. The probability model currently performs below the historical-frequency benchmark and is retained as a research comparison. See [formulas and research assumptions](docs/FORMULAS.md) for the methods and evaluation approach.

## Documentation

| Topic | Guide |
| --- | --- |
| Chinese project and usage guide | [简体中文 README](README.md) |
| Design and module boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Formulas, execution timing, and model limitations | [Research methodology](docs/FORMULAS.md) |
| Daily operations, migration, containers, and recovery | [Operations](docs/OPERATIONS.md) |
| Checks and operating results | [Validation](docs/VALIDATION.md) |
| Upstream source reading and design choices | [Upstream review](docs/UPSTREAM_REVIEW.md) |
| Bug reports, code changes, and documentation | [Contributing](CONTRIBUTING.md#english) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

Detailed technical documents are currently primarily in Chinese. This English entry covers installation, account setup, commands, migration, recovery, and verification.

## Contributing

Bug reports, documentation improvements, and fixes are welcome. Read the [contribution guide](CONTRIBUTING.md#english), validate changes in a separate demo directory, and remove account data, caches, logs, and credentials from submissions. For model changes, include the data dates, cost assumptions, and before/after results.

## Attribution and license

InvestLab builds on the v5.5 calculation engine. Interface and validation designs draw on source reviews of OpenBB, Qlib, LEAN, Ghostfolio, Wealthfolio, skfolio, and QQQ/TQQQ Decision Cockpit. See the [review record](docs/UPSTREAM_REVIEW.md) for the files, versions, and design choices.

The code is licensed under [MIT](LICENSE). Third-party market-data access and redistribution terms are separate from the code license. Source code is published on GitHub; personal accounts and runtime data stay in separate private directories.
