# Public read-only demo

This deployment provides a **synthetic-data demonstration only**. It does not publish local portfolios, transaction journals, real market snapshots, or backups.

1. Connect a Render account and select this repository.
2. Create a service from the `render.yaml` Blueprint.
3. Confirm the external host is set through Render's `RENDER_EXTERNAL_HOSTNAME`.
4. Wait for the startup command to finish seeding, calculating and verifying the demo fixture.
5. Check `/health/live` and `/health/ready`. In the UI, confirm that **虚构数据演示** is displayed. Check tabs, chart, history and refresh.

The public flag `--public-demo` refuses non-demo accounts. The regular `investlab serve` command remains loopback-only.

On free-tier hosts the process and ephemeral data may reset after idle. Startup regenerates the same demonstration. For personal holdings use the original private local workflow and SSH port forwarding instead.

No broker connection, order placement or automatic trading is provided.
