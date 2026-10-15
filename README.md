[简体中文](README.md) · [English](README.en.md)

# InvestLab

**记录 QQQ 和 TQQQ 持仓，跟踪行情，比较投资策略。**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

InvestLab 根据行情和持仓给出仓位调整参考，并保存计算依据，方便复查。通过命令行或网页即可查看，数据保存在自己的电脑上，交易由你决定并执行。

[快速体验](#快速体验) · [核心能力](#核心能力) · [使用自己的账户](#使用自己的账户) · [文档](#文档) · [参与贡献](CONTRIBUTING.md)

## 快速体验

需要 **Python 3.11 或更高版本**，核心程序使用 Python 标准库。下面用自带的模拟账户和示例行情体验功能，行情计算可离线运行。

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

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)，查看持仓、调整建议、策略收益曲线和历史记录。演示页面会标明模拟数据；按 `Ctrl+C` 停止服务。`runtime/` 已由 Git 忽略。

Windows PowerShell 将激活命令替换为 `.\.venv\Scripts\Activate.ps1`，其余命令相同；也可以直接调用 `.\.venv\Scripts\investlab.exe`。当前命令行和看板以中文为主，英文首页提供项目与使用说明。

另开终端，激活同一虚拟环境后可检查计算结果和数据完整性：

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

`verify` 用独立算法重新计算 20 组策略与费用组合，完整结果保存在 `runtime/demo/data/verification.json`。

## 核心能力

| 能力 | 能帮你做什么 |
| --- | --- |
| 跟踪行情 | 更新 QQQ/TQQQ 收盘价，显示数据日期、来源和异常 |
| 管理持仓 | 分开记录账户估值和已确认交易，保留修改历史，避免重复录入 |
| 查看调整建议 | 根据趋势、波动和已确认持仓，给出每一步的目标比例 |
| 比较投资策略 | 查看固定 60/40、风险平价、波动目标、均值回归、动量等十类策略的历史结果 |
| 检查计算 | 用独立算法核对收益曲线、交易费用和风险分配，检查历史信号的时间顺序 |
| 备份与恢复 | 保存账户、报告及计算所用数据，恢复前检查文件和数据库完整性 |
| 定时运行 | 提供容器和 systemd 配置，可在自己的主机上按时更新 |

## 默认规则

长期目标为 **60% QQQ + 40% TQQQ**。系统结合 200 日趋势和 20 日波动给出调整参考；每次建议增加的 TQQQ 最多为总资产的 5 个百分点，从最后确认持仓开始计算。账户记录在你导入新估值或确认流水后更新。

## 使用自己的账户

将真实运行数据放在源码仓库之外。先按自己的已确认数据创建估值文件，格式见 [valuation.json](examples/valuation.json)；示例中的账户均为虚构。

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
```

首次运行前请填写自己的估值文件。估值用于记录各资产金额，股数、成本和成交由确认流水提供。使用 `ledger-import` 导入，格式见 [events.json](examples/events.json)。

系统按最新已完成的美股交易日检查行情。来源价格有冲突时，会提示核对后再生成新建议。Yahoo 的两个接口按同一数据源统计，独立核对结果单独显示。宏观数据用于解释风险，ETF 监控可独立运行。

已有 v5.5 完整项目可迁移到新目录，原账本保留不动：

```bash
investlab --home /private/investlab migrate /path/to/qqq-tqqq-clean
investlab --home /private/investlab audit
```

迁移会逐表检查数据一致性，保留历史报告、账户记录和研究数据。运行、调度和恢复方式见[操作手册](docs/OPERATIONS.md)。

## 日常命令

所有命令使用同一个 `--home` 数据目录；`--json` 放在子命令之前，可获得机器可读结果。

| 命令 | 用途 |
| --- | --- |
| `run --online --independent-check --require-current` | 更新行情、计算、存档、回读与核验本地备份；数据不合格时非零退出 |
| `run` / `summary` | 使用缓存复算 / 输出每日中文短结论 |
| `refresh-macro` / `research` / `evaluate` | 更新四组宏观解释因子 / 生成策略研究 / 评估已到期观察 |
| `valuation-import FILE` / `ledger-import FILE` | 导入确认估值 / 导入确认流水 |
| `account NAME` | 查看按账户和币种重放的现金、股数、已知成本与已实现损益 |
| `verify` / `audit` | 独立复算 / 检查数据库、关系和证据哈希 |
| `freeze` | 记录代码版本和数据日期，便于后续比较 |
| `backup --output FILE.zip` | 创建一致性数据库快照、研究证据与逐文件清单 |
| `restore FILE.zip --to EMPTY_DIRECTORY` | 核验后恢复到空目录 |
| `doctor` / `serve` | 检查运行环境 / 打开本机只读看板 |
| `export --output FILE.json` | 导出当前报告，导出文件包含私人数据 |

## 验证结果与研究说明

当前 v6.0.1 有 **240 项测试通过，1 项可选发行商 NAV 数据测试因资料未分发而跳过**。GitHub CI 覆盖 Python 3.11、3.12、3.13，以及同一持久卷上的只读容器运行、独立复算和审计。

重构前后在冻结的同一行情上，十条策略 × 两档费用的汇总结果完全一致；20 组净值路径独立复算最大相对偏差约 `3.3e-14`。[验证记录](docs/VALIDATION.md)提供检查方法和具体结果。

研究使用美元 ETF 复权市场价，收盘 t 产生信号，t+1 收盘执行，新增持仓从 t+2 开始获得收益；比较每边 15 / 50 基点费用，未计税费与现金利息。真实人民币账户收益需要完整份额、现金流和同日汇率。

历史回测用于比较策略；实际投资结果还取决于后续行情、交易费用和执行情况。概率模型当前的历史表现低于历史频率基准，作为研究对照保留。公式、假设和评估方法见[研究说明](docs/FORMULAS.md)。

## 文档

| 想了解什么 | 阅读入口 |
| --- | --- |
| 英文使用说明 | [English README](README.en.md) |
| 设计与模块边界 | [架构](docs/ARCHITECTURE.md) |
| 公式、执行时序与模型限制 | [研究说明](docs/FORMULAS.md) |
| 每日运行、迁移、容器与恢复 | [操作手册](docs/OPERATIONS.md) |
| 检查方法与运行结果 | [验证记录](docs/VALIDATION.md) |
| 借鉴了哪些成熟项目、保留了什么取舍 | [上游源码审阅](docs/UPSTREAM_REVIEW.md) |
| 报告问题、修改代码或改进文档 | [贡献指南](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

详细技术文档目前以中文为主；英文首页包含安装、账户接入、命令、迁移、恢复和验证说明。

## 参与贡献

欢迎反馈问题、改进文档或提交修复。提交前请先阅读[贡献指南](CONTRIBUTING.md)，使用独立演示目录验证，移除账户数据、缓存、日志和凭据。模型变更请附上使用的数据日期、费用假设和修改前后的比较结果。

## 来源与许可

InvestLab 基于 v5.5 计算引擎开发，参考了 OpenBB、Qlib、LEAN、Ghostfolio、Wealthfolio、skfolio 和 QQQ/TQQQ Decision Cockpit 的接口设计与验证方法。参考文件、对应版本和设计选择见[源码审阅记录](docs/UPSTREAM_REVIEW.md)。

代码使用 [MIT 许可证](LICENSE)。第三方市场数据的获取与再分发规则独立于代码许可。源码发布在 GitHub，个人账户和运行数据保存在独立私有目录。
