# InvestLab 私有云每日监控

**目标：每天自动生成 QQQ/TQQQ 行情与策略报告；失败后补跑一次，仍失败则邮件告警；始终不自动下单。**

## 执行时间

Vercel Hobby 每个定时任务最多每日一次，执行可能延后 59 分钟。本项目使用 UTC 时间（北京时间 +8）：

- 美股交易日之后的周二至周六 00:00 UTC（北京 08:00–08:59）运行首次计算
- 周二至周六 03:00 UTC（北京 11:00–11:59）检查当日结果；若缺失或失败，最多补跑一次，仍失败尝试 SMTP 邮件通知

程序用 New York 时区和美股交易日历检查真实已收盘交易日，节假日不强行生成新报告。QQQ/TQQQ 行情必须通过独立来源核验与审计，否则记录失败。

## 数据一致性

- **真实账户**只保存在 `state/` 下人工确认的不可覆盖快照；定时任务只读取它。
- 研究计算运行在临时 SQLite 中，合格结果另存 `computed/`，原始账户不会被覆盖。
- `schedule-claims/` 用 Blob 的 `allow_overwrite=false` 为每个市场交易日、账户版本、尝试次数创建唯一记录。不同任务无法重复取得相同尝试权。
- `runs/` 保存可审计运行报告，`scheduled-receipts/` 单独保留定时运行回执。研究建议仅在对应账户版本一致时展示。
- 当日首轮失败，检查任务尝试一次新的唯一重试；不会无限重试、反复改变账户。

## 上线所需设置

1. Vercel > investlab-cloud > Environment Variables，新增 `INVESTLAB_CRON_ENABLED=true`（Production），重新发布（仅配置后生效）。
2. 保留现有 `CRON_SECRET`、`BLOB_READ_WRITE_TOKEN`、Vercel Authentication；不要在公开仓库提交任何凭据。
3. 故障邮件需要在 Vercel **Production** 添加：`INVESTLAB_SMTP_HOST`（QQ 邮箱可用 smtp.qq.com）、`INVESTLAB_SMTP_PORT`（465）、`INVESTLAB_SMTP_USER`、`INVESTLAB_SMTP_PASSWORD`（邮箱 SMTP 授权码）、`INVESTLAB_ALERT_TO`（收件邮箱）。请只在 Vercel 私有设置页面填写授权码。
4. Vercel Authentication 可能拦截自动 Cron 请求，必须在 Cron Jobs 与日志里核对一次真实回执，不能只凭定时计划宣称成功；如果被拦截，应使用官方 Protection Bypass for Automation，并另行证明内部 Cron 调用路径正常，不可直接关闭身份保护。
5. 在 `/api/scheduler/status` 查看配置、最近运行日及是否有合格回执。界面“账户与设置”已有中文显示。
6. 使用一次安全故障测试验证收件箱收到告警，再持续观察至少 10 个符合条件的交易日，以证明实际运行率。

**限制：** SMTP 配置成功不等于实际邮件送达；本项目没有自动订单，保留单存储快照不是独立灾备；若 Vercel Cron 自身没有触发两个任务，仍需一个独立的外部漏跑监视器。

## 验收判定

- BUILD PASS：代码、单元测试、两端界面均通过
- DEPLOY PASS：最新提交 READY，生产域名指向新版本，Vercel Authentication 仍开启
- RUN PASS：真实账户没有变化，合格行情和报告的 `scheduled_session`、`computed_version` 与回执一致
- ALERT PASS：人为制造受控故障后 SMTP 接收成功，有可追踪证据
- LONG-TERM PASS：连续 10 个美股交易日无漏跑，失败自动补跑及告警符合预期

只有满足对应证据才能分别宣告上述 PASS。
