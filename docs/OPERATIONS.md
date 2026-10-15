# 日常运行、迁移与恢复

## 推荐运行方式

在长期在线的Linux主机上装一个Python虚拟环境，数据放独立私有目录。若继续用原ChatGPT每日任务，保留其身份、原会话和频率；不要额外开启systemd定时器。

独立主机的可选配置见`deploy/investlab.service`和`investlab.timer`：周二至周六北京时间14:00运行。美股节假日不会产生新交易日；遇到同一行情日重跑不增加观察样本。模板路径与系统用户须按实际安装调整。

当前引擎交易日历包含常规美国股票假日和已知特殊停市；临时新停市需要更新日历，不能把供应商缺一行默认为节假日。18:30纽约时间之前不采纳当天日线，是收盘数据的保守发布时间缓冲，不是市场正式收盘时间。

## 每日顺序

1. `doctor`核对运行目录与账户。
2. 每个新行情日按需运行一次`refresh-macro`；数据失败不反复重试。
3. `run --online --independent-check --require-current`完成计算、存档、数据库回读和本地完整备份。
4. `audit`检查证据；`evaluate`更新已经到期的观察结果。
5. `summary`输出短通知。LOCAL_ONLY只是本地内容准备好，没有外部发送回执。

QQQ/TQQQ是必需行情，QLD和四个宏观因子不作为这两只ETF成功运行的共同门槛。来源冲突停止新配置；备用源失败单独显示，不称独立核对通过。

## 容器

```bash
docker compose -f deploy/compose.yaml run --rm monitor init --demo
docker compose -f deploy/compose.yaml run --rm monitor run
```

容器模板运行CLI，数据使用持久卷。只读看板默认监听127.0.0.1；当前模板不把容器看板公开暴露，不假装端口映射后就能访问。优先在主机运行`serve`，通过SSH本地端口转发访问。CI将实际构建镜像并用同一持久卷跨容器运行演示、独立复核与审计；本地环境无Docker，实际成功结果以远端container job为准。

## 备份与恢复演练

```bash
investlab --home /private/investlab backup --output /private/backup-2026-10-15.zip
investlab --home /private/investlab restore /private/backup-2026-10-15.zip --to /private/restore-check
investlab --home /private/restore-check audit
investlab --home /private/restore-check doctor
```

备份使用SQLite原生backup，而不是只拷贝可能仍在WAL里的主文件。包括研究证据、版本、账户流水及清单。恢复拒绝绝对路径、目录穿越、符号链接、重名条目和哈希不符；完整状态在临时目录验完后才原子切换，验证失败不留下半套目标目录。

新运行的backup在operation被标记成功之前产生，因此恢复后最后一次operation可能是PERSISTED：这表示计算已保存但成功回执尚未写入。不能据此冒充那次外部通知已送达。恢复后先audit，再生成一轮新报告。失败/中断记录保留。

保留至少一份异机备份；本项目默认不擅自删除历史研究、流水或旧报告。可以人工定期清理已确认异机保存的过期备份，不能删除模型快照后仍宣称历史可重放。

## 升级

升级前做完整备份。在新目录安装新代码，以原数据副本跑audit和verify；比较相同数据上的结果。代码变化导致模型源码哈希变化是正常版本事实，不能把旧研究标记成新代码的前瞻成绩。旧文件仍由固定主文件身份保存；更新时用真实当前版本防止覆盖其他任务新增记录。

## 故障定位

| 现象 | 查看 |
|---|---|
| 在线命令非零退出 | 供应商证据metadata、operation详情、行情截止日 |
| 报告存在但保存未完成 | operation是否FAILED/PERSISTED；DB中run_id是否存在；备份是否核验 |
| 重复日报仍建议同一步 | 最后确认估值是否真的更新；这是预期的未成交保护 |
| 宏观模型DATA_LIMITED | 四个CSV的日期与缺失，ETF模型可继续 |
| 两个Yahoo地址都成功 | 仍是同一供应商，不升级为独立验证 |
| 图表收益与账户不同 | 前者美元假设回测，后者真实现金流；不能直接混合 |

## 私有状态包与公开源码

GitHub保存工作源码；私有主文件保存运行账本和证据，SOURCE.json固定仓库URL与完整提交。每轮先校验状态包manifest，再从该提交取回源码并安装，不能用浮动main悄悄替换已冻结版本。保存后续状态使用：

```bash
python investlab/scripts/package_private.py --home ./runtime --output NEW_PRIVATE.zip --repository https://github.com/wanghaibing07/investlab-monitor --revision FULL_VERIFIED_COMMIT_SHA
```

个人状态包不上传GitHub；研究快照中的历史源码是证据，不是另一份工作树。
