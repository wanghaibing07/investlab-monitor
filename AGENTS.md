# InvestLab agent guidance

- Keep the existing FastAPI + native HTML/CSS/JavaScript stack. Do not migrate to React, Tailwind or shadcn/ui solely to restyle the dashboard.
- Before front-end edits, read docs/UI_DESIGN.md, inspect actual pages and define a single business outcome. Prefer real visual references to generic prompts such as "make it premium".
- Implement one coherent design direction; never add gratuitous cards, gradients, mock market performance or placeholder trades.
- Run static tests, then tests/visual/dashboard_smoke.cjs in Playwright on desktop 1440x900 and mobile 390x844. Review screenshots, page errors, horizontal overflow, navigation, dialogs and failure/empty states.
- CI uses synthetic account values only. Never put real holdings, Vercel cookies, cloud credentials, account snapshots or production API responses in commits/artifacts.
- All production account reads/writes require authorized Vercel SSO. Never disable deployment protection, auto trading or cron safeguards to make a UI test pass.
- Clearly distinguish code tests, synthetic-browser tests and authenticated production acceptance. A successful build/READY deployment is not complete UI verification.
- Work in a small branch/PR, collect CI evidence, then merge/deploy only after passing gates. Avoid modifying active TQQQ shadow-risk experiments.
