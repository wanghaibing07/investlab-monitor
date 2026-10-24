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

## 2026-10-24 reference review and focused improvement

Three official, publicly inspectable financial products informed the update; these
are interface precedents, **not** InvestLab data providers:

- [Kubera portfolio tracker](https://www.kubera.com/portfolio-tracker):
  shows consolidated wealth and separates read-only tracking from transactions.
  InvestLab keeps confirmed total value near the decision, but never claims
  computed investment returns without cost and cash-flow records.
- [Ghostfolio](https://ghostfol.io/en):
  foregrounds private holdings, asset allocation and independent analysis.
  InvestLab keeps a small set of positions and actual-vs-strategy weights.
- [Sharesight](https://www.sharesight.com/us/):
  presents holdings and performance in context, with explicit portfolio records.
  InvestLab shows valuation dates and source notes before any history chart.

The existing editorial forest-and-porcelain direction stays. No new framework,
chart library or third-party animation runtime is justified by the current UI.

Selected interactions, all tied to server-backed state:

1. **Verified save feedback:** only after a server readback, a separate GET and
   the full dashboard refresh agree on the exact state version and CNY values.
   A checkmark and brief restrained particles are purely feedback, never proof.
2. **Evidence progress:** a four-step ring reflects confirmed values, verified
   storage, qualified technical report and matching currently actionable brief.
   It does not record an imaginary completed human task.
3. **Strategy disclosure:** native keyboard-operable details expand the exact
   condition records without adding navigation or changing investment state.

Drag-to-snap timelines, inertial selector wheels and radial page transitions
were not adopted: they add gesture conflict and motion cost without making the
four core facts easier to verify on a phone.

The history X-axis uses actual elapsed dates; equal spacing of irregular
snapshots would misrepresent elapsed time. Invalid amounts become unavailable,
never synthetic zeroes. The current P&L empty state explains the missing
cost/flow records instead of inventing a rate of return.

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
The UI contract checks also cover missing/malformed account amounts, stale
technical success versus actionable current briefs, scheduler status from API
and keyboard-accessible strategy disclosure.

## Production acceptance still required
In an authorized Vercel login session, verify current deployment + full overview/portfolio/risk/report/settings, read-back of confirmed account, and one intentionally confirmed online market run. Keep private screenshots local and redact holdings before sharing. Do not declare end-to-end verified merely because a release is READY.
