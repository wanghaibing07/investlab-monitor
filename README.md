[简体中文](README.md) · [English](README.en.md)

# InvestLab

**把 QQQ / TQQQ 的持仓、行情和投资策略放在一起，让每天的投资决定有据可查。**

InvestLab 是一个开源、可在自己电脑上运行的投资监控工具。它帮你看清**现在持有什么、今天需要关注什么、为什么考虑调整仓位，以及不同投资方法过去表现如何**。系统提供计算和判断依据，买卖由你自己决定。

**[在线体验（虚构数据）](https://investlab-monitor.vercel.app/)**：无需安装。在线版是只读的演示快照，不接入实时行情或真实账户；完整功能请在本机运行。

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[快速体验](#快速体验) · [能用来做什么](#能用来做什么) · [使用自己的账户](#使用自己的账户) · [计算是否可信](#计算是否可信) · [更多文档](#更多文档)

## 能用来做什么

打开网页看板，主要看三个页面：

| 页面 | 你能看到什么 |
| --- | --- |
| **今日判断** | 最后确认的持仓、目标比例、下一步调整参考、判断理由，以及行情是否更新 |
| **策略研究** | 同一段历史行情下，不同投资规则的收益曲线、最大回撤、波动和交易费用 |
| **流水与运行** | 已确认的账户变动、历史计算记录，以及每次运行的结果 |

日常使用可以按这个顺序：**先核对持仓和行情日期 → 看调整参考及原因 → 比较风险 → 自己决定是否交易**。

项目还提供账户流水记录、历史报告、定时更新、备份恢复和独立计算核对。数据可以留在自己的运行目录中，不需要把个人账户上传到 GitHub。

## 快速体验

准备 **Python 3.11+**，复制以下命令即可用**虚构账户和示例行情**打开看板，无需提供真实持仓。核心演示可离线运行。

~~~bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .

investlab --home ./runtime/demo init --demo
investlab --home ./runtime/demo run
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo serve
~~~

浏览器打开 **http://127.0.0.1:8765**。你会看到今日判断、策略对比和历史记录；演示数据会标明为模拟数据。按 `Ctrl+C` 关闭网页服务。

Windows PowerShell 把 `source .venv/bin/activate` 换成 `.\.venv\Scripts\Activate.ps1`，其余命令相同。命令行和网页目前主要使用中文。

想检查演示数据是否完整，可另开终端并激活同一虚拟环境：

~~~bash
investlab --home ./runtime/demo audit
~~~

## 默认关注的投资组合

当前内置的长期目标是 **60% QQQ + 40% TQQQ**。两只基金都跟踪纳斯达克 100 相关风险，其中 **TQQQ 追求每日 3 倍杠杆表现**，长期持有的风险和波动明显更高。

系统参考 **200 日价格趋势和近 20 日波动**，再结合你最后确认的实际持仓，给出分步调整参考；单次建议增加的 TQQQ 不超过总资产的 **5 个百分点**。这是一套可供研究的既定规则，并非适合所有人的投资比例。

**重点：目标仓位不等于实际成交。** 程序不会因为出现调整建议就修改你的交易记录，也不会连接券商自动下单。只有导入已确认的账户数据，记录才会更新。

## Alpaca 模拟账户与风险情景

- **网页演示**：在「策略研究」页调整指数单日涨跌和 TQQQ 仓位，即时查看假设的单日组合敏感性，不下单。
- **本地模拟券商接入**：`alpaca-paper-snapshot` 只读取 Alpaca Paper Trading 模拟账户和持仓，单独保存为美元风险快照；不修改人民币账户。
- **研究方法**：参照 Public Equity Investing 的风险敞口、情景分析和证据分级原则。ChatGPT 的插件授权不会传给网站。
- 具体使用方法、凭据和边界见 [Alpaca 模拟账户](docs/ALPACA_PAPER.md)。

## 本地网页录入账户与重新计算

无需编写JSON文件，也可以在本机网页上添加已确认的人民币资产估值：

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab serve --local-edit
```

打开 `http://127.0.0.1:8765`，填写QQQ、TQQQ、QLD和现金估值，确认后保存。然后自行选择使用缓存行情计算或联网更新并核验行情。该操作**不会被记成买卖成交**，不会自动下单。首次初始化只执行一次；已有目录直接运行 `serve --local-edit` 即可。普通 `serve` 继续只读，公网演示版始终禁止编辑账户。

[查看本地网页操作与安全边界](docs/LOCAL_WEB.md)。

## 使用自己的账户

先用 [估值文件示例](examples/valuation.json) 填写你的真实资产金额，再运行：

~~~bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
~~~

- **估值**记录各资产当前金额；**成交流水**记录真正买卖的股数、成本和资金变化。已确认交易可按 [流水示例](examples/events.json) 使用 `ledger-import` 导入。
- `run --online` 获取行情、生成结论并保存结果；`summary` 用简短中文说明本次判断。
- 真实账户放在独立的私有目录。在线更新会访问行情提供商，但本地账户文件不必提交到公开仓库。

行情来自外部服务时，系统会显示数据日期、来源和检查结果；同一供应商的多个接口不会被当成多个独立来源。

## 计算是否可信

项目把“**程序算对了**”和“**策略未来能赚钱**”分开验证。

| 关心的问题 | 项目如何处理 |
| --- | --- |
| 计算有没有算错？ | 用另一套计算方法复核 10 类策略、两档交易费用，共 20 组结果 |
| 有没有偷看未来行情？ | 检查信号产生、下一交易日执行及后续收益的时间顺序 |
| 回测是不是实际收益？ | 历史策略对比使用美元 ETF 行情；个人账户收益单独按实际流水核算 |
| 数据丢了怎么办？ | 可以备份、恢复，并检查数据库和文件是否完整 |
| 可以长期自动运行吗？ | 提供 [systemd 定时任务](deploy/investlab.timer) 和 [容器配置](deploy/compose.yaml) |

截至 **2026-10-15** 的[验证记录](docs/VALIDATION.md)：**240 项测试通过，1 项依赖可选外部数据的测试跳过**；Python 3.11–3.13 和容器流程已在 GitHub CI 验证。20 组收益曲线的独立复算结果一致。

历史回测用于比较方法，不等于未来收益承诺。回测计入两档模拟交易费用，未计税费与现金利息；真实账户结果还取决于交易、资金流和汇率。完整假设见[研究方法](docs/FORMULAS.md)。

## 私有 Vercel 云端运行（独立部署）

云端版 `investlab-cloud` 在 Vercel Authentication 后访问；使用私有 Blob 保存版本化的账户与计算快照，绝不与 [公开虚构演示](https://investlab-monitor.vercel.app/) 共享真实账户数据。新建项目默认**不自动初始化用户账户，也不启用 Cron**，先完成本人确认的账户初始化和线上验证；避免尚未配置的任务被误报为运行成功。

[私有云端架构、配置和验收说明](docs/VERCEL_CLOUD.md)。

## 每日自动运行与失败告警

在自己的私有 Linux 主机上，可运行 `daily-cycle` 完成在线行情、持久化、独立复核、成熟结果评价与状态记录：

```bash
investlab --home ~/.local/share/investlab daily-cycle
investlab --home ~/.local/share/investlab daily-status
```

失败和宏观数据降级会产生私有待发通知；仅配置 SMTP 后 `notify-pending` 才会发送邮件。默认不发送邮件，也不会把账户数据上传 Vercel。

[查看定时任务、私有告警配置与故障恢复](docs/DAILY_OPERATIONS.md)。

## 常用命令

使用同一个 `--home` 目录保存你的记录。

| 命令 | 用途 |
| --- | --- |
| `run` / `summary` | 计算并保存 / 查看当天简短结论 |
| `valuation-import FILE` / `ledger-import FILE` | 更新确认估值 / 导入已确认成交 |
| `account NAME` | 查看账户现金、持仓与成本 |
| `research` / `verify` | 研究历史策略 / 独立复算 |
| `audit` / `doctor` | 检查数据完整性 / 检查运行环境 |
| `backup --output FILE.zip` | 备份账户、报告和研究记录 |
| `restore FILE.zip --to EMPTY_DIRECTORY` | 恢复到新的空目录 |
| `serve` | 打开仅供本机访问的只读网页 |

每日更新、容器部署、迁移与恢复示例见[操作手册](docs/OPERATIONS.md)。

## 更多文档

| 想了解什么 | 阅读入口 |
| --- | --- |
| English introduction and usage | [English README](README.en.md) |
| 程序由哪些部分组成 | [架构说明](docs/ARCHITECTURE.md) |
| 投资规则、公式、费用和回测假设 | [研究方法](docs/FORMULAS.md) |
| 安装、定时运行、备份与迁移 | [操作手册](docs/OPERATIONS.md) |
| 测试和独立复核的具体依据 | [验证记录](docs/VALIDATION.md) |
| 参考了哪些开源项目 | [源码参考与设计选择](docs/UPSTREAM_REVIEW.md) |
| 反馈问题、参与开发 | [贡献指南](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

## 开源许可

代码采用 [MIT 许可证](LICENSE)。个人账户、行情缓存、备份和密钥应保存在私有目录；第三方行情数据另遵循对应服务的使用条款。
