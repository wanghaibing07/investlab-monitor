# InvestLab · QQQ / TQQQ 长期投资监控

[![tests](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wanghaibing07/investlab-monitor/actions/workflows/ci.yml)

Local-first portfolio monitoring, quantitative research, independent verification, and recoverable evidence journals.

把**账户事实、每日判断、量化研究和运行证据**放进同一个可追溯的系统。

默认长期目标 **60% QQQ + 40% TQQQ**。保留每次最多增加总资产5个百分点的TQQQ分步规则，以及趋势/波动退出条件。所有建议由人决定是否执行；程序没有券商下单接口。

## 五分钟体验

```bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install .
investlab --home /tmp/investlab-demo init --demo
investlab --home /tmp/investlab-demo run
investlab --home /tmp/investlab-demo verify
investlab --home /tmp/investlab-demo serve
```

打开 http://127.0.0.1:8765 。看板包括今日判断、账户到目标的差距、策略净值对照、流水和运行记录。演示行情和账户均为固定、可复现的虚构样本，醒目标明，不调用网络。

Windows使用 `.venv\Scripts\activate`；数据目录可改成自己的路径。Python 3.11及以上，核心运行不需要第三方库或模型API。

## 接入自己的账户

```bash
investlab --home ~/.local/share/investlab init
# 按自己确认的真实数据修改文件后再导入
investlab --home ~/.local/share/investlab valuation-import my-valuation.json
investlab --home ~/.local/share/investlab run --online --independent-check --require-current
investlab --home ~/.local/share/investlab summary
```

估值格式见 [examples/valuation.json](examples/valuation.json)。金额是人民币聚合估值，不等于已知股数或成本。缺少确认估值时，系统不会填入演示账户。

已有v5.5完整目录可直接迁移到空目录：

```bash
investlab --home /private/investlab migrate /path/to/qqq-tqqq-clean
investlab --home /private/investlab audit
```

迁移原样保留全部SQLite旧表、每一行历史记录和必要研究证据，并记录迁移前后各表内容哈希。原数据库不会修改。旧的估值不会伪造为成交。

## 日常命令

| 命令 | 用途 |
|---|---|
| `run --online --independent-check --require-current` | 下载完整收盘行情，计算、保存、回读和核验本地备份；数据不完整返回非零码 |
| `run` | 缓存复算；不会被标为本次联网成功 |
| `summary` | 适合每日通知的中文短结论 |
| `refresh-macro` | 单独更新四个宏观解释因子，失败不拦截ETF账户报告 |
| `research` | 概率、路径推演和十条成熟策略的完整研究报告 |
| `verify` | 独立费用算法复算20组回测，检验未来数据对过去信号的影响 |
| `ledger-import FILE` | 原子导入已确认流水；同ID重试去重，内容冲突拒绝 |
| `account NAME` | 查看流水重放后的现金、股数、加权平均成本和已实现损益 |
| `valuation-import FILE` | 记录独立账户估值；不创造交易 |
| `audit` | 数据库、关系、历史报告、模型证据、账户记录哈希检查 |
| `freeze` | 冻结当前代码与数据截止日，之后开始积累前瞻证据 |
| `backup --output FILE.zip` | 一致性数据库快照＋研究证据＋逐文件哈希 |
| `restore FILE.zip --to EMPTY_DIRECTORY` | 核验后恢复到空目录；拒绝覆盖运行账本 |
| `serve` | 仅本机监听的只读看板；无HTTP写入接口 |
| `doctor` | 检查版本、运行目录、数据库与账户初始化状态 |
| `export --output FILE.json` | 导出当前报告，文件含私人数据 |

所有命令可在子命令前加 `--json`；`--home`统一指定私有运行目录。所有写操作共用操作系统锁，崩溃后锁自动释放。连续观察只计成功完成、行情合格的不同交易日，演示与离线复算不计数。

## 系统包含什么

- **行情**：QQQ/TQQQ原始与复权收盘，保留供应商原文和哈希；拦截错误代码、非日线、数组错位、重复日期、无效价格、未完整收盘与来源冲突。两个Yahoo端点仍算同一供应商。
- **账户**：追加式真实流水、VOID纠正、独立估值、人民币旧基线迁移。十进制金额计算；多币种分别记账，不用未知汇率强行相加。
- **配置判断**：200日趋势缓冲，20日波动门槛，确认持仓驱动的分步增加；重复日报不等于成交。
- **研究**：固定60/40、QQQ基准、风险平价、波动目标、统计均值回归、12个月动量；宏观四因子敏感度、明确事件的概率、联合区块路径推演和费用比较。
- **验证**：独立的解析费用求解器重放全部回测净值；两资产风险平价解析对照；历史前缀检验；完整来源和模型快照。
- **运行**：可安装Python包、只读本地看板、SQLite备份恢复、运行状态、通知去重记录、systemd定时器、容器配置、GitHub CI。

## 如何理解结果

程序测试通过说明代码在这些用例下按预期运行。独立回算一致说明这些计算互相吻合。连续运行成功说明运行链路在观察期内稳定。**三者都不等于策略能赚钱或能跑赢60/40持有。**

历史研究使用真实ETF复权市场价做代理，收盘t产生信号，t+1收盘执行，新增持仓从t+2开始获得收益。费用按每边15/50基点比较；现金利息和税费未建模。真实人民币账户收益需完整份额、现金流和同日汇率，旧聚合估值不足时不计算。

[公式与研究边界](docs/FORMULAS.md) · [架构与源码借鉴](docs/ARCHITECTURE.md) · [日常运行与恢复](docs/OPERATIONS.md) · [验收记录](docs/VALIDATION.md) · [开源来源](docs/UPSTREAM_REVIEW.md)

## 验证开发修改

```bash
PYTHONPATH=src/investlab/engine python -m unittest discover -s tests/legacy -q
python -m unittest discover -s tests/app -q
python scripts/check_release.py
```

发布代码不包含用户账户、真实行情缓存、运行日志、联系方式、凭据或私有备份。GitHub是工作源码唯一来源；私有状态包通过SOURCE.json引用精确提交。示例全部虚构。原v5测试中的可选发行商NAV数据没有随代码再分发，相关用例在缺少该资料时明确跳过。

## 来源与许可

本项目在现有个人v5.5引擎上渐进重构。定向阅读了OpenBB、Qlib、LEAN、Ghostfolio、Wealthfolio、skfolio和QQQ/TQQQ Decision Cockpit的源码，借鉴接口和验证设计，未复制或捆绑这些上游的实现代码。逐项路径、提交和取舍见[源码审阅记录](docs/UPSTREAM_REVIEW.md)。项目代码使用MIT许可；第三方数据的使用和再分发规则独立于代码许可。
