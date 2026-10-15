[简体中文](README.md) · [English](README.en.md)

# InvestLab

**QQQ / TQQQ 长期投资监控与量化研究。账户、判断、计算和证据，一处追溯。**

[![CI](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

InvestLab 是一个数据保存在本地的投资监控工具：导入已确认的账户记录，更新完整收盘行情，生成分步配置建议，比较策略，并保存可回放的计算证据。配有命令行和只读网页看板，核心运行无需第三方 Python 库、模型 API 或云服务账号。

默认长期目标为 **60% QQQ + 40% TQQQ**。每次增加 TQQQ 的建议以最后确认持仓为起点，最多增加总资产的 5 个百分点，并结合趋势与波动条件。最终交易由人执行。

[快速体验](#快速体验) · [核心能力](#核心能力) · [使用自己的账户](#使用自己的账户) · [文档](#文档) · [参与贡献](CONTRIBUTING.md)

## 快速体验

需要 **Python 3.11 或更高版本**。以下使用独立目录中的固定虚构账户和行情，无需联网获取市场数据。

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

打开 **http://127.0.0.1:8765**，查看今日判断、账户到目标的差距、策略净值比较、流水和运行记录。演示页面会标明虚构数据；按 `Ctrl+C` 停止服务。`runtime/` 已由 Git 忽略。

Windows PowerShell 将激活命令替换为 `.\.venv\Scripts\Activate.ps1`，其余命令相同；也可以直接调用 `.\.venv\Scripts\investlab.exe`。当前命令行和看板以中文为主，英文首页提供项目与使用说明。

另开终端，激活同一虚拟环境后可复核演示计算：

```bash
investlab --home ./runtime/demo verify
investlab --home ./runtime/demo audit
```

`verify` 重放 20 组策略与费用组合，完整结果保存在 `runtime/demo/data/verification.json`。

## 核心能力

| 能力 | 实际用途 |
| --- | --- |
| 完整收盘行情 | 获取 QQQ/TQQQ 原始与复权收盘，保留供应商原文和哈希，识别未完成日线、过期数据与来源冲突 |
| 真实账户记录 | 分开保存已确认流水与独立估值；十进制金额、同 ID 去重、冲突整批回滚；通过追加纠正保留原始记录 |
| 分步配置判断 | 使用 200 日趋势缓冲与 20 日波动条件，区分长期目标、本轮建议和实际持仓；重复日报不会被记为成交 |
| 策略与情景研究 | 比较固定 60/40、QQQ 基准、风险平价、波动目标、均值回归与动量等十类策略；提供宏观敏感度、事件概率和路径推演 |
| 独立数值复核 | 用另一套费用求解方法重放净值，对照两资产风险平价解析解，检查未来数据是否改变过去信号 |
| 可恢复的运行证据 | SQLite 账本、源码与输入快照、单写者锁、失败记录、一致性备份和核验后恢复 |
| 本地界面与部署 | 只读网页看板、可安装 Python 包、容器和 systemd 模板，以及多版本 GitHub CI |

## 使用自己的账户

将真实运行数据放在源码仓库之外。先按自己的已确认数据创建估值文件，格式见 [valuation.json](examples/valuation.json)；示例中的账户均为虚构。

```bash
investlab --home ~/.local/share/investlab init
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
```

首次运行前必须填写自己的估值文件。聚合估值不会被推算成股数、成本或成交。真实流水另用 `ledger-import` 导入，格式见 [events.json](examples/events.json)。

行情必须覆盖最新已完成的美股交易日；来源冲突会阻止新配置。两个 Yahoo 端点仍属于同一供应商，备用来源失败会单独显示。宏观因子用于解释风险，单独获取失败不阻断 ETF 监控。

已有 v5.5 完整项目可迁移到新目录，原账本保留不动：

```bash
investlab --home /private/investlab migrate /path/to/qqq-tqqq-clean
investlab --home /private/investlab audit
```

迁移逐表核对历史内容哈希，保留报告、账户基线与研究证据。运行、调度和恢复方式见[操作手册](docs/OPERATIONS.md)。

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
| `freeze` | 固定源码与数据截止日，开始积累该版本的前瞻证据 |
| `backup --output FILE.zip` | 创建一致性数据库快照、研究证据与逐文件清单 |
| `restore FILE.zip --to EMPTY_DIRECTORY` | 核验后恢复到空目录 |
| `doctor` / `serve` | 检查运行环境 / 打开本机只读看板 |
| `export --output FILE.json` | 导出当前报告，导出文件包含私人数据 |

## 验证与研究边界

当前 v6.0.1 有 **240 项测试通过，1 项可选发行商 NAV 数据测试因资料未分发而跳过**。GitHub CI 覆盖 Python 3.11、3.12、3.13，以及同一持久卷上的只读容器运行、独立复算和审计。

重构前后在冻结的同一行情上，十条策略 × 两档费用的汇总结果完全一致；20 组净值路径独立复算最大相对偏差约 `3.3e-14`。[验证记录](docs/VALIDATION.md)列出方法、证据与待观察项。

研究使用美元 ETF 复权市场价，收盘 t 产生信号，t+1 收盘执行，新增持仓从 t+2 开始获得收益；比较每边 15 / 50 基点费用，未计税费与现金利息。真实人民币账户收益需要完整份额、现金流和同日汇率。

现有事件概率模型尚未胜过历史频率基准。长期稳定性与策略效果继续积累未来证据；测试通过、回算一致和短期运行成功各有适用范围，均不代表投资收益得到保证。具体公式见[研究说明](docs/FORMULAS.md)。

## 文档

| 想了解什么 | 阅读入口 |
| --- | --- |
| 英文使用说明 | [English README](README.en.md) |
| 设计与模块边界 | [架构](docs/ARCHITECTURE.md) |
| 公式、执行时序与模型限制 | [研究说明](docs/FORMULAS.md) |
| 每日运行、迁移、容器与恢复 | [操作手册](docs/OPERATIONS.md) |
| 实测结果与当前缺口 | [验证记录](docs/VALIDATION.md) |
| 借鉴了哪些成熟项目、保留了什么取舍 | [上游源码审阅](docs/UPSTREAM_REVIEW.md) |
| 报告问题、修改代码或改进文档 | [贡献指南](CONTRIBUTING.md) · [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) |

详细技术文档目前以中文为主；英文首页包含安装、账户接入、命令、迁移、恢复和验证说明。

## 参与贡献

欢迎提交可复现的问题、文档改进和有证据支持的修复。提交前请先阅读[贡献指南](CONTRIBUTING.md)，使用独立演示目录验证，移除账户数据、缓存、日志和凭据。模型变更请同时提供数据时间边界、费用假设与前后结果。

## 来源与许可

InvestLab 在原有 v5.5 数值引擎上渐进重构。定向阅读了 OpenBB、Qlib、LEAN、Ghostfolio、Wealthfolio、skfolio 和 QQQ/TQQQ Decision Cockpit，借鉴接口和验证设计，未复制或捆绑这些上游实现。路径、固定提交与取舍见[源码审阅记录](docs/UPSTREAM_REVIEW.md)。

代码使用 [MIT 许可证](LICENSE)。第三方市场数据的获取与再分发规则独立于代码许可。GitHub 保存工作源码；个人账本与运行证据保存在独立私有目录，状态包通过 `SOURCE.json` 引用精确源码提交。
