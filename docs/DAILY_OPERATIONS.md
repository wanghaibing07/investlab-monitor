# 长期运行：日报、验证与失败通知

这一运行链路面向**本机或私有 Linux 主机上的真实账户**。Vercel 公开演示不运行定时计算，也不接收 SMTP 凭据。投资建议始终是人工执行。

## 单次完整执行

确保已完成 `init` 和人工确认真实人民币估值，再运行：

```bash
investlab --home ~/.local/share/investlab daily-cycle
investlab --home ~/.local/share/investlab daily-status
```

`daily-cycle` 在一个互斥写入锁下依次执行：

1. 预检：必须是真实账户，且已有本人确认的估值
2. 可选：刷新宏观解释因子。失败被记录为 **DEGRADED**，不会冒充完全成功
3. 获取 QQQ/TQQQ 完整日线，独立行情检查并保存报告及备份；如不满足在线数据资格立即失败
4. 审计 SQLite、报告及研究证据
5. 独立重算策略结果，必须 PASS
6. 尝试评价已经到期的历史预测；不会把 0 条到期结果误报为策略优势

`--skip-macro` 可跳过宏观更新，`--skip-evaluate` 可跳过后续结果评价。跳过的环节标记 SKIPPED。为了公开可复现而生成的虚构账户不能执行 `daily-cycle`。

## 数据持久化与恢复

每轮记录保存在：
- `data/daily-status.json`：最近一次运行状态、各阶段结果、明确失败代码
- `data/daily-history/<cycle-id>.json`：每轮不可覆盖的历史状态
- `data/daily-alerts/<hash>.json`：待发失败/降级通知或已发送回执

每轮结果有 `SUCCEEDED`、`DEGRADED`、`FAILED` 三种状态；后两者返回非零退出码，使 systemd 显示失败。失败后不会创建假的成功报告。相同一天、相同阶段与同一问题的告警会被归并，降低重复告警。每日汇总没有账户金额、密码和 API 响应正文。

## systemd 安装

模板 `deploy/investlab.service` 和 `deploy/investlab.timer` 适用于私有 Linux 机器：周二至周六北京时间14:00执行一次（覆盖前一个美股完整收盘日），断电后补跑一次。

将模板复制到 `/etc/systemd/system/`，修改可执行文件与用户路径，并确保服务运行账户拥有私有数据目录。执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now investlab.timer
systemctl list-timers investlab.timer
systemctl status investlab.timer
```

模板只负责 **调度**。它不代表这台机器已经部署，更不代表已经跨多个交易日验收通过。

## 邮件告警（明确配置后才启用）

可选择在服务器私有环境中设置：
- `INVESTLAB_SMTP_HOST`、`INVESTLAB_SMTP_PORT`（默认465，SSL）
- `INVESTLAB_SMTP_USER`、`INVESTLAB_SMTP_PASSWORD`（邮箱服务的授权码，不是 GitHub 密钥）
- `INVESTLAB_ALERT_TO`（收件人）

执行 `investlab --home ... notify-pending` 发送未发送的失败/降级记录。邮件只包含状态、阶段、错误代码，没有账户金额、行情或密钥。若未配置 SMTP，事件保留为 PENDING，不假装已发送。发送失败继续保留待发，可重试；通信属于至少一次送达语义，极端中断后可能重复投递。

可以使用 QQ 邮箱 SMTP，但务必在私人服务器设置邮箱授权码，**不要**填入 GitHub、Vercel、聊天消息或版本库。实际收发需要在配置好的主机上单独验证。

## 边界

- 这是运行和报警机制，不是新的收益预测模型；前瞻评估只能在真实未来数据到期后积累样本。
- 本地长期监控依赖机器保持运行、网络稳定、行情供应商与 SMTP 可用；本项目不代替券商账户事实。
- 如需要外网访问真实账户，应单独设计身份验证、加密与权限控制；不能把 `--local-edit` 通过端口映射直接公开。
