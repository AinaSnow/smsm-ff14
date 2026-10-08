# 诊断 r2：补齐 BGRA8 原始读回

2026-10-08。本候选只补齐首轮实机确认的 DXGI 87 法线格式缺口，并提供停机更新命令。保持固定 ReShade 6.8.0 / API 20、默认关闭、每条目标最多一个绘制、256 MiB 原始预算；不替换游戏 shader，不改光照。

插件 SHA-256：`35ce17db352c3937620e3d191b08f3f10967fbd757d6b0a3be9d7a08e7c0c6f5`。r1 的 `02af645f…` 包和旧采集保持不变。

新增 BGRA8 UNORM / TYPELESS / sRGB 的四字节布局支持，保存原始 B/G/R/A 位，不转换或交换文件通道；视图和资源格式各自记录。WARP 用真实 BGRA8 纹理、非对齐行宽、已知四通道图案实际绘制，独立验证 raw 行去 padding、原始字节和 shader 的逻辑 RGBA 输出。新增实机格式 87 已通过这个离线测试；其他两个布局只采用同等存储字节规则，不宣称各自完成游戏验证。

验证通过：9 份 WARP 捕获报告及全部 payload；两个独立构建逐字节相同；官方完整 ReShade 硬件零顶点 host 的回调/两目标/更新常量检查；模拟 r1→r2 升级、升级中断恢复、配置及运行库保留、r10 精确恢复和保护检查。见 [r2 验证摘要](validation/native-diagnostic-r2-2026-10-08.json)。

游戏退出后在管理员终端更新，现有 ReShade 运行库保持原样；无需先卸载，也不删除 ReShade.ini、preset、日志或抓帧：

```powershell
python tools/native_environment.py update --game '<客户端根目录>\game' --package '<r2 诊断包目录>'
```

更新仅变更已登记 add-on 和凭据，验证客户端版本、旧包完整性、新候选默认状态及固定运行库摘要。运行中的游戏阻止更新；失败留下恢复事务，可以用 `native_environment.py recover` 恢复旧候选。当前设置与原 r10 备份继续保留。

受保护的客户端需先初始化可写诊断目录。命令工具现在优先在该目录生成临时请求，再同卷原子发布，保留游戏用户可删除的文件权限；已有请求不能覆盖。当前本机输出目录已在首轮初始化，game 目录 ACL 仍保持原样。

r2 已于 22:44（上海时间）在用户确认游戏退出后安装，文件摘要核对通过；运行库与用户配置保持原样，r1 升级前备份及原 r10 备份均保留。本机部署检查点为本地 `artifacts/native-deployment/r2-deployment.json`。

r2 的游戏验收尚未完成，下一次只采一个有效目标快照验证 BGRA8 是否正确读回，不重复上一轮所有场景。更完整的原生光照语义判断见 [本轮审计](NATIVE-LIGHTING-AUDIT.md)。
