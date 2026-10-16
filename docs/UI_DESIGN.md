# InvestLab — UI product standard

## Product goal
This is a private research and decision desk, not a trading terminal or a marketing landing page.
The first screen must answer: What is the verified conclusion? Why? What may I review manually? How fresh is the evidence?

## Visual alternatives considered
1. **Grafana-density**: dense charts and operational telemetry. Good for diagnostics, not the first-time investor decision.
2. **Linear-minimalism**: extremely sparse navigation and typography. Good for task systems, insufficient for explaining data quality.
3. **Editorial wealth desk (chosen)**: prominent Chinese conclusion; smaller evidence, position and historical panels below; calm forest / porcelain palette.

## Implemented design system
- Primary surfaces: porcelain #f2f4f0 / white; dark forest navigation #142824; primary action #224b3d.
- Semantic signal: verified, waiting, and error must have textual labels, not only colors.
- Main hierarchy: today's evidence-gated conclusion → next manual review → account value and evidence dates → charts and detailed reports.
- Typography: readable Simplified Chinese system fonts, tabular numeric amounts, no decorative English titles in priority content.
- Spacing and containers: no nested card stacks; keep a consistent panel radius and no fake whitespace or decorative graphs.
- Five working views: Overview, Portfolio, Strategy & Risk, Run Reports, Account Settings.
- Mobile: 390 × 844 navigation, modals, labels and charts must work without horizontal page overflow.
- Desktop: 1440 × 900, primary conclusion and next action stay discoverable without scrolling through charts first.

## Non-negotiable product behavior
- Never package real holdings, access tokens or private research into public HTML, JS, CSS, screenshots or test artifacts.
- Never infer actual returns from balance snapshots or display made-up live quotes.
- A completed technical check does not become a buy/sell instruction. Qualified research must match account version and market session.
- Manual run always requires an explicit confirmation. No automatic trade or scheduling is enabled by UI work.
- Vercel Authentication protects all deployments and all private APIs. Synthetic tests never bypass that production control.

## Browser acceptance
Run tests/visual/dashboard_smoke.cjs with Playwright. It serves the **actual** production UI asset files using local synthetic read-only API responses.
Capture desktop and mobile screenshots for three states: first run pending, account not yet initialized, and backend/storage failure.
Pass criteria: navigation and dialogs work, no JavaScript exceptions or viewport overflow, financial amounts match synthetic data, error/empty states are visible, and zero API writes are made.
CI screenshots are proof of rendering of synthetic fixtures, **not** proof of authenticated production success.

## Production acceptance still required
In an authorized Vercel login session, verify current deployment + full overview/portfolio/risk/report/settings, read-back of confirmed account, and one intentionally confirmed online market run. Keep private screenshots local and redact holdings before sharing. Do not declare end-to-end verified merely because a release is READY.
