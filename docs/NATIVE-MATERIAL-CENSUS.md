# r7：原材质变体统计与定点取样

r6 已证明前四次旧 hair 目标绘制不改变 RGB。下一步不再扩大该单变体的环境光实验，而是寻找实际有输出贡献的材质路径。

## 身份范围

`ShaderAudit --material-roster` 从当前客户端按名称读取六份 ShPk，逐项核对包索引、版本、提取偏移、DXBC 字节及 SHA，生成供构建使用的身份表。只把标识编入插件，不编入这些包的游戏字节码。

| 材质包 | 已核对的唯一 PS 数 |
|---|---:|
| hair | 200 |
| skin | 384 |
| character | 1,038 |
| characterlegacy | 1,740 |
| characterglass | 38 |
| characterstockings | 28 |

合并后为 3,399 个唯一 PS，13 个身份被多个包共享，报告保留全部来源名称，不把共享程序强行归为单一材质。包身份不等于当前玩家对象；皮肤、衣物、头发覆盖必须结合后续绘制证据。

## 两个默认关闭的只读模式

`census` 只统计下一个帧中的已知材质绘制，最多记录 512 条状态和独立 occlusion query；不替换 PS、不标紫、不复制每次绘制的颜色，只保留 Present 入口的一份 backbuffer。报告给出原 PS/VS 身份、材质来源、输出槽/格式、混合/深度状态、绘制数与 query samples。超过上限仍统计观察总数，并明确保留记录被截断的事实。

`sample <hash> <skip>` 仍使用原 PS，只对选定的精确身份采集一个帧。可以跳过该 shader 的前 N 次绘制，再保留前四次 RTV0 的前/后/帧末原始颜色；每次最高 256 MiB，并沿用 r6 的状态恢复与 GPU 完成检查。这样可以针对 census 中较有意义的绘制取样，不必总采屏外的第一个对象。

统计、取样期间原环境光实验和覆盖标记都关闭。原始 draw 在 hook 内执行一次，原 PS 和绘制参数不变；成功执行标记在回调内部设置，避免后续审计异常导致重复绘制。报告里的兼容字段 `replacement_executed` 表示 draw 已通过 hook 执行，**只有 `shader_replaced` 才表示是否换了 PS**，两个只读模式中该值为 false。

`summarize_native_materials.py` 按 PS 合并统计，并以 query 和写入状态提出定点取样候选。它不宣布颜色输出成功。多输出槽可能写的是 G-buffer 数据而非最终颜色；跨帧的 skip 也只是选取提示，不能保证对象顺序固定。最终必须用 sample 的前后颜色变化和空间对应判断，不能再次只看计数。

## 已验证与下一步

官方 ReShade 硬件 host 使用真实三顶点和原游戏 PS，验证 census 身份记录、sample 前/后/帧末取样及 skip 边界。三个模式均保留原画面，marker 绘制计数为零。安装测试验证 r6→r7、事务中断恢复、配置/runtime 保留、旧候选的能力拒绝、严格 shader hash/skip 参数和待处理命令不被覆盖。摘要见 [r7 验证](validation/native-material-r7-2026-10-09.json)。

下一次用户只需重新进入固定场景并站定。助手先采 census，根据输出布局和查询挑选少量变体，再自动逐帧 sample；不要求用户寻找紫色或反复截图。实际角色归属和画质收益尚未验收，不据此启用新光照效果。

```powershell
dotnet run --project tools/ShaderAudit -c Release -- --material-roster '<client 根目录>' artifacts/client-2026.09.15 '<新的 roster.json>'
python tools/request_native_ambient.py '<game 目录>' census
python tools/summarize_native_materials.py '<本轮目录>' --output '<新的候选摘要.json>'
python tools/request_native_ambient.py '<game 目录>' sample --shader '<已核对的 16 位 hash>' --skip 0
python tools/analyze_native_output.py '<取样目录>' --output '<新的分析.json>'
```

所有 raw 资源和 backbuffer 留在本地。原 r6/r5/r4/r10 备份和不可变候选继续保留；更新需停机，不修改运行中的 DLL。

2026-10-09 03:39（上海时间），用户确认退出后已安装 r7，插件/身份表能力凭据核对通过；r6 备份、runtime 和用户配置保留。等待下一次进入固定场景后的自动 census 与少量 sample，所有效果默认关闭。

## 首次实机：当前玩家头发和裙装路径取得

census 共观察到 2,008 次相关材质绘制；前 512 条全部没有 RTV，记录被早期深度阶段占满。它不能列全后续颜色变体，也不代表这些包没有颜色输出。本轮不要求再次安装插件，而是从已有完整帧日志筛出按客户端核验过的颜色路径，再以 r7 的 sample 验证当前帧。

| 精确 PS | 包 | 当前帧证据 | 空间对应 |
|---|---|---|---|
| `1c5c89ac035f9a44` | hair | 该路径共 10 次绘制；定点采第 10 次，10,996 个 RGB 像素变化 | 前后 raw 差分落在当前玩家头发和耳部 |
| `e86f0d4916054deb` | character | 该路径 3 次绘制；第 1 次改变 53,565 个 RGB 像素 | 差分清楚覆盖当前玩家裙装；另两次为较小区域 |
| `643c8fab6e8d0bce` | skin | 17 次绘制，前两份颜色快照分别改变 1,219 / 961 像素 | 尚未对应到当前玩家 |
| `ba9e417598de8f83` | skin | 10 次绘制，前四份颜色快照均无变化，后续只有少量 query samples | 尚未对应到当前玩家 |

头发与裙装的采样均使用原 PS，在 RGBA16F 单输出目标中实际写色；同帧 backbuffer 上的离线差分标注已目视核对。标注的紫色是本地分析图层，游戏没有开启 marker。它比“包名称/绘制计数”更强，但只证明当前发型、衣物和视角下的空间对应，不能直接推广到其他装备或全部皮肤。后续处理会改变该目标，完整最终合成追踪仍未完成。

后续环境光实验应首先审计这两个已确认写色的精确 PS，分别核对签名、最终法线、环境 SH 合成位置与运行时绑定，再建立实际绘制对照。旧 `980154264a89fba1` 不能再作为通用玩家颜色入口。皮肤保留缺口，光照收益及 GPU 成本未验收。原 census 的前 512 条限制已记录；下一次如仍需广泛统计，应过滤无颜色输出的阶段或提供分段记录，而不是盲目扩大常驻采集。

采集后 marker、环境光、audit 均关闭。原始图像和差分图只保留本地，Git 仅存 [汇总证据](validation/native-material-live-r7-2026-10-09.json)。
