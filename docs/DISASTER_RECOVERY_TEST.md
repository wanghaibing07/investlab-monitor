# 恢复验证与保留策略

当前打包脚本通过一个SQLite原生backup生成一致性主包；它不把home/backups下所有历史恢复点自动打包。主包可解压不等于多个时间点能恢复。

研究输出独立记录恢复来源、实际文件SHA、SOURCE提交、manifest、SQLite完整性/外键、账户与历史行指纹、最新操作及审计退出码。两个空目录解压同一包不能算两个时间点。旧版必须从真实独立历史来源取回，不重造旧账本。

Google Drive默认二进制旧修订可能清理；官方当前文档说明通常30日，也可能因未固定修订数量更早清理；keepForever最多200份且占空间。旧二进制下载需keepForever。设置keepForever或另存私有恢复点依实施书需要额外授权，本轮不静默设置。

当前连接器能列修订，但fetch_file_revision拒绝ZIP。Library已暴露接口可固定file_id取回已知版本，未暴露列出历史file_id的只读动作；不能用restore_version把主文件回退来获取旧版本。

旧时间点恢复失败时必须标阻断，不以新建备份冒充旧历史。生产发布须重读最新主版本、保护预期版本，保存同一身份，再镜像双端重取核验。

官方：https://developers.google.com/workspace/drive/api/guides/manage-revisions
