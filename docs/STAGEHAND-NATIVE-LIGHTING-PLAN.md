# Stagehand 原生灯光：首轮 M0–M1

2026-10-09，按用户提供的侧边计划执行。首轮限定咖啡馆、一盏参数已知的原生灯、当前角色，并必须在普通游戏模式验证。新增灯产生清晰变化只证明原生灯接入，不算地图既有光照改进完成。

r8 SH 实验保持关闭。r10 发布包及原安装备份保留，当前游戏继续使用已有 ReShade 环境以保留采集能力。本轮不换游戏 DLL、不再修改 SMSM shader。IPC 测试桥、GPU 数据关联、日常推荐和性能预算验收均在 M1 清晰可重复之后推进。

## M0 兼容性表

| 项目 | 固定测试值 | 当前证据 |
|---|---|---|
| 游戏 | `2026.09.15.0000.0000` / DX11 | 版本文件；灯 Create 签名在可执行代码段唯一匹配 |
| Dalamud | `15.0.3.6` / API 15 / .NET 10 | 本机 runtime/deps 与插件清单一致 |
| Stagehand | 官方 `0.5.5.0` | GitHub 发布资产 SHA256 匹配，源码标签提交 `48b6f54ac6e971bf26aefaa8e4a33846d7b9309d` |
| 灯光布局 | Scene.Light 0xB0 / Render.Light 0x130 | 本机 FFXIVClientStructs PE 元数据的关键偏移与源码相符；未执行 native 调用 |
| Stagehand 自有签名 | 加上灯 Create 共 14 条 | 当前客户端文件代码段均唯一匹配；不代替 live resolver 验收 |
| IPC | 上游 revision 1.2 | 固定版源码；本轮没有 IPC consumer，live 版本尚未调用查询 |
| Stage 格式 | 官方 Stagehand.Definitions 0.5.5 | 空舞台和禁用 point light 的官方序列化往返通过 |

`prepare_stagehand_m0.py` 固定资产并安全解包，`StagehandM1` 只做元数据与格式核对，`install_stagehand_m1.py` 在停机时备份并添加官方插件登记。模拟原配置保留、失败回退和运行中拒绝通过。不是自定义 Dalamud 插件或 IPC 桥。

已登记官方插件作为固定开发加载路径，专用目录只有空舞台，对象数为 0、无自动显示条件，资产悬停预览关闭。live 加载和实验灯尚未验证；离线核对通过不等于 M0 完成。

## 接口清单与清理

LightDefinition 已包含形状、颜色、强度、位置、范围、衰减和独立阴影开关。LiveLight 调用原生 `Scene.Light.Create`，更新 Render.Light 参数，并走 CleanupRender/Dtor 释放。

后续 M2 可直接使用 `TryCreateOrUpdateTemporaryStage` / WithTransform、`TrySetTemporaryStageVisible`、`TrySetTemporaryStageTransform`、`TryDestroyTemporaryStage`，定义字符串足以切换本轮参数。`GetLocation` / `LocationChanged` 支持场景归属和清理。当前只记录能力，暂不实现消费端。

| 对象 | 可取得内容 | 保留缺口 |
|---|---|---|
| Stagehand 新增灯 | 自己的 Stage ID、已知定义参数、显示/隐藏/销毁和变换 | 对应 GPU 数据与最终材质贡献未关联 |
| 地图原有灯 | 本轮不操作或枚举 | 稳定 ID、实际参数和 GPU 关联尚未取得；新增灯不能替代验收 |

静态入口没有发现 GPose 限制，普通模式仍须实测。位置变化源码先 DestroyAllLiveStages 并清空手动显示，临时 Stage 文档说明先隐藏。插件关闭会停止服务并 Dispose live Stage，Light 解除 framework 更新并释放对象。切图、禁用和退出无残余仍待实测。

依据：[灯光实现](https://github.com/universalconquistador/Stagehand/blob/0.5.5/Stagehand/Live/LiveLight.cs)、[创建入口](https://github.com/universalconquistador/Stagehand/blob/0.5.5/Stagehand/Live/LiveObjectService.cs)、[IPC](https://github.com/universalconquistador/Stagehand/blob/0.5.5/Stagehand.Api/IStagehandApi.Temporary.cs)、[位置清理](https://github.com/universalconquistador/Stagehand/blob/0.5.5/Stagehand/Services/LocalStageService.cs)。

## M1 最小场景

咖啡馆、当前角色、固定位置/镜头，先做普通游戏模式。仅一盏 Point light，无投影纹理，动态/角色/物件阴影均关闭。起始白色 `(1,1,1)`、强度 8、范围 10、quadratic factor 1。正式灯位在角色附近约 2–3 米，实际绝对坐标只记本地。

1. 输入 `/stagehand`，确认官方插件可打开；选 `SMSM M1 Native Single Light`。用 Open Editor 的 `+` 菜单添加且仅添加一盏 Point Light，关闭额外阴影后保存。0.5.5 的灯光添加入口以当前相机位置放置（此前把其他对象的玩家位置入口当作灯光入口，现更正），正式观察前核对灯位。
2. 固定角色和镜头，禁用/Hide 灯记录原画面；开启、关闭至少重复三次，观察恢复是否一致。
3. 从固定 ON 参数分别只改 Color、Position、Range；每次改下一项之前恢复固定 ON 状态。
4. 记录头发、裙装、皮肤、附近地面的响应。若不稳定或不符合预期，先排查 Stagehand 参数/兼容性，暂停 shader 修改。
5. 最后 Hide/销毁实验 Stage，核对原画面，再验证位置切换和关闭插件时清理。保持无自动加载条件。

首轮只用 Stagehand 自身 UI/Stage 文件和必要记录，没有自定义常驻控制器。保留 ReShade 能力，但不开展新的 GPU 数据关联。

## 响应与验收

| 对象/条件 | 开关可重复 | 颜色 | 位置 | 范围 | 关闭恢复 |
|---|---|---|---|---|---|
| 当前头发 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 当前裙装 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 皮肤 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 附近地面 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 普通模式创建/隐藏/销毁 | 待测 | — | — | — | 待测 |
| 切图/禁用/退出清理 | 待测 | — | — | — | 待测 |

M0 通过：普通模式一盏灯重复创建和清理，不残留。M1 通过：变化清晰、方向/范围符合预期、关闭后恢复。有异常即暂停 SMSM shader 工作，不凭计数或字段存在通过。

M2 薄桥只在 M1 通过后做临时 Stage 所有权、预设切换、有限采集协调和清理。M3 再追踪灯参数到缓冲区/纹理/材质，并过滤早期深度阶段。M4 只选择一个有证据的问题改进；若原生灯满足补光则侧重配置控制，原地图灯另验收。M5 再验普通模式/GPose、移动、场景、恢复和帧时间；1080p 单灯约 1 ms GPU 增量仅是初始预算。

当前：[M0 预检](validation/stagehand-m0-preflight-2026-10-09.json)。M0 live 与 M1 未通过，下一步是首次加载官方插件及普通模式单灯测试。

15:35（上海时间）日志确认官方 Stagehand 插件实例启动并完成加载，用户能打开窗口并点 Show。测试文件仍为 `Objects={}`，所以当前未创建灯，也不能据此判断灯光无效。下一步在官方 Editor 添加唯一 Point Light 并保存，之后才开始配置和受光测试。重复清理及 M1 仍未验收。
