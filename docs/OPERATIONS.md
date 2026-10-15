# 运行、迁移与恢复

## 安装与调度

在长期在线的Linux主机上使用Python虚拟环境，将运行数据放在独立私有目录。选择一套调度器执行每日更新，例如systemd或已有任务服务。

可选配置见`deploy/investlab.service`和`deploy/investlab.timer`，模板时间为周二至周六北京时间14:00。按实际主机调整路径、系统用户和运行时间。成功运行的观察天数按不同交易日统计。

交易日历包含常规美股假日和已知特殊停市；新增临时停市须更新日历，供应商缺失行情应单独排查。程序在纽约时间18:30后接纳当日日线，为供应商发布完整收盘数据预留时间；市场正式收盘时间与此处理时间分别记录。

## 每日更新

1. `doctor`检查运行目录与账户。
2. 每个新行情日按需执行一次`refresh-macro`；失败时检查数据源状态。
3. `run --online --independent-check --require-current`计算、保存报告，并核对数据库记录和完整备份。
4. `audit`检查数据与计算记录；`evaluate`评估预测周期已结束的结果。
5. `summary`输出短摘要。`LOCAL_ONLY`表示摘要已在本地生成，外部发送状态由通知服务记录。

QQQ/TQQQ为必需行情。QLD和四个宏观因子独立处理。价格来源有冲突时先核对行情，再生成新建议；备用源的核对结果单独显示。

## 容器

```bash
docker compose -f deploy/compose.yaml run --rm monitor init --demo
docker compose -f deploy/compose.yaml run --rm monitor run
```

以上命令使用模拟数据。容器模板运行命令行程序，运行数据保存在持久卷中。网页看板适合在主机上通过`serve`启动，默认监听`127.0.0.1`；远程访问使用SSH本地端口转发。

GitHub CI使用固定镜像摘要构建容器，在同一持久卷上完成跨容器运行、数值复核与审计。结果可在仓库Actions中查看。

## 备份与恢复

```bash
investlab --home /private/investlab backup --output /private/backup.zip
investlab --home /private/investlab restore /private/backup.zip --to /private/restore-check
investlab --home /private/restore-check audit
investlab --home /private/restore-check doctor
```

备份使用SQLite原生backup接口，包含研究输入、版本、账户流水和文件校验清单。恢复时检查文件路径、符号链接、重复条目及哈希，在临时目录验证完整状态后，再原子切换到空目标目录。

运行过程中的备份可能保留`PERSISTED`状态，表示计算结果已保存，完成回执尚待写入。恢复后先执行`audit`，再生成一份新报告。历史失败和中断记录继续保留，方便定位问题。

保留至少一份异机备份。需要重现历史计算时，同时保留对应的模型源码与数据快照；旧备份可在确认异机副本完整后按保留策略清理。

## 升级

升级前创建完整备份。在新目录安装新代码，使用数据副本执行`audit`和`verify`，比较相同行情下的结果。

每个代码版本分别记录历史研究和后续运行结果。保存到具备版本管理的存储时，核对当前版本；存在其他任务的新记录时，读取最新数据再合并保存。

## 故障定位

| 现象 | 检查内容 |
| --- | --- |
| 在线命令非零退出 | 供应商响应信息、运行详情、行情截止日 |
| 报告存在但保存未完成 | `operation`是否为`FAILED`或`PERSISTED`，数据库中的`run_id`，备份检查结果 |
| 多份日报给出相同建议 | 最近确认估值；相同持仓通常得到相同的下一步建议 |
| 宏观模型显示`DATA_LIMITED` | 四组宏观CSV的日期和缺失项，ETF模型可继续运行 |
| 两个Yahoo地址均成功 | 两个接口属于同一供应商，独立数据源核对结果另列 |
| 策略图表与账户收益不同 | 图表为美元历史模拟，账户收益按实际交易、资金流与汇率计算 |

## 私有运行归档

源码保存在GitHub；私有运行归档保存账户、报告和研究输入。`SOURCE.json`记录仓库地址及完整提交编号。恢复时先检查文件清单，再安装对应提交的代码，以重现原版本计算。

在包含`investlab/`源码目录和`runtime/`数据目录的工作目录中打包：

```bash
python investlab/scripts/package_private.py --home ./runtime --output NEW_PRIVATE.zip --repository https://github.com/wanghaibing07/investlab-monitor --revision FULL_VERIFIED_COMMIT_SHA
```

将`FULL_VERIFIED_COMMIT_SHA`替换为已核对的完整提交编号。生成的归档存放在私有存储中；其中的历史源码快照用于重现研究，日常开发使用GitHub源码。
