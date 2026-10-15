# 上游源码审阅与取舍

审阅日期：2026-10-15。以下是定向读取的核心文件，不宣称通读这些大型仓库。读取了仓库源码与许可文件，固定到提交以便复查。

本项目没有复制这些上游的实现代码，也没有捆绑其依赖。引用的是架构、接口边界和测试思路；数值模块来自用户原有v5.5项目。

## OpenBB-finance/OpenBB

- 提交：`7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2`；许可：Apache-2.0。
- 采用：请求→采集→转换；数据源隔离。
- 取舍：不为两只ETF引入整个平台。
- 阅读文件：
  - [openbb_platform/core/openbb_core/provider/abstract/fetcher.py](https://github.com/OpenBB-finance/OpenBB/blob/7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2/openbb_platform/core/openbb_core/provider/abstract/fetcher.py)
  - [openbb_platform/core/openbb_core/provider/abstract/provider.py](https://github.com/OpenBB-finance/OpenBB/blob/7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2/openbb_platform/core/openbb_core/provider/abstract/provider.py)

## ghostfolio/ghostfolio

- 提交：`204f0d857ef258a2c090780bce8b69429a094f95`；许可：AGPL-3.0。
- 采用：账户活动/估值/收益分离；存活和就绪分离。
- 取舍：不复制AGPL计算器或引入Angular/NestJS。
- 阅读文件：
  - [apps/api/src/app/portfolio/calculator/portfolio-calculator.ts](https://github.com/ghostfolio/ghostfolio/blob/204f0d857ef258a2c090780bce8b69429a094f95/apps/api/src/app/portfolio/calculator/portfolio-calculator.ts)
  - [apps/api/src/app/health/health.controller.ts](https://github.com/ghostfolio/ghostfolio/blob/204f0d857ef258a2c090780bce8b69429a094f95/apps/api/src/app/health/health.controller.ts)

## wealthfolio/wealthfolio

- 提交：`6773921aa77b8c97ef81ef78268525f24be288a4`；许可：AGPL-3.0。
- 采用：收益质量、成本与估值状态明确建模。
- 取舍：不复制Rust引擎或推算未知成本。
- 阅读文件：
  - [crates/portfolio-engine/src/model/performance.rs](https://github.com/wealthfolio/wealthfolio/blob/6773921aa77b8c97ef81ef78268525f24be288a4/crates/portfolio-engine/src/model/performance.rs)

## QuantConnect/Lean

- 提交：`80e7843f645673bcbeaab963049f76f20f6785e1`；许可：Apache-2.0。
- 采用：目标、未完成订单、实际执行各自有身份。
- 取舍：借鉴边界，不接入自动下单。
- 阅读文件：
  - [Common/Algorithm/Framework/Portfolio/PortfolioTarget.cs](https://github.com/QuantConnect/Lean/blob/80e7843f645673bcbeaab963049f76f20f6785e1/Common/Algorithm/Framework/Portfolio/PortfolioTarget.cs)
  - [Algorithm/Execution/ImmediateExecutionModel.cs](https://github.com/QuantConnect/Lean/blob/80e7843f645673bcbeaab963049f76f20f6785e1/Algorithm/Execution/ImmediateExecutionModel.cs)

## microsoft/qlib

- 提交：`54355232463878d2eebb91fe0ee5fa7fa1f5976c`；许可：MIT。
- 采用：策略与执行器、成交约束、费用假设分离。
- 取舍：不将A股默认交易单位/最低佣金用于美股ETF。
- 阅读文件：
  - [qlib/backtest/executor.py](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/backtest/executor.py)
  - [qlib/backtest/exchange.py](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/backtest/exchange.py)

## skfolio/skfolio

- 提交：`ec37c60aaf036d225fcc74933ff199c07cfb48da`；许可：BSD-3-Clause。
- 采用：按时间划分检验；风险预算独立约束。
- 取舍：不把看过的历史分段称未见样本。
- 阅读文件：
  - [src/skfolio/model_selection/_walk_forward.py](https://github.com/skfolio/skfolio/blob/ec37c60aaf036d225fcc74933ff199c07cfb48da/src/skfolio/model_selection/_walk_forward.py)
  - [src/skfolio/optimization/convex/_risk_budgeting.py](https://github.com/skfolio/skfolio/blob/ec37c60aaf036d225fcc74933ff199c07cfb48da/src/skfolio/optimization/convex/_risk_budgeting.py)

## kydchen/qqq-tqqq-signal-dashboard

- 提交：`53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba`；许可：MIT。
- 采用：手动计划与执行日志；费用和陈旧数据提示。
- 取舍：不复制其估值/恐慌择时阈值。
- 阅读文件：
  - [assets/execution.js](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/assets/execution.js)
  - [test/execution-planner.test.cjs](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/test/execution-planner.test.cjs)
  - [assets/app.js](https://github.com/kydchen/qqq-tqqq-signal-dashboard/blob/53d2ed5c92ccae8ddc1bd9663ba289b66b2edeba/assets/app.js)

## v5.5自身审计

原始ZIP SHA256：`a651b185d3cc0ab667f8362178f6e39f2df8ae8f83d74780491598e4fb504ab1`。原项目190项测试实际执行通过。迁移包含24张非系统旧表、32次运行、1条账户基线与12,586条价格；每张表逐行规范化后计算哈希并核对。

旧数据库中有1条早期研究原型缺少源码和输入快照，原审计已排除其有效证据资格。v6保留原记录及缺口，新增“有源码归档的合格记录缺少输入”独立检查；任何合格记录缺少快照均使审计失败，不用原型排除掩盖新缺口。
