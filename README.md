[简体中文](README.md) · [English](README.en.md)

# InvestLab

**看清 QQQ / TQQQ 持仓、市场趋势和组合风险，让每次投资决策有据可查。**

InvestLab 是开源的 ETF 投资监控与策略研究工具。它将**账户、行情、策略、风险与历史记录**整合到一处，帮助投资者了解当前仓位、评估调整时机，并持续复盘自己的投资方法。

**[在线体验](https://investlab-monitor.vercel.app/)** · [快速开始](#本地快速开始) · [功能介绍](#核心功能) · [English](README.en.md)

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 核心功能

| 功能 | 你能获得什么 |
| --- | --- |
| **投资组合** | 汇总 QQQ、TQQQ、QLD 和现金，查看实际配置、目标比例与估值历史 |
| **每日行情** | 跟踪最新完整美股交易日，查看行情来源、更新时间和校验结果 |
| **策略建议** | 结合长期趋势、市场波动和实际仓位，生成分步调整参考及理由 |
| **风险与回测** | 在统一的行情和费用假设下，对比收益、回撤、波动与不同策略 |
| **自动监控** | 支持定时分析、保存报告、失败补跑与邮件提醒 |
| **数据管理** | 记录估值与成交、保留历史版本，并支持备份、恢复和完整性检查 |

**日常使用：核对仓位 → 查看行情与风险 → 阅读调整依据 → 自主决定交易。**

## 在线体验

**[打开 InvestLab 公开演示](https://investlab-monitor.vercel.app/)**

打开即用，可以浏览「今日判断」「策略研究」「流水与运行」等页面。公开演示采用**虚构账户和示例行情**，展示完整的分析流程及页面交互。

使用自己的持仓数据时，可选择[本地运行](#本地快速开始)或[部署私有云端](docs/VERCEL_CLOUD.md)。

## 本地快速开始

环境要求：**Python 3.11+**。以下命令启动自带示例账户的本地看板。

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

浏览器打开 **http://127.0.0.1:8765**。Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1` 激活虚拟环境。

如需复核运行结果：

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

将示例账户换成自己的实际估值，参阅[本地网页操作](docs/LOCAL_WEB.md)与[使用手册](docs/OPERATIONS.md)。

## 为 QQQ / TQQQ 设计的研究框架

项目内置的长期参考组合为 **QQQ 60% + TQQQ 40%**，并使用以下信息生成每日复核建议：

- **趋势**：200 日趋势衡量市场方向。
- **波动**：近期波动及风险指标辅助控制组合敞口。
- **分步配置**：将长期目标拆解为可审阅的单次调整参考。
- **策略对比**：在统一的交易费用和历史行情下研究不同配置方法。

**长期目标、本步参考与实际持仓分别呈现**，便于理解每个调整动作的依据。TQQQ 采用每日三倍杠杆机制，组合分析同时关注潜在回撤与波动风险。

## 自动化与数据管理

InvestLab 支持两种运行方式：

| 运行方式 | 适用场景 |
| --- | --- |
| **本地部署** | 在自己的电脑或 Linux 服务器上记录账户、计算策略、安排定时任务 |
| **私有 Vercel 部署** | 通过身份验证访问个人看板，保存历史账户版本，按美股交易日自动分析并进行失败补跑 |

定时计算和人工确认的账户记录分别保存；研究报告包含运行日期、行情质量与计算状态。邮件提醒由部署者按需配置。**交易执行由投资者自主决定。**

部署说明：[私有云端](docs/VERCEL_CLOUD.md) · [每日自动监控](docs/VERCEL_DAILY_AUTOMATION.md) · [备份与运行维护](docs/DAILY_OPERATIONS.md)。

## 可追溯的计算与研究

数据检查、账户审计、策略复算与历史结果评价构成一套完整的研究流程。每次运行都保存可追溯记录，方便比较不同规则、分析结果变化和复现计算过程。

- [验证记录](docs/VALIDATION.md)：自动化测试、审计和研究复核
- [研究方法](docs/FORMULAS.md)：策略公式、费用、回测及风险假设
- [GitHub Actions](https://github.com/wanghaibing07/investlab-monitor/actions)：最新构建与测试状态

## 文档与参与

| 内容 | 入口 |
| --- | --- |
| 系统架构 | [架构说明](docs/ARCHITECTURE.md) |
| 账户录入与日常操作 | [本地网页](docs/LOCAL_WEB.md) · [操作手册](docs/OPERATIONS.md) |
| 私有云部署、定时运行 | [Vercel 云端](docs/VERCEL_CLOUD.md) · [每日监控](docs/VERCEL_DAILY_AUTOMATION.md) |
| Alpaca 模拟账户数据 | [Alpaca Paper Trading](docs/ALPACA_PAPER.md) |
| 设计参考与项目贡献 | [开源参考](docs/UPSTREAM_REVIEW.md) · [贡献指南](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

**开源协议：** [MIT](LICENSE)。策略结果用于投资研究，投资者结合个人情况自主决策。
