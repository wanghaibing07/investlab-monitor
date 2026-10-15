# Alpaca 模拟账户（只读）

InvestLab 可以读取自己的 **Alpaca Paper Trading** 模拟账户，生成独立的风险快照。这与 ChatGPT 的 Alpaca 插件是两个不同的授权环境：ChatGPT 插件连接不等于本地程序或 Vercel 获得账户访问权。

## 安全边界

- 仅使用 `https://paper-api.alpaca.markets/v2/account` 和 `/v2/positions`，方法始终为 GET。
- **没有**下单、撤单、真实交易、自动同步成交、账户修改接口。
- API Key 只从本地进程环境变量读取，不写入 GitHub、网页、Vercel、日志或演示快照。
- 输出为 **USD 模拟账户**。现有 InvestLab 的人民币真实账户不被修改，不进行隐式汇率转换。
- 不支持的其他仓位会被明确标注；这时 QQQ/TQQQ 风险度量只是部分敞口。
- 单日敏感性近似 `QQQ权重 + 3×TQQQ权重`；乘以假设的指数单日变化。它不是 TQQQ 长期收益预测，忽略实际跟踪误差、费用和路径依赖。

## 使用

先在 Alpaca Paper Trading 控制台获取**模拟账户**凭据，不要使用真实券商账户凭据。将环境变量放在私有终端中，不上传仓库。

```bash
export APCA_API_KEY_ID="你的模拟账户Key"
export APCA_API_SECRET_KEY="你的模拟账户Secret"
investlab --home ~/.local/share/investlab alpaca-paper-snapshot
```

命令会保存 `<home>/data/alpaca-paper-snapshot.json`（权限 0600），同时输出不包含 API Key 的摘要。读取失败会返回非零状态，不使用虚构持仓顶替结果。运行前无需初始化真实账户，不影响本地持仓。

## 与 Public Equity Investing 方法的结合

风险快照沿用上市资产投资研究的三层证据原则：

1. **券商源事实**：模拟账户美元估值和模拟持仓，包含读取时间及来源。
2. **计算衍生值**：两只ETF权重、近似纳指单日风险敞口。
3. **明确的假设情景**：指数单日 -10%、-5%、+5%、+10% 对上述已知风险敞口的简化敏感性，不赋予情景发生概率、不发出买卖指令。

此处借鉴 Public Equity Investing 的风险预算和情景设计方法，**不是插件被嵌入网站**，也不等于模型验证或投资建议。

## 数据质量

Alpaca 免费行情可能使用 IEX feed；IEX 是单一交易所，不代表全市场综合行情。若将来增加第二行情源核对，必须显式显示 `feed`、调整口径、行情日期、覆盖比例，不能把两个接口当成独立来源。

资料：

- [Alpaca Paper API](https://docs.alpaca.markets/us/reference/getallopenpositions)
- [官方 Python SDK](https://github.com/alpacahq/alpaca-py)
- [TQQQ 官方风险说明](https://www.proshares.com/our-etfs/leveraged-and-inverse/tqqq)

## 单独核对行情（不上线、不改策略）

有自己的模拟账户API Key，且已在本机保存真实价格历史时，可以执行：

```bash
investlab --home ~/.local/share/investlab alpaca-quote-check
```

工具会以 Alpaca **IEX 单交易所、日线、adjustment=all** 样本，和本机最近一个完整交易日的 QQQ/TQQQ 调整收盘价进行差异比较，并把报告保存在私有 `data/alpaca-quote-check.json`。这项读取不会覆盖原价格、生成买卖建议或改变投资信号。

- `CONTEXT_AGREEMENT`：两只ETF的观察值在1%背景比较容差内，但不等于官方收盘价已独立确认。
- `SOURCE_DISAGREEMENT`：至少一个差异超过1%，优先复核数据、交易日和复权口径。
- `INCOMPLETE`：该交易日缺少至少一个IEX观察值；不能声称已验证。

**限制**：IEX仅是单交易所，不是全市场SIP收盘行情；本地来源可能使用 Yahoo 历史复权价，不同供应商在企业行动调整和时点上可能不一致。1%为警示阈值，不应被当成实时交易的充分可靠性门槛。不同供应商在相同价格指标上的观测是补充证据，不是策略有效性验证。演示数据被明确拒绝进行真实行情核对。

参考：[Alpaca 市场数据说明](https://docs.alpaca.markets/us/docs/market-data-faq)。
