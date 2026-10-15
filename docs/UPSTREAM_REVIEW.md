# 上游源码审阅与取舍

审阅日期：2026-10-15。本页列出审阅的核心源码与许可文件，固定到具体提交，便于复查参考来源。

参考内容为架构、接口设计和测试方法，上游实现代码与依赖均未随本项目分发。数值模块沿用InvestLab的v5.5引擎。

## OpenBB-finance/OpenBB

- 提交：`7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2`；许可：Apache-2.0。
- 采用：请求→采集→转换；数据源隔离。
- 取舍：采用轻量数据适配层，满足两只ETF的行情需求。
- 阅读文件：
  - [openbb_platform/core/openbb_core/provider/abstract/fetcher.py](https://github.com/OpenBB-finance/OpenBB/blob/7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2/openbb_platform/core/openbb_core/provider/abstract/fetcher.py)
  - [openbb_platform/core/openbb_core/provider/abstract/provider.py](https://github.com/OpenBB-finance/OpenBB/blob/7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2/openbb_platform/core/openbb_core/provider/abstract/provider.py)

## ghostfolio/ghostfolio

- 提交：`204f0d857ef258a2c090780bce8b69429a094f95`；许可：AGPL-3.0。
- 采用：账户活动/估值/收益分离；存活和就绪分离。
- 取舍：使用独立Python实现和本地网页，保持部署简单。
- 阅读文件：
  - [apps/api/src/app/portfolio/calculator/portfolio-calculator.ts](https://github.com/ghostfolio/ghostfolio/blob/204f0d857ef258a2c090780bce8b69429a094f95/apps/api/src/app/portfolio/calculator/portfolio-calculator.ts)
  - [apps/api/src/app/health/health.controller.ts](https://github.com/ghostfolio/ghostfolio/blob/204f0d857ef258a2c090780bce8b69429a094f95/apps/api/src/app/health/health.controller.ts)

## wealthfolio/wealthfolio

- 提交：`6773921aa77b8c97ef81ef78268525f24be288a4`；许可：AGPL-3.0。
- 采用：收益质量、成本与估值状态明确建模。
- 取舍：沿用Python计算引擎，将缺失成本明确标记。
- 阅读文件：
  - [crates/portfolio-engine/src/model/performance.rs](https://github.com/wealthfolio/wealthfolio/blob/6773921aa77b8c97ef81ef78268525f24be288a4/crates/portfolio-engine/src/model/performance.rs)

## QuantConnect/Lean

- 提交：`80e7843f645673bcbeaab963049f76f20f6785e1`；许可：Apache-2.0。
- 采用：目标、未完成订单、实际执行各自有身份。
- 取舍：分别保存目标和执行记录，真实交易由人工完成。
- 阅读文件：
  - [Common/Algorithm/Framework/Portfolio/PortfolioTarget.cs](https://github.com/QuantConnect/Lean/blob/80e7843f645673bcbeaab963049f76f20f6785e1/Common/Algorithm/Framework/Portfolio/PortfolioTarget.cs)
  - [Algorithm/Execution/ImmediateExecutionModel.cs](https://github.com/QuantConnect/Lean/blob/80e7843f645673bcbeaab963049f76f20f6785e1/Algorithm/Execution/ImmediateExecutionModel.cs)

## microsoft/qlib

- 提交：`54355232463878d2eebb91fe0ee5fa7fa1f5976c`；许可：MIT。
- 采用：策略与执行器、成交约束、费用假设分离。
- 取舍：交易单位与佣金假设按美股ETF配置。
- 阅读文件：
  - [qlib/backtest/executor.py](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/backtest/executor.py)
  - [qlib/backtest/exchange.py](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/backtest/exchange.py)

## skfolio/skfolio

- 提交：`ec37c60aaf036d225fcc74933ff199c07cfb48da`；许可：BSD-3-Clause。
- 采用：按时间划分检验；风险预算独立约束。
- 取舍：将开发期历史诊断与后续数据评价分开。
- 阅读文件：
  - [src/skfolio/model_selection/_walk_forward.py](https://github.com/skfolio/skfolio/blob/ec37c60aaf036d225fcc74933ff199c07cfb48da/src/skfolio/model_selection/_walk_forward.py)
  - [src/skfolio/optimization/convex/_risk_budgeting.py](https://github.com/skfolio/skfolio/blob/ec37c60aaf036d225fcc74933ff199c07cfb48da/src/skfolio/optimization/convex/_risk_budgeting.py)

## kydchen/qqq-tqqq-signal-dashboard

- 提交：`53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba`；许可：MIT。
- 采用：手动计划与执行日志；费用和陈旧数据提示。
- 取舍：采用本项目的趋势、波动和分步配置规则。
- 阅读文件：
  - [assets/execution.js](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/assets/execution.js)
  - [test/execution-planner.test.cjs](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/test/execution-planner.test.cjs)
  - [assets/app.js](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/assets/app.js)

## v5.5迁移验证

原始ZIP SHA256：`a651b185d3cc0ab667f8362178f6e39f2df8ae8f83d74780491598e4fb504ab1`。原项目190项测试实际执行通过。迁移包含24张非系统旧表、32次运行、1条账户基线与12,586条价格；每张表逐行规范化后计算哈希并核对。

迁移数据中有1条早期研究记录缺少源码和输入快照，单独标记并排除在有效研究统计之外。v6检查每条有效研究记录的源码和输入快照，缺失时审计返回错误。
