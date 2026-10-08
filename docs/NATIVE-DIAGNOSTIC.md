# 原生光照诊断候选：工程交付与实机入口

2026-10-08，开发分支 `feature/native-lighting-reshade-diagnostics`，从已发布的 `r10` / `7ec7432` 分出。本轮完成 M0 的工程准备和 M1 的诊断实现与隔离验证；**M1 的游戏验收、M2 实机审计和 M3 画质改动未完成**。真实客户端保持 r10 daily，仅 tone；没有安装新 DLL。

## 固定环境与目标表

运行库固定为官方 ReShade **6.8.0，完整 Add-on 支持，x64**。源码提交 `18deaa52de0c425a78b329e9cb3c497281cd00ec`，API **20**，MSVC `14.51.36231`、Windows SDK `10.0.26100.0`、C++17 `/O2 /MT /Brepro`。官方下载见 [ReShade](https://reshade.me/)，固定 SDK 见 [v6.8.0](https://github.com/crosire/reshade/tree/v6.8.0)。运行库不加入本项目发布附件。

| 项目 | 固定 SHA-256 |
|---|---|
| 官方完整 Add-on 安装器 | `afe4c8f13048306307983b8b3d41d5bf00a86820440b0e57dea10950e1176445` |
| 从安装器取得的 ReShade64.dll | `0cee63f9c9f13f3ac909c5b4903f4dbb4b719a7ab3b4f13b0deaf83c814b94f7` |
| 全屏材质原始 DXBC | `907ce4b6cc047a429a41c537a33a44c3fff04bd74ea66ad780e9b669d72dd740` |
| 网格材质原始 DXBC | `f8face0fb530f3b884c2a6b2af289fa1a8bb3ed0e4301b03efd34afadf7c76f7` |

插件用原始 DXBC SHA-256 对照识别，不把 3DMigoto hash 当 ReShade hash。VS 身份也记录 SHA-256；迟于创建时才加载的未知 shader 不猜测匹配。要求完整重启，不能热装 DLL。

| 目标 | PS 常量 | VS 常量 | PS 纹理 | 独立观察 |
|---|---|---|---|---|
| `415a922293923fa4` | b0/b1/b2/b3 | 无 | t10 位置候选、t5 法线候选、t3/t4 原生漫反射/镜面输入、t0 反射数组绑定 | 当前 OM 深度附件 |
| `980154264a89fba1` | b1/b2/b3/b4/b6 | b0/b2 | t2 深度候选、t4 法线候选、t0/t1 原生漫反射/镜面输入、t7 反射数组绑定 | 当前 OM 深度附件 |

反射 cube/cube-array 当前只报告绑定、格式和视图类型，明确为不支持读回，不转成 2D 猜测空间光场。支持的 2D array 只读取最详细 mip 的第一个可见 slice，明确记录选择范围。MSAA、压缩及未知格式不转换、不降低精度。网格位置 v6 仍没有独立位置纹理，不能把它与另一绘制的位置拼接。

本机只读核对：游戏文件版本 `2026.09.15.0000.0000`，r10 receipt SHA `8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae`，3DMigoto d3d11 SHA `0ec5fb6e8118eb0c1c6e3955940a98116ba94b090691ee2c7a38ec9be8f51d36`。磁盘 cfg 为 ScreenWidth 1920 / ScreenHeight 1009、Fullscreen 1920×1080、ScreenMode 2、AntiAliasing 1、GraphicsRezoScale 100、Fps 0。这是配置值，尚未核对当前运行时分辨率、升频模式或帧时间。SDR 为用户既有反馈，测试前复核。未发现 dxgi.dll 或 ReShade.ini；检查时没有 ffxiv_dx11 进程。

## 实现边界和日志

- 加载后默认关闭，只保留 shader 身份和资源生命周期；关闭状态不查询绘制绑定、不复制资源。生命周期/hash 回调和每次 Present 的单次命令文件检查仍有成本，未称为零开销。
- F7 开启/停止诊断，F8 手动请求下一帧；也可用下述命令文件通道。只接受一个手动请求，每条目标路径最多一个绘制；忙时拒绝新的触发，不排队。
- 从即时 D3D11 context 的 pre-draw 查询实际六个视口数值、PS/VS 常量及绑定，不依赖之前是否收到绑定事件。记录 CB1 first/count，保存整份缓冲区及其范围。
- 描述先估算原始数据，合计最多 256 MiB。预算超限停止整轮，丢弃尚未读回的 staging，不输出伪成功。预算不是总 CPU/GPU 内存限额，行距/驱动分配有额外成本。
- 每次创建新的插件自有 staging，复制选定子资源后立即放开源引用。Present 时用 `Map(DO_NOT_WAIT)` 读回，最多八次 Present，超时明确记录；原始文件去除行距 padding，保留浮点/typeless 原始位和格式，不生成 JPEG。
- 不替换 shader，不绑定额外材质资源，不改游戏光照参数；draw 回调总返回 false。资源生命周期代次、已观察的更新/copy/map/clear/draw 写入意图均记录；不是完整成功写入历史。关闭期间、间接绘制、UAV 和延迟上下文的生产者覆盖不完整，缺口写入日志，不宣称内容语义已确认。
- 延迟 context 不采集；首个 Present 流为主流，其他交换链不混用。主交换链销毁/重建时停止并清空状态，需重新开启；找不到目标则 `missing_targets`，停止会释放 staging。

输出为游戏可执行文件旁 `SMSM-native-captures/capture-*/manifest.json` 和原始 `.bin`，含来源帧/绘制/pre-draw、身份、子资源、尺寸、格式、生命周期和 SHA-256。`snapshots_complete` 只表示两目标路径观察到，不表示全部绑定有效；每个资源各自有 captured/missing/unsupported/error 状态。相机与光照语义始终待确认。读回延迟帧数和 copy/readback+IO 的 CPU 时间单独记录，不能当 GPU 成本。

## 可复现构建与验证

需要 Windows、Python 3.10+、Git、Visual Studio C++ x64 和 Windows SDK。所有输出要求新目录。

```powershell
git clone --depth 1 --branch v6.8.0 https://github.com/crosire/reshade.git artifacts/reshade-sdk-v6.8.0
python tools/build_native_diagnostic.py artifacts/native-diagnostic-next
python tools/test_native_diagnostic.py artifacts/native-warp-next
python tools/audit_native_lighting.py artifacts/client-2026.09.15 artifacts/native-static-next/report.json
python tools/test_native_reshade_host.py artifacts/native-host-next --package artifacts/native-diagnostic-next --setup artifacts/ReShade_Setup_6.8.0_Addon.exe
python tools/test_native_environment.py artifacts/native-environment-next --package artifacts/native-diagnostic-next --runtime artifacts/native-host-next/d3d11.dll
```

离线结果分开：

1. 实际 WARP draw 与读回验证，8 份捕获报告覆盖默认关闭、重复触发/目标次数、更新常量不复用旧值、缺目标、预算停止、取消、shader 销毁、资源代次及拒绝延迟 context。Python 独立核对 raw float 位、行距、深度、SHA 和同帧来源；检查实际 shader 输出未被采集改变。
2. 官方完整运行库真实加载候选，准确识别两份原始游戏 DXBC，在两次手动请求中取得数值视口及更新后的独立常量。ReShade 官方实现跳过 WARP，因此这个测试使用硬件 **零顶点 draw**，仅证明 Add-on API/原生指针/回调连通，不执行游戏材质算法或冒充实机场景。
3. 模拟客户端完成 r10 → 诊断 → r10 的逐字节恢复；安装中断恢复、外来注入器、运行进程和已修改文件保护通过。真实客户端无写入。

最终构建与证据摘要见 [validation/native-diagnostic-2026-10-08.json](validation/native-diagnostic-2026-10-08.json)。原始 artifacts 留本地，不加入 Git。

## 静态审计回答了什么

`audit_native_lighting.py` 校验两份原始 DXBC，输出原生环境常量的实际指令引用。网格 PS 的 cb6[0–2] 通过法线相关的 dp4_sat 求值，cb6[4] 还与 v6.z 参与衰减，cb6[9] 参与区域插值；不能声称原版给整个人统一亮度。全屏 PS 的 cb2 为动态索引区域参数，包含矩阵变换和区域条件。这提供继续追踪生产者的明确入口。

尚不知道：这些常量在 CPU/前级按对象、顶点或区域如何生成，插值索引与世界位置的真实对应，原生局部灯参数/筛选/更新，以及不同材质的覆盖。字段名或 bytes 变化不是探针语义证明。

## 停机切换与恢复

诊断是独立的原版渲染环境。先通过管理器卸载现有 r10 并保存它输出的备份；不要叠加两个 d3d11 注入器。候选只含本插件，官方运行库自行从上述固定官方安装器取得，校验后作为 `--runtime` 输入。

```powershell
# 退出游戏后，先保存这条命令输出的 r10 备份路径。
python tools/manage_preview.py uninstall --client-root '<客户端根目录>'
python tools/native_environment.py install --game '<客户端根目录>\game' --package '<诊断包目录>' --runtime '<已校验的 ReShade64.dll>'
```

安装器拒绝现有注入器、管理凭据、ReShade.ini、非空旧 shader 目录、未知版本、摘要不符、重解析路径和运行中的游戏；不改 ACL。不热换 DLL。仅管理 d3d11.dll、SMSM.NativeLighting.addon64 和自己的凭据。每次变更有独立备份与持久事务，失败后运行 `recover`；手改/损坏备份会阻止恢复，不能覆盖未知内容。

开始一次短测试后，在管理员终端对实际 game 目录提交：

```powershell
python tools/request_native_capture.py '<客户端根目录>\game' enable
python tools/request_native_capture.py '<客户端根目录>\game' capture
python tools/request_native_capture.py '<客户端根目录>\game' stop
```

每个命令等到游戏下一次 Present 消费后再提交下一个；未消费请求不能覆盖。检查 ReShade.log 与新 manifest 是否完成，不连续触发。F7/F8 为备用，本次官方 host 测试验证的是命令通道，按键通道仍待游戏复核。

结束后退出游戏，卸载候选，恢复先前 r10 备份：

```powershell
python tools/native_environment.py uninstall --game '<客户端根目录>\game'
python tools/manage_preview.py rollback --client-root '<客户端根目录>' --backup '<卸载 r10 时的实际备份>'
```

ReShade 运行时生成的配置/日志、采集和备份保留，不递归删除；之后再次安装诊断前应先将已知 ReShade.ini 保存到独立备份目录。候选不是日常色调迁移；恢复后用 r10 status 核对 daily/tone 与完整性。

## M2 一次短实机配合与后续阻碍

选一个固定明暗/冷暖交界；依次采角色两侧位置、人物固定时两个镜头朝向、已确认会照亮材质的原生局部灯变化，再做一次场景切换。场景找不到真实局部灯则记为缺口，不能用发光贴图代替。每次只请求一帧。原版、插件加载但关闭、插件开启但空闲及一次触发的帧时间要分别记录；可复用 `record_validation.py` 汇总真实帧时间 CSV，无数据不填。

```powershell
python tools/analyze_native_capture.py '<新 capture>\manifest.json' --compare '<上一 capture>\manifest.json'
```

分析器核对 SHA、来源帧/阶段、数值视口和字节预算。只有 shader SHA 与冻结原版完全匹配时才按反射偏移列出 PS 相机候选矩阵，计入 CB1 first/count 范围，范围不足/非有限值明确报告；数值或字段名不证明投影约定正确。比较只列候选字节变化，不自动把它判为世界光场。M2 仍需独立位置/深度对应及数据流补证后才能给出三选一迁移结论。当前结论为**尚未到达迁移决策点**，不能以隔离 host 的合成数据选择“值得迁移”。M3/M4 按原计划的进入条件推进。
