[简体中文](#简体中文) · [English](#english)

# Contributing to InvestLab

## 简体中文

欢迎改进文档、修复可复现的问题、补充数据适配和数值验证。较大的模型或接口变更，请先在 [Issues](https://github.com/wanghaibing07/investlab-monitor/issues) 说明具体问题与预期行为。

### 报告问题

提供 InvestLab 与 Python 版本、操作系统、已脱敏的命令、预期与实际结果，以及最小复现步骤。优先使用演示账户。行情问题请说明供应商、行情日期和采集时间；没有取得数据时保留缺失状态。

公开提交前移除真实账户、交易、联系方式、令牌、完整运行 ZIP 和私人日志。安全问题先使用本地虚构数据重现，仅公开不含敏感信息的说明。

### 修改与验证

```bash
git clone https://github.com/wanghaibing07/investlab-monitor.git
cd investlab-monitor
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

PYTHONPATH=src/investlab/engine python -m unittest discover -s tests/legacy -q
python -m unittest discover -s tests/app -q
python scripts/check_release.py
```

Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1` 激活环境；旧引擎测试前先设置 `$env:PYTHONPATH = 'src/investlab/engine'`，然后运行 `python -m unittest discover -s tests/legacy -q`。

验证运行行为时使用独立演示目录，按 [README](README.md#快速体验) 执行 `init --demo`、`run`、`verify` 和 `audit`。演示数据与真实账户使用不同目录。容器和 Python 版本兼容性由 GitHub CI 继续检查。

提交说明写清具体问题、修改后的行为与验证结果。故障修复应提供能够暴露该问题的用例；文案修订检查双语一致性和链接即可。模型或公式变更需要说明信号与成交时间、费用、输入截止日以及同数据前后对照，更新相应文档与版本证据。

### 双语文档

`README.md` 为中文首页，`README.en.md` 为英文首页。两页最前面的语言入口互相链接。修改功能、安装步骤或验证结论时同步更新两页；命令行和看板目前以中文为主。详细技术文档可以逐步翻译，现有中文链接须清楚标注。

## English

Documentation improvements, reproducible fixes, data adapters, and numerical checks are welcome. Before a substantial model or interface change, open an [issue](https://github.com/wanghaibing07/investlab-monitor/issues) describing the concrete problem and expected behavior.

### Report a problem

Include the InvestLab and Python versions, operating system, a sanitized command, expected and actual behavior, and minimal reproduction steps. Prefer a demo account. For market-data issues, include the provider, price date, and retrieval time; retain missing-data states when no data was obtained.

Remove real accounts, trades, contact information, tokens, full runtime archives, and private logs before posting. Reproduce security issues with fictional local data first; publish only a description that contains no sensitive information.

### Develop and verify

Use the installation and test commands in the Chinese section above. On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1`; before the legacy suite, set `$env:PYTHONPATH = 'src/investlab/engine'` and run `python -m unittest discover -s tests/legacy -q`.

For runtime changes, use a separate demo directory and follow the [English quick start](README.en.md#quick-start): `init --demo`, `run`, `verify`, and `audit`. Keep demo data and real accounts in separate directories. GitHub CI also checks the Python matrix and containers.

Describe the concrete problem, resulting behavior, and validation in your pull request. Add a regression case that exposes a corrected failure. For text-only changes, check translation consistency and links. Model or formula changes should document signal/execution timing, fees, the input cutoff, and before/after comparisons on identical data; update the corresponding methodology and version evidence.

### Bilingual documentation

`README.md` is the Chinese entry and `README.en.md` is the English entry. Keep their first-line language links reciprocal. Update both when capabilities, installation steps, or validation claims change. The CLI and dashboard are currently primarily in Chinese. Detailed technical documents can be translated incrementally; identify links to the existing Chinese material clearly.
