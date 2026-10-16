# InvestLab — Production Reliability Acceptance

CI green, deployment READY and synthetic ZIP recovery are NOT proof of reliable long-term operation.

## Four independent gates

1. **Market data:** Non-demo online evidence from two independently verified providers for the latest completed US market session; journal audit and research verification PASS, current account/report version consistency. Fail on stale/session mismatch or insufficient sources.
2. **Account durability:** SSO, authenticated read and reread across refresh/new login; newest snapshot SHA256 and SQLite integrity; independent encrypted backup restored into an empty environment; amounts, date and history verified. In-store snapshots alone do not count as independent disaster recovery.
3. **Daily execution:** Transactional writer lock and idempotent run key by account/session/strategy; production scheduler; durable successful receipt by agreed cutoff on 10 successive eligible US trading sessions. Handle New York DST, weekends and exchange holidays.
4. **Failures/recovery:** Independent watchdog checking missing runs/failed receipts/staleness; tested alert delivery, deduplication, bounded retries for transient failures, independent off-site restore, written recovery procedure, agreed RTO and RPO.

## Current behavior and mandatory stop conditions

- Current storage: private Vercel Blob, versioned ZIP snapshots. It has no atomic compare-and-swap for concurrent writers. Do NOT enable scheduled writes concurrently with manual edits. Add verified transactional locking first, preferably Postgres with a unique account/market session/strategy key, or an equivalently tested solution.
- Read-only GET /api/recovery checks up to two recent private snapshots in isolated directories. It performs SHA256 validation, SQLite quick_check, and confirmed non-demo account validation. It never changes active account state, does not expose balances, and refuses to treat older valid versions as an automatic substitute for a corrupted latest version.
- Recovery probe reports independent_backup_verified=false and automatic_recovery_verified=false even when two snapshots are restorable from the SAME store.
- GET /api/cron/daily requires CRON_SECRET authorization AND the exact opt-in environment variable INVESTLAB_CRON_ENABLED=true. Keep the opt-in variable unset and keep crons absent from deploy/cloud/vercel.json until all prerequisites pass. Do not weaken Vercel SSO to make cron work.
- Vercel Cron operates on UTC and has plan-dependent precision. Receiving a scheduled HTTP request is not sufficient evidence of successful data and report persistence.
- A daily run must produce a durable receipt plus quote source, session date, audit, code/protocol identity, state generation and qualified run status. Missing or failed evidence is never presented as success.
- Independently deliver and test a redacted alert for failed/missing runs. Retry only bounded idempotent operations. Never retry account mutation blindly; verify the newest persisted version first.
- Roll back code separately from data. Preserve latest data before any data restore. Require manually chosen version and independent checksum + amount/date/history verification before promoting restored data.

## Acceptance log

For each production session record session date, two-source evidence, state generation, run start/end, qualified result, report readback, alert delivery result, and any incident recovery. Every row is explicitly PROVEN, UNVERIFIED or NOT IMPLEMENTED. Do not use synthetic fixtures as proof of real market data or production data recovery.

Never include private holdings, SSO cookies, auth headers, secret values or vendor-proprietary raw datasets in commits or screenshots.
