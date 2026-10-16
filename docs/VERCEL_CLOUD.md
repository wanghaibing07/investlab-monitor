# InvestLab Cloud / Vercel（独立私有部署）

云端版本与公开 [InvestLab 演示](https://investlab-monitor.vercel.app/) 是**两个项目**。公开站永远只有虚构数据，云端真实账户单独通过 Vercel Authentication 保护。

## 运行架构

- Vercel Python Functions / FastAPI：执行现有 `investlab.service.run`、审计、独立验证、已到期结果评价
- Vercel 私有 Blob：把真实账户 SQLite 以**一致性备份**打包成不可覆写版本，保存完整快照；运行报告同样只写入私有不可覆写对象
- Vercel Cron Jobs：在完成真实账户初始化、Cron 密钥及首次计算验收后启用，避免未配置时产生假的「每天运行成功」
- Vercel Authentication：所有网站路径默认要求 Vercel 身份登录；账户创建另外需要管理密钥

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
- `POST /api/initialize`：一次性录入用户确认的人民币估值；必须额外提供管理令牌
- `GET /api/cron/daily`：必须提供 Vercel Cron Bearer Secret；它严格要求非演示账户、在线行情通过及独立验证

未设置真实账户或管理密钥时，不开放账户输入。云端不会通过 ChatGPT Alpaca 插件复用你的登录权限，也不会执行任何真实/模拟交易。

## 首次初始化：受保护网页

完成 Vercel 身份登录后，打开 `https://investlab-cloud.vercel.app/setup`。网页首先只读检查 `/api/status`；仅当私有 Blob 检查确认 `SETUP_REQUIRED` 且 `storage_verified:true` 时允许提交一次性初始化。

填写经过账户持有人确认的日期、QQQ/TQQQ/QLD/现金人民币整数估值和来源说明，在密码栏输入 Vercel Production 环境中的 `INVESTLAB_ADMIN_TOKEN`。**管理令牌不能通过聊天、GitHub、URL 参数或公开表单传递**。网页不会把令牌写入浏览器存储；只经同源 HTTPS POST 提交给后端。

服务器保存新版本的私有 Blob 后，立即下载并重新校验快照 ZIP 的 SHA256 与 SQLite 基线，逐项比较日期、各项金额和合计。只有回读完全匹配，才返回 `INITIALIZED` + `readback.verified:true`。浏览器还会独立重新请求 `/api/status`；两重检查通过才提示“持久化验证成功”。失败或网络中断后先查 `/api/status`，不要重复提交。已存在账户时禁止覆盖。

**注意**：登录保护和管理令牌属于两个独立的权限控制；网页不读取或显示既有管理密钥。管理令牌不可访问时由账户所有人在 Vercel 环境设置中安全轮换，且需要使变更作用于新部署。初始化仅保存账户估值，绝不生成交易或启用 Cron。

## 部署与验收

1. 创建独立 Vercel 私有项目并开启 Vercel Authentication。
2. 连接私有 Blob 存储（不能是 public）。
3. 设置生产环境 `CRON_SECRET` 和 `INVESTLAB_ADMIN_TOKEN`；值从安全随机源生成，不上传仓库。
4. 将打包分支 `vercel-cloud` 部署到私有项目，并验证匿名访问被 Vercel 拦截。
5. 首次账户录入需要私有身份登录以及管理令牌；保存后验证 Blob 私有版本。
6. 首次执行通过并核对数据库恢复、报告与数据质量，再开启 `crons` 调度。
7. 真实连续交易日的 Cron 送达、失败告警、重试和外部价格核对仍需实测。

> 当前模块提供可复用的 Python 云端状态备份与运行功能；实际开通步骤与运行状态必须按部署日志验收。
