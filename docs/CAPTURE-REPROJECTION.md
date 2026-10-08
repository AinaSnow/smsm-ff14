# 第十轮：无损输入与重投影验证

2026-10-08。新增只读检查器和不可变采集审阅文件。本轮没有安装包、客户端写入或实机结论。单灯、遮挡和柔和漫反射保持上一轮实现。

## 本轮证据

`artifacts/capture-reprojection-validation-v5/report.json`：66 项检查通过。九组独立 CPU 射线/几何输入经过 11 次实际 D3D11 WARP 绘制和浮点读回，再交给检查器。GPU pass 只拷贝参考纹理；这是数据通路验证，不是游戏场景回放。

覆盖球面、斜面、反向深度、右手坐标、投影抖动、子视口、非默认深度范围、半精度位置与半精度深度。最大像素重投影误差约 0.04181 像素，来自半精度位置。报告保留深度误差、有效覆盖率、最大值与 P99。

反例包括矩阵转置、逆投影误作投影、错误手性、上下翻转、错误视口、深度不匹配、跨帧/跨绘制/前后阶段混用、空数据、覆盖不足、缺少深度变化、截断/越界/NaN/奇异矩阵、SHA 不符，以及不支持或损坏的 DDS。用同一矩阵从深度重建的位置不能独立证明矩阵正确；数值相符也标为循环证据。

半精度存储采用每个位置分量一 ULP 区间的八个角点计算投影深度不确定度，另计半精度深度的一 ULP。分母跨零或不确定度超过 0.002 时拒绝。WARP 可能截断半精度输出，不能假定最近舍入的半 ULP。特意增加的错误深度仍被拒绝，没有单纯调大统一阈值。

采集草案的默认关闭、目标限制、不可覆盖输出及原包完整性共 3 项测试通过。这不是 3DMigoto 原生 INI 解析或执行测试。

连同历史相机绑定和包管理共运行 28 项单元测试，最终 27 项通过、1 项因 Windows 符号链接权限跳过。目录联接测试首次被沙箱环境阻止创建测试对象，单项在沙箱外、仍仅使用仓库临时模拟客户端复测通过；没有修改该旧测试或游戏目录。新增半精度 ULP 端点检查覆盖零、次正规值与最大有限值。

## 检查器

```powershell
C:\Python314\python.exe tools/validate_capture_reprojection.py artifacts/capture-reprojection-validation-next
C:\Python314\python.exe tools/capture_reprojection.py artifacts/capture-reprojection-validation-v5/sphere/manifest.json artifacts/sphere-correspondence.json
```

输出要求新路径。数值通过退出 0，未通过或缺失数值证据退出 2；格式错误报错。**退出 0 只表示数值对应通过，不代表实机可接入。**

输入实例见生成的 `sphere/manifest.json`：

- `schema: 1`、`source_kind: synthetic/game`。
- `matrix_convention: row_dot_column_vector`，显式指定四个 `projection_rows`；不自动尝试转置挑选成功结果。候选行 18–21、22–25 要分别核对。
- `viewport: [x,y,width,height,minDepth,maxDepth]` 需要独立证据，不能自动以窗口尺寸代替。
- `position_origin: independent_view_position` 仅为来源声明，不是工具已证明的事实。
- `inputs.camera/position/depth` 各有相对路径、SHA-256、`snapshot: {capture,draw,phase: pre}`。相机用原始 `.buf`；纹理用 DDS 或显式尺寸/行距的浮点数据。

位置 XYZ 投影后必须对应原纹素中心，并与独立深度对应。最低要求为 64 个有效样本、视口覆盖 25%、4×4 分区至少 12 格、视空间 Z 范围至少 0.05。对应率须达 99.5%；基础阈值 0.35 像素、深度 0.00005，另计明确的存储精度界限。这些是筛查规则，不是画质认证。

支持单 mip、单切片、2D DX10 DDS 的 RGBA32F/RGBA16F/R32F/D32F/R16F；原始格式为 rgba32f/rgba16f/r32f/r16f。处理行距，拒绝 typeless、压缩、数组、多 mip、传统 FourCC、未知格式和尾部数据。暂不缩放不同尺寸资源。真实文件不支持时保留原件，增加有依据的解码，不转 JPEG 继续。

即使来源声明为游戏且数值通过，`game_projection_verified` 与 `eligible_for_game_occlusion` 仍为 false。独立性、视口来源、绑定范围、资源写入顺序仍需额外证据；没有放宽游戏 shader CB 范围检查。

## 采集草案与缺口

```powershell
C:\Python314\python.exe tools/prepare_capture_audit.py artifacts/capture-review-next
```

当前 `artifacts/capture-review-2026.09.15-v2/` 只有清单及两份 `.ini.disabled`，**不能覆盖游戏 d3dx.ini，也不是可安装包**。生成器校验 r10 基线，记录文件和历史审计摘要，拒绝复用输出目录。

| 单独选择的路径 | 计划读取的已有资源 | 缺口 |
|---|---|---|
| 全屏 `415a922293923fa4` | PS b0/b1、t10 位置、t5 法线 | 同次绘制的独立深度未确认 |
| 网格 `980154264a89fba1` | PS b1/b3、VS b0/b2 候选相机、PS t2 深度、t4 法线 | v6 插值位置不是可直接 dump 的纹理 |

每份草案用 CPU 命令列表变量控制，默认 arm=0、F8 注释；计划每帧最多采目标前两次绘制，Present 后重置。只定点 dump 指定资源，无全帧资源导出、hold、clear_rt 或 deferred-context 采集。次数限制尚未在已安装 DLL 内测试，不宣称硬性内存/时间/字节上限。不用 IniParams，也不新增 GPU 绑定。两个片段不能把重复的 Constants/Present/Hunting 节直接拼接安装。

核对上游源码发现 `RSSetViewports` 日志只记录数量和指针，不记录六个数值；普通 F8 新增 DDS/BUF 仍补不齐视口。不同绘制的深度、位置不能仅按指针拼接，必须审计生产者、后续写入与子资源映射。

下一步补齐数值视口与独立位置/深度采集办法，验证草案解析和次数限制，再构建可回退诊断包。当前无需用户按 F8、F10 或重启。

## 依据

DDS 结构依据微软 [DDS_HEADER](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header)、[DX10 扩展](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header-dxt10) 与 [编程指南](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide)。

定点 dump 语义参照仓库 d3dx.ini 和 3DMigoto 1.3.16 [CommandList.cpp](https://raw.githubusercontent.com/bo3b/3Dmigoto/1.3.16/DirectX11/CommandList.cpp)：未启用 frame analysis 时直接返回，启用后读取指定绑定资源。全局导出和视口日志边界依据 [FrameAnalysis.cpp](https://raw.githubusercontent.com/bo3b/3Dmigoto/1.3.16/DirectX11/FrameAnalysis.cpp)。源码审阅不等于当前 DLL 的运行验证。
