[简体中文](README.md) · [English](README.en.md)

# InvestLab

**Long-term QQQ / TQQQ portfolio monitoring and quantitative research, with traceable accounts, decisions, calculations, and evidence.**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

InvestLab keeps portfolio data on your machine. Import confirmed account records, retrieve completed daily market bars, generate staged allocation suggestions, compare strategies, and retain evidence for replay. It includes a CLI and a read-only web dashboard. The core runtime requires no third-party Python packages, model API, or cloud account.

The default long-term target is **60% QQQ + 40% TQQQ**. Each suggested TQQQ increase starts from the last confirmed holdings and is limited to 5 percentage points of total assets, subject to trend and volatility conditions. A person executes any trades.

[Quick start](#quick-start) · [Features](#features) · [Use your own account](#use-your-own-account) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md#english)

## Quick start

Requires **Python 3.11 or later**. This example uses a separate directory with fixed, fictional holdings and prices. It does not fetch market data.

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

Open **http://127.0.0.1:8765** for the daily review, allocation gap, strategy equity comparisons, account journal, and run history. Demo data is labeled as fictional. Press `Ctrl+C` to stop the server. Git ignores `runtime/`.

On Windows PowerShell, replace the activation command with `.\.venv\Scripts\Activate.ps1`; the remaining commands are unchanged. You can also invoke `.\.venv\Scripts\investlab.exe` directly. **The CLI and dashboard are currently primarily in Chinese.** This README provides the English project and usage guide.

In another terminal with the same virtual environment activated, verify the demo:

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

`verify` replays 20 strategy/cost combinations and writes the full result to `runtime/demo/data/verification.json`.

## Features

| Capability | What it provides |
| --- | --- |
| Completed daily market bars | Raw and adjusted QQQ/TQQQ closes, original provider responses and hashes, checks for unfinished sessions, stale data, and source conflicts |
| Confirmed account records | Separate journals and valuations; decimal amounts, stable-ID deduplication, atomic batch rollback, and append-only corrections |
| Staged allocation reviews | A 200-day trend buffer and 20-day volatility conditions; separate targets, suggestions, and confirmed holdings so repeated reports never become trades |
| Strategy and scenario research | Ten strategy families including fixed 60/40, QQQ benchmark, risk parity, volatility targeting, mean reversion, and momentum; macro sensitivity, event probabilities, and path simulations |
| Independent numerical checks | Equity replay with a different fee solver, an analytical two-asset risk-parity comparison, and tests for future data changing past signals |
| Recoverable evidence | SQLite records, source and input snapshots, a single-writer lock, visible failures, consistent backups, and validated restoration |
| Local interface and deployment | A read-only dashboard, installable Python package, container and systemd templates, and multi-version GitHub CI |

## Use your own account

Keep real runtime data outside the source repository. Create a valuation file from your own confirmed records using [valuation.json](examples/valuation.json) as the format reference. All supplied account examples are fictional.

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
```

Fill in your valuation file before running these commands. Aggregate valuations do not imply known shares, cost basis, or trades. Import confirmed transactions separately with `ledger-import`; see [events.json](examples/events.json).

Prices must cover the latest completed US equity session. Conflicting sources block a new allocation review. Two Yahoo endpoints count as one provider; an unavailable independent check is reported separately. Macro factors explain risk, and a macro retrieval failure does not block ETF monitoring.

An existing complete v5.5 project can be migrated to a new directory without changing its original account database:

```bash
investlab --home /private/investlab migrate /path/to/qqq-tqqq-clean
investlab --home /private/investlab audit
```

Migration compares historical content hashes table by table and preserves reports, account baselines, and research evidence.

## Daily commands

Use the same `--home` directory throughout. Place `--json` before the subcommand for machine-readable output.

| Command | Purpose |
| --- | --- |
| `run --online --independent-check --require-current` | Retrieve prices, calculate, persist, read back, and verify a local backup; exit nonzero when data is unqualified |
| `run` / `summary` | Recalculate from cached data / print a short daily summary in Chinese |
| `refresh-macro` / `research` / `evaluate` | Update four macro explanatory series / generate strategy research / evaluate matured observations |
| `valuation-import FILE` / `ledger-import FILE` | Import confirmed valuations / confirmed transactions |
| `account NAME` | Replay cash, shares, known costs, and realized P&L by account and currency |
| `verify` / `audit` | Independently recalculate results / check database integrity, relationships, and evidence hashes |
| `freeze` | Fix source identity and the data cutoff before collecting forward evidence for that version |
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

GitHub is the working source repository. Private state capsules contain runtime data and a `SOURCE.json` reference to an exact commit. Preserve that commit when resuming a capsule, rather than silently replacing it with the current `main` branch.

## Verification and research scope

The v6.0.1 suite has **240 passing tests and 1 skipped optional issuer-NAV test**, whose input data is not redistributed. GitHub CI covers Python 3.11, 3.12, and 3.13, plus execution, independent verification, and auditing across read-only containers sharing a persistent volume.

On identical frozen prices, all summary fields agree between the original and refactored engines for ten strategies at two cost levels. Independent replay of 20 equity paths has a maximum relative difference of approximately `3.3e-14`. The [validation record](docs/VALIDATION.md) lists methods, evidence, and open observations.

Research uses USD ETF adjusted market closes. A signal at close t executes at close t+1; a new position starts earning returns from t+2. Costs are compared at 15 / 50 basis points per side. Taxes and cash interest are not modeled. Actual CNY account returns require complete share counts, cash flows, and same-date FX rates.

The current event-probability model has not beaten the historical-frequency benchmark. Long-term reliability and strategy performance still require future observations. Passing tests, matching calculations, and a short successful operating period establish different kinds of evidence; they do not establish guaranteed investment returns. See [formulas and research assumptions](docs/FORMULAS.md).

## Documentation

| Topic | Guide |
| --- | --- |
| Chinese project and usage guide | [简体中文 README](README.md) |
| Design and module boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Formulas, execution timing, and model limitations | [Research methodology](docs/FORMULAS.md) |
| Daily operations, migration, containers, and recovery | [Operations](docs/OPERATIONS.md) |
| Executed checks and known gaps | [Validation](docs/VALIDATION.md) |
| Upstream source reading and design choices | [Upstream review](docs/UPSTREAM_REVIEW.md) |
| Bug reports, code changes, and documentation | [Contributing](CONTRIBUTING.md#english) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

Detailed technical documents are currently primarily in Chinese. This English entry covers installation, account setup, commands, migration, recovery, and verification.

## Contributing

Reproducible bug reports, documentation improvements, and evidence-backed fixes are welcome. Read the [contribution guide](CONTRIBUTING.md#english), validate changes in a separate demo directory, and remove account data, caches, logs, and credentials from submissions. Model changes should include the information cutoff, cost assumptions, and before/after results.

## Attribution and license

InvestLab incrementally refactors an existing v5.5 numerical engine. Source reviews covered OpenBB, Qlib, LEAN, Ghostfolio, Wealthfolio, skfolio, and QQQ/TQQQ Decision Cockpit. Their interfaces and verification approaches informed design choices; their implementations are not copied or bundled. See the [review record](docs/UPSTREAM_REVIEW.md) for paths, pinned commits, and decisions.

The code is licensed under [MIT](LICENSE). Third-party market-data access and redistribution terms are separate from the code license. Personal records and runtime evidence stay in private directories; a state capsule references its exact source commit through `SOURCE.json`.
