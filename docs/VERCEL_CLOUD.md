# InvestLab Cloud / Vercel（独立私有部署）

云端版本与公开 [InvestLab 演示](https://investlab-monitor.vercel.app/) 是**两个项目**。公开站永远只有虚构数据，云端真实账户单独通过 Vercel Authentication 保护。

## 运行架构

- Vercel Python Functions / FastAPI：执行现有 `investlab.service.run`、审计、独立验证、已到期结果评价
- Vercel 私有 Blob：把真实账户 SQLite 以**一致性备份**打包成不可覆写版本，保存完整快照；运行报告同样只写入私有不可覆写对象
- Vercel Cron Jobs：支持按美股交易日自动计算与延迟补跑；需要有效的 `CRON_SECRET` 和 `INVESTLAB_CRON_ENABLED=true`，实际成功与否以最新运行回执为准
- Vercel Authentication：所有网站路径默认要求 Vercel 身份登录；账户创建和更新仅使用 Vercel 私有项目登录，无第二个管理令牌

## 真实账户状态的判定

`/health` 的 `storage_connected: true` **只表示已经加载 Blob 凭据**，不是数据读写已经验收；新增的 `storage_credentials_only: true` 明确标识这一点。

打开登录保护下的 `/api/status` 可以检查真正的账户状态：

- `SETUP_REQUIRED`、`account_initialized: false`、`storage_verified: true`：已成功查询私有 Blob，目前未找到已确认的账户快照，也没有日报
- `READY_FOR_FIRST_RUN`、`account_initialized: true`：从私有 Blob 下载并校验了 SQLite 快照，已找到确认账户，但尚未产生日报
- 有 `latest_run_exists: true`：存在独立的日报，仍需查看该报告自身是否 `SUCCEEDED`，不能仅凭账户存在认定正常运行
- `STORAGE_ERROR`（503）：列表、下载、完整性或账户验证失败。不能把存储故障说成“账户没有初始化”
- `STATE_INCONSISTENT`（503）：发现历史日报，但当前缺少有效的确认账户，需要人工修复

这次状态检查只读取数据，不新增账户、不执行策略、不发送邮件。验证当前私有存储为空不等于“私有存储写入已验证”；首次保存确认账户后，需重新访问此接口检查持久化结果。

## 日常使用：打开投资看板，而不是接口 JSON

**入口：**[InvestLab 私人投资工作台](https://investlab-cloud.vercel.app/)。

- **资产总览：** 当前的人民币总额、QQQ/TQQQ/QLD/现金比例、已确认估值日期和监控可信度。
- **投资组合：** 每种资产估值与占比、每次保存的历史估值记录。
- **策略与风险：** 当前权重与冻结策略目标 QQQ 60% / TQQQ 40% 的对照；风险指标只有在独立行情验证通过时显示。
- **运行报告：** 查看最近一次成功、失败或未运行的真实状态，账户确认后可手动发起一次**只做计算、不交易**的在线监控。
- **账户与设置：** 从私有 Blob 下载最近账户版本，持续更新估值；每次新快照都不可覆盖，旧版本冲突会拒绝写入。

`GET /api/status`、`GET /api/account`、`GET /api/history`、`GET /api/latest` 等 JSON 接口专供程序使用。人类用户日常不应直接访问这些 JSON 页面。

**真实性规则：** 账户金额来自持有人确认的基线，不是股票股数；资产曲线只使用至少两个不同日期的真实估值，并标记“不是收益率”；行情、波动率和风险贡献必须来自审核通过的在线报告；缺失时清楚显示空状态，绝不虚构收益率、市场数据或交易信号。

**体验与实现：** 独立的 HTML/CSS/JavaScript 资产通过同一个受保护的 FastAPI 项目提供，不连接第三方字体或脚本 CDN。支持桌面和移动端、键盘输入、语义化表格、提示及错误状态。所有私有数据在登录后动态读取，网页构建文件不含真实账户金额。

**手动运行：** 点击“运行一次监控”，阅读说明确认后同源 HTTPS POST `/api/run`，携带最新已确认的快照版本。服务端会验证该版本仍为最新，再执行在线行情校验、账本审计和研究校验。计算期间账户版本变化则拒绝保存计算出的新账户版本。结果不合格或请求失败不会显示为成功。这个基于 Blob 的版本检查**不是分布式事务锁**。自动 Cron 研究使用独立计算快照，不直接覆盖人工确认的账户；多个手动账户更新之间仍需避免并发写入。

## 决策简报：校验通过 ≠ 立刻交易

人类用户从 `/` 进入「今日决策简报」，不要把 `/api/status` 的 `SUCCEEDED` 或 `PASS` 当成买卖意见。专门的私有只读接口 `GET /api/brief` 综合三份已核实数据：

1. 当前私有账户的人民币持仓快照，含估值日期和 QQQ/TQQQ/QLD/现金金额；
2. 最近一次存入 Blob 的执行收据，要求在线行情合格、账本审计和研究验证均通过；
3. 完整持久化的 `service.latest` 模型报告，检查当次行情是否仍是最新完整交易日、运行是否已经成功结束、配置研究是否有效、与当前账户的全部金额及日期是否完全相同。

满足所有条件时，简报显示「模型复核标题 → 为什么 → 你下一步怎么处理 → QQQ/TQQQ 当前权重与**本步**参考权重 → 条件与风险说明」。权重源自项目 `advisory.observe` 的 `actions` 和 `next_review_weights`，不能用最终目标 60/40 冒充本步配置；全体权重合计应为 100%，操作方向必须和权重变化一致。文案始终使用「评估增加 / 评估减少 / 维持」，不输出可执行股数、不发送订单。

在技术检查通过但账户估值变化、行情过期、最新运行失败、模型意见缺失时，状态分别是 `ACCOUNT_MISMATCH` / `MARKET_STALE` / `LAST_RUN_FAILED` / `MODEL_BLOCKED` 等，**明确隐藏**本步权重与买卖意见，建议先补齐证据。页面还显示行情交易日、账户估值日、报告生成时间与操作适用状态。因账户持有人确认日可能晚于美股最新收盘日，日期不相同时必须再核对报价和资金情况。

**设计与代码审查来源**：参考 GitHub 上的 Anthropic [Frontend Design](https://github.com/anthropics/skills/tree/main/skills/frontend-design)、[UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) 及 Vercel [Web Interface Guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines)。采用纸白/深绿的研究简报层级；将首屏注意力用于「判断、依据、人工下一步」，资产卡片和分析图退居其后。导航、空状态、移动适配、对话框、键盘焦点与错误提示必须保持可用。

## 当前边界

此路径面向单账户私有管理。私有 Blob 保存版本化文件，**不是关系数据库事务引擎**；定时研究与手动估值写入分离，降低了互相覆盖的风险，但多个手动账户更新仍没有完整的跨请求事务锁。若需要多人同时修改账户，应采用经过验证的事务型存储方案。真实账户数据不得写入静态构建、公开 Blob 或 GitHub。

数据的性质：
- `GET /health`：非敏感运行检查
- `GET /api/status`：读取最近一条私有报告；不存在时明确 `SETUP_REQUIRED`
- `POST /api/initialize`：首次保存用户确认的人民币估值；需登录 Vercel 私有项目，且请求必须同源 HTTPS JSON
- `GET /api/cron/daily`：必须提供 Vercel Cron Bearer Secret；它严格要求非演示账户、在线行情通过及独立验证

若未设置真实账户，账号管理网页允许登录后初始化；未登录的访客由 Vercel Authentication 拦截。云端不会通过 ChatGPT Alpaca 插件复用你的登录权限，也不会执行任何真实/模拟交易。

## 长期账户管理：一次登录，重复更新持仓估值

完成 Vercel 身份登录后，打开 `https://investlab-cloud.vercel.app/setup`。网页首先只读检查 `/api/status`；仅当私有 Blob 检查确认 `SETUP_REQUIRED` 且 `storage_verified:true` 时允许提交一次性初始化。

填写经过账户持有人确认的日期、QQQ/TQQQ/QLD/现金人民币整数估值和来源说明，点击「创建并保存账户」。无需填写任何管理令牌：**浏览器内登录已开启的 Vercel Authentication 才能访问页面和写入接口**，服务端还检查请求来源与 JSON 类型，阻止跨站提交。

第一次初始化只写入真实账户快照。再次进入 `/setup` 会从私有 Blob 读取已经保存的估值和当前版本，允许修改日期、四项人民币金额和备注，再通过 `POST /api/valuation` 创建**新版本的不可覆盖快照**；历史记录仍在。旧页面发出的过期版本更新会返回 409 冲突，提示先重新读取。注意：Blob 不是带事务锁的数据库，**不要同时在多个浏览器中提交账户修改**。定时 Cron 仅读取已确认的账户版本、另存计算快照，不直接覆盖人工估值；仍应以运行回执检查数据一致性。

后端保存私有 Blob 后，重新下载 ZIP 快照、校验 SHA256 和 SQLite，并逐项核对账户金额、估值日期和合计；页面还会独立读取 `GET /api/account`，两次核实后才提示持久化成功。出现错误时先刷新查询账户，避免重复提交。更新估值不会自动生成股票成交或发出交易指令。

**部署访问权限很重要**：Vercel Authentication 所授权的任何项目访问者（包括你主动授予 Viewer 的成员或分享部署链接的持有者）都可能打开这个私人后台。去掉第二个管理令牌后，**必须将该项目的部署访问权限制为你自己**，不要创建分享链接或自动化绕过密钥；定期审计 `Security → Deployment Protection` 的访问成员、共享链接与绕过设置。项目需一直保持 `ssoProtection.deploymentType: all`。关闭项目登录保护会让修改接口缺少身份验证，不得关闭。后端校验请求来源不能替代真正的身份认证。



进一步阅读：[Vercel 每日自动监控（调度、补跑与邮件）](VERCEL_DAILY_AUTOMATION.md) 和 [生产可靠性验收标准](CLOUD_RELIABILITY_ACCEPTANCE.md)。

## 部署与验收

1. 创建独立 Vercel 私有项目并开启 Vercel Authentication。
2. 连接私有 Blob 存储（不能是 public）。
3. 仅保留系统内部的 `CRON_SECRET`（未来 Cron 使用），以及私有 Blob 连接凭据；账户页面不再使用 `INVESTLAB_ADMIN_TOKEN`。
4. 将打包分支 `vercel-cloud` 部署到私有项目，并验证匿名访问被 Vercel 拦截。
5. 首次账户录入只需私有 Vercel 身份登录；保存后验证 Blob 私有版本，日后仍可新增估值快照。
6. 当前代码已经声明每日计算和延迟补跑两条 Cron 规则；生产部署需设置 `INVESTLAB_CRON_ENABLED=true`，并通过真实运行回执核对是否成功触发。
7. Cron 规则注册、代码上线与长期真实运行是不同验收环节；持续交易日运行、失败通知送达及独立灾备要分别记录证据，不能从部署 READY 推导出成功。

> 当前模块提供可复用的 Python 云端状态备份与运行功能；实际开通步骤与运行状态必须按部署日志验收。
