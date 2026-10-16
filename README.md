[简体中文](README.md) · [English](README.en.md)

# InvestLab

**每天看清 QQQ / TQQQ 的持仓、行情和风险，再决定是否调整。**

InvestLab 是一款**开源、可在自己电脑上运行的 ETF 投资监控与策略研究工具**。它把账户估值、市场行情、策略对比和历史报告放在一起，帮你回答：**现在持有什么？发生了什么变化？下一步为什么值得关注？**

它提供数据和研究依据，**不会自动买卖股票或 ETF**。

**[在线体验（无需登录，全部是虚构数据）](https://investlab-monitor.vercel.app/)** · **[本地快速开始](#本地快速开始)** · **[计算与验证](#结果为什么值得核对)** · **[English](README.en.md)**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 它能帮你做什么

| 你的问题 | InvestLab 提供什么 |
| --- | --- |
| **我的钱现在在哪里？** | 查看 QQQ、TQQQ、QLD 和现金的已确认估值、比例与历史变化。 |
| **今天行情有什么变化？** | 跟踪美股收盘数据，检查日期和来源；数据不合格时明确标记。 |
| **现在要调整仓位吗？** | 对照策略规则，给出本步参考比例、理由和风险条件，供人工决定。 |
| **哪个策略更合适？** | 在相同历史行情和交易费用下比较策略的收益、回撤与波动。 |
| **以后能追查与恢复吗？** | 保存运行记录、研究依据与账户备份，支持校验和隔离恢复。 |

你可以按照这个顺序使用：**看账户 → 核对行情是否最新 → 理解策略与风险 → 自己决定是否交易**。

## 先试试看

**[打开公开演示](https://investlab-monitor.vercel.app/)**，无需安装、无需账号。可以直接浏览「今日判断」「策略研究」「流水与运行」。

演示中的账户、行情和计算结果**全部是虚构的**；它展示产品交互，不提供实时市场报价或真实投资建议。你的真实账户不会出现在公开演示站点。

想使用自己的数据，有两种方式：

- **在自己电脑运行**：适合体验完整计算、独立验证、导入账户及保存历史记录。
- **自行部署私有云端**：使用受登录保护的 Vercel 运行环境，支持私有账户、手动计算和可配置的定时监控。私人工作台不是公开演示，也不是本仓库提供的公共账号服务。

## 本地快速开始

需要 **Python 3.11+**。下面使用虚构账户和演示行情，不需要任何 API 密钥。

~~~bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .

investlab --home ./runtime/demo init --demo
investlab --home ./runtime/demo run
investlab --home ./runtime/demo serve
~~~

打开 **http://127.0.0.1:8765** 即可查看本地看板；按 `Ctrl+C` 停止服务。Windows PowerShell 将激活命令改为 `.\.venv\Scripts\Activate.ps1`。

想检查演示结果是否自洽，可在另一个终端运行：

~~~bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
~~~

要录入自己的持仓估值、导入真实成交流水或联网更新行情，参阅 [本地网页操作](docs/LOCAL_WEB.md) 和 [使用手册](docs/OPERATIONS.md)。**估值变化不等于实际成交**，只有本人确认的交易才会记录为交易。

## 项目的核心设计

### 1. 关注 QQQ / TQQQ，而不是做通用证券交易平台

默认研究组合的长期参考比例是 **60% QQQ + 40% TQQQ**。系统结合 200 日趋势与近期波动，给出分步复核建议；单步增加 TQQQ 的参考幅度设有上限。

这只是项目内置的研究规则，不代表每天都要买入，也不适用于每个人。**TQQQ 追求纳斯达克 100 指数每日 3 倍表现，连续多日的收益并不等于指数累计涨幅乘以三。**

### 2. 不只展示结论，也展示依据

- 行情结果包含**交易日、来源和数据校验状态**。同一数据商的两个接口不算两个独立来源。
- 研究会检查**计算结果、账本一致性和策略复算**，不把程序通过测试等同于策略未来能赚钱。
- 回测统一比较费用、收益、最大回撤和波动；信号与交易时间分开，避免用事后信息“预测”过去。
- 历史账户估值和真实成交分别保存，不把资产估值曲线直接包装成投资收益率。

### 3. 支持长期记录与定时监控

- **本地运行**：提供定时运行、备份恢复和可选的 SMTP 故障邮件通知。
- **私有 Vercel 部署**：实现了按美股交易日调度、同一账户版本的重复运行控制、独立保存研究结果及延迟补跑。是否实际完成每轮行情计算，必须查看真实运行回执。
- 自动计算不覆盖人工确认的持仓，**也不会连接券商自动下单**。邮件通知需要自行配置并测试送达。

详细配置和适用条件见 [私有云部署](docs/VERCEL_CLOUD.md)、[每日自动监控](docs/VERCEL_DAILY_AUTOMATION.md) 和 [本地运行与告警](docs/DAILY_OPERATIONS.md)。

## 结果为什么值得核对

本项目把两件事分开：

**程序有没有按规则算对**：通过自动化测试、账本审计、两种独立计算方式复核和备份恢复检查来验证。

**投资策略长期有没有效果**：需要真实、持续的未来交易日数据，不能靠一次回测或一次成功部署证明。

你可以查看 [验证记录](docs/VALIDATION.md)、[研究公式与假设](docs/FORMULAS.md) 和 [GitHub CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)。这里不把某个历史测试数量写成永久有效的“当前成绩”；每次代码更新以对应的 CI 和运行证据为准。

## 文档入口

| 想了解 | 阅读 |
| --- | --- |
| 项目如何组成 | [架构说明](docs/ARCHITECTURE.md) |
| 如何导入真实估值与交易 | [本地网页](docs/LOCAL_WEB.md) · [操作手册](docs/OPERATIONS.md) |
| 策略公式、回测费用与风险假设 | [研究方法](docs/FORMULAS.md) |
| 如何接入 Alpaca 模拟账户（只读） | [Alpaca Paper Trading](docs/ALPACA_PAPER.md) |
| 如何部署私有云、定时更新与恢复 | [Vercel 云端](docs/VERCEL_CLOUD.md) · [每日自动监控](docs/VERCEL_DAILY_AUTOMATION.md) |
| 计算与部署有哪些证据 | [验证记录](docs/VALIDATION.md) · [自动化测试](https://github.com/wanghaibing07/investlab-monitor/actions) |
| 设计参考、讨论和贡献 | [开源参考](docs/UPSTREAM_REVIEW.md) · [贡献指南](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

## 许可证与数据说明

[MIT 许可证](LICENSE)。公开演示仅使用虚构数据。真实账户、密钥、备份和受授权限制的第三方行情数据不应提交到公开 GitHub 仓库。

InvestLab 提供投资研究与记录工具，不代替交易执行、个性化投资咨询或真实券商账单。
