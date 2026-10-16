# InvestLab Cloud / Vercel（独立私有部署）

云端版本与公开 [InvestLab 演示](https://investlab-monitor.vercel.app/) 是**两个项目**。公开站永远只有虚构数据，云端真实账户单独通过 Vercel Authentication 保护。

## 运行架构

- Vercel Python Functions / FastAPI：执行现有 `investlab.service.run`、审计、独立验证、已到期结果评价
- Vercel 私有 Blob：把真实账户 SQLite 以**一致性备份**打包成不可覆写版本，保存完整快照；运行报告同样只写入私有不可覆写对象
- Vercel Cron Jobs：在完成真实账户初始化、Cron 密钥及首次计算验收后启用，避免未配置时产生假的「每天运行成功」
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

## 当前边界

此路径面向**单账户、单写入者**初始阶段。私有 Blob 是版本化文件存储，**不是关系数据库事务引擎**。即使能保存 SQLite 备份，也不能在重叠的 Cron/手工写入时保证全局串行。实际连续运行前必须引入数据库事务锁（如 Vercel Marketplace Postgres）或经验证的互斥方案。禁止把真实账户数据写入静态构建、公开 Blob 或 GitHub。

数据的性质：
- `GET /health`：非敏感运行检查
- `GET /api/status`：读取最近一条私有报告；不存在时明确 `SETUP_REQUIRED`
- `POST /api/initialize`：首次保存用户确认的人民币估值；需登录 Vercel 私有项目，且请求必须同源 HTTPS JSON
- `GET /api/cron/daily`：必须提供 Vercel Cron Bearer Secret；它严格要求非演示账户、在线行情通过及独立验证

若未设置真实账户，账号管理网页允许登录后初始化；未登录的访客由 Vercel Authentication 拦截。云端不会通过 ChatGPT Alpaca 插件复用你的登录权限，也不会执行任何真实/模拟交易。

## 长期账户管理：一次登录，重复更新持仓估值

完成 Vercel 身份登录后，打开 `https://investlab-cloud.vercel.app/setup`。网页首先只读检查 `/api/status`；仅当私有 Blob 检查确认 `SETUP_REQUIRED` 且 `storage_verified:true` 时允许提交一次性初始化。

填写经过账户持有人确认的日期、QQQ/TQQQ/QLD/现金人民币整数估值和来源说明，点击「创建并保存账户」。无需填写任何管理令牌：**浏览器内登录已开启的 Vercel Authentication 才能访问页面和写入接口**，服务端还检查请求来源与 JSON 类型，阻止跨站提交。

第一次初始化只写入真实账户快照。再次进入 `/setup` 会从私有 Blob 读取已经保存的估值和当前版本，允许修改日期、四项人民币金额和备注，再通过 `POST /api/valuation` 创建**新版本的不可覆盖快照**；历史记录仍在。旧页面发出的过期版本更新会返回 409 冲突，提示先重新读取。注意：Blob 不是有事务锁的数据库，**不要同时在多个浏览器或定时任务写入**；当前未启用 Cron，正式允许并发前需要数据库事务锁。

后端保存私有 Blob 后，重新下载 ZIP 快照、校验 SHA256 和 SQLite，并逐项核对账户金额、估值日期和合计；页面还会独立读取 `GET /api/account`，两次核实后才提示持久化成功。出现错误时先刷新查询账户，避免重复提交。更新估值不会自动生成股票成交或发出交易指令。

**部署访问权限很重要**：Vercel Authentication 所授权的任何项目访问者（包括你主动授予 Viewer 的成员或分享部署链接的持有者）都可能打开这个私人后台。去掉第二个管理令牌后，**必须将该项目的部署访问权限制为你自己**，不要创建分享链接或自动化绕过密钥；定期审计 `Security → Deployment Protection` 的访问成员、共享链接与绕过设置。项目需一直保持 `ssoProtection.deploymentType: all`。关闭项目登录保护会让修改接口缺少身份验证，不得关闭。后端校验请求来源不能替代真正的身份认证。



## 部署与验收

1. 创建独立 Vercel 私有项目并开启 Vercel Authentication。
2. 连接私有 Blob 存储（不能是 public）。
3. 仅保留系统内部的 `CRON_SECRET`（未来 Cron 使用），以及私有 Blob 连接凭据；账户页面不再使用 `INVESTLAB_ADMIN_TOKEN`。
4. 将打包分支 `vercel-cloud` 部署到私有项目，并验证匿名访问被 Vercel 拦截。
5. 首次账户录入只需私有 Vercel 身份登录；保存后验证 Blob 私有版本，日后仍可新增估值快照。
6. 首次执行通过并核对数据库恢复、报告与数据质量，再开启 `crons` 调度。
7. 真实连续交易日的 Cron 送达、失败告警、重试和外部价格核对仍需实测。

> 当前模块提供可复用的 Python 云端状态备份与运行功能；实际开通步骤与运行状态必须按部署日志验收。
