# r10 — 可选效果与可恢复安装管理

发布基线：2026-10-08，国际服客户端 `2026.09.15.0000.0000`。

本版本冻结既有 `preview-2026.09.15-r10-managed`，默认 daily 只开启固定 50% SMSM 色调，保留游戏原生 Bloom 和景深。反射、阴影、抖动与径向模糊保留为独立可选实验；自定义灯、遮挡及 ReShade 迁移研究不进入此日常包。

管理器支持旧凭据升级、逐项选择/隔离、版本与文件摘要检查、备份、回退及中断恢复。用户已反馈色调 F10 关闭/恢复、传送、室内外及短战斗没有异常；未提供长期稳定性或帧时间数据，其他实验不视为验收完成。本版本标记为预发布。

下载 ZIP 后解压到独立目录，不将整个压缩包直接复制到游戏。需要 Python 3.10+；游戏退出后在管理员 PowerShell 中使用解压目录的管理器：

```powershell
python '<解压目录>\tools\manage_preview.py' install --client-root '<含 game 的客户端根目录>' --package '<解压目录>\package'
python '<解压目录>\tools\manage_preview.py' status --client-root '<客户端根目录>'
```

保留解压目录，管理器从不可变源包读取文件。备份位置由每次操作输出；回退及独立效果选择见 [MANAGEMENT.md](MANAGEMENT.md)。ZIP 附带 SHA256SUMS.json，发布附件另含整包 SHA-256。旧包和实验资料继续保留。

用户本次明确授权同步 Git、发布 r10、创建新开发分支并提交，覆盖历史文档中的“不推送发布”限制。新主线见 [NATIVE-LIGHTING-PLAN.md](NATIVE-LIGHTING-PLAN.md)；r10 不包含尚未完成的迁移效果。
