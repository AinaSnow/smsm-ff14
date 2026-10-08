# 单灯原型：实际渲染、注入审计与遮挡研究

2026-10-08，客户端 `2026.09.15.0000.0000`。本轮未修改游戏安装目录，未进行实机测试。所有图是合成输入的实际 D3D11 WARP 读回结果，不是游戏截图或效果预测图。

## 已完成与边界

第五轮补充 [网格材质路径单灯](MESH-MATERIAL-LIGHT.md)：第二条材质路径已有 61 项实际渲染验证，包含最终法线、原版裁剪、9 个灯位和 alpha 混合；两条路径的 v2 候选默认关闭、独立选择，尚未实机验证。下一步接离线遮挡及少量覆盖/叠加测试。

最新第四轮结果见 [材质阶段单灯](MATERIAL-LIGHT.md)：已实际执行原版材质合成与新插入版，62 项渲染检查和 3 项包管理检查通过；绕过前级 R11G11B10 写入后，标准亮度合成样本中增量完全消失比例从 55.63% 降到 3.44%。新的 material-light 候选默认关闭，未安装；只覆盖一个材质路径，游戏内连续控制和遮挡尚未接入。下文保留前三轮研究记录。

第三轮见 [下游注入、边缘复核与目标精度](LIGHT-INJECTION-AND-PRECISION.md)：已追踪两个光照目标的不同消费者与共同场景输出；六组遮挡几何误判总数减少约 61%，但运动变化误差略增。

离线灯具在同一个 D3D11 设备上逐帧更新位置；颜色、强度和范围同样由常量缓冲控制。灯从左移到右，表面漫反射随几何关系正确变化。两份当前游戏主光照字节码的插入版本已在合成 G-buffer 上真正执行并读回两个输出目标。

游戏候选包是 `artifacts/experimental-2026.09.15-single-light-v1`，清单 SHA-256 `d0e7b42914b3046d0f4d9e3699b426487125a3d3dfbcdc33b7828b7c9afd9ba7`。默认 `daily` 仍只开色调，`single-light` 默认关闭。该包是首轮原型，尚未确认游戏内显示、实际混合状态、重复注入次数、真实材质表现或性能。

游戏侧暂采用“参数写入新不可变 shader 包，再明确选择并 F10 重载”，尚未实现游戏内逐帧拖动、世界固定灯位、鼠标拾取或快捷键控制器。离线 b13 动态缓冲不会带入游戏；不用 r5 的 t120.y，不改 DLL/INI，也不自动发送按键。

## 第二轮：重复绘制、材质分支与屏幕空间遮挡

2026-10-08 后续开发仍只在本地进行。新增 **213 项混合/注入差分检查、48 项遮挡检查、2 项历史日志解析测试全部通过**。共享 renderer 修改后，原单灯 **84 项**与原景深合成 **264 帧**回归通过，包管理 **4 项**通过。没有改写游戏目录或既有不可变包，没有安装遮挡实验。

### 注入审计的新证据

`tools/validate_light_stress.py` 实际执行两份原版字节码和 v1 候选，每份覆盖数值 `LightingType=0/1/2/3`、`SemiTransparency=0/0.5/1` 与原光照遮罩为零的输入。数值 ID 不命名为“皮肤/头发”：对应实际材质的语义尚未证明。原型新增漫反射不随这些分支调整，原 alpha、镜面输出保持不变；这证明插入隔离性，不代表已实现材质适配。

renderer 新增明确的合成混合状态（覆盖、RGB 加法、源 alpha 混合）和连续 1/2/4 次 draw，期间不清空目标，alpha 均采用最新源值。另以两个 MRT 的已知常量与 0.25/0.75 alpha 校准混合器，避免仅用游戏 shader 的 0/1 alpha 得出错误结论。所有这些状态都是测试设置，不冒充游戏当前状态。

结果：RGB 加法混合时，重复注入产生 1/2/4 倍增量；覆盖混合不累加；源 alpha 混合会改变或抑制增量。原光照遮罩为零时，原输出 alpha 可以为零，但单灯仍有 RGB 增量。这说明不能未经审计便把原主光的阴影或 alpha 用作新灯的遮挡条件，也不能仅以 shader RGB 正确推断最终画面正确。

`tools/audit_light_capture.py` 重新读取已有 `FrameAnalysis-2026-10-08-021615/log.txt`，不要求重新抓帧：

| 历史 draw | Shader | 观察 |
|---|---|---|
| 1735 | e9f57e0834b642f5 | 一次 DrawIndexed；两个颜色目标 |
| 2000 | 8b384acd7a03c836 | 一次 DrawIndexed；颜色目标、深度目标均不同于 1735 |

两次绑定同一 blend-state 指针，但 depth/stencil-state 指针不同。日志没有状态对象的完整描述符，也没有下游逐像素合成权重，不能确认混合公式、透明分类或每像素累计次数。资源 hash 相同不代表同一个资源对象。本次发现既不能证明重复叠加，也不能证明不存在；下一步要追踪两个不同输出到最终合成的关系。日志 SHA-256 为 `2844d46c132181fda4a2a04e0a0c6c50c79418e53e58943ed4ac4102ef83a92c`，它早于单灯实现，不是新灯实机执行证据。

### 遮挡原型与实际差分

`tools/patches/single_light_visibility.hlsl` 是**独立离线研究实现**，不被游戏包生成器引用。复用已验证的深度/法线与单灯算法，通过审计过的逆投影矩阵求逆，将表面到灯的线段投影回屏幕，再与最近深度比较。控制缓冲 b12 仅由离线工具绑定；不开启时输出与原单灯逐像素一致，不引入新的游戏运行时绑定。

当前固定 96 个线段样本，深度偏差阈值 0.025、假定厚度 0.35，单位为视空间单位；这些是受控测试参数，尚未校准为 FF14 通用值。已找到的遮挡立即保留；没有找到遮挡而线段离屏时标记为不可判定，退回无遮挡结果，不制造屏幕边框阴影。

独立参考使用已知场景的**线段与有限矩形求交**，不复用深度步进算法。测试包括普通投影、反向 Z、右手坐标、投影抖动和偏移视口，以及七个灯位：

- 排除两像素边界带后的真实阴影内部，五种配置检出率均为 100%。明亮内部误遮挡率为 0～0.134%；边界之外仍有少量错误，未隐藏。
- 整个可见接收面仍有 105～146 个像素与几何参考不同（分别统计，图像为 128×80），可见阴影边缘台阶；不是全图逐像素正确。
- 灯左移到右时，阴影质心从约 78.16 移至 48.84 像素；回到相同灯位读回一致。这里没有验证游戏 TAA 或时域稳定性。
- 对照实验故意从深度输入去掉挡板，637 个几何参考阴影内部像素仍被照亮，复现了深度缺失导致的漏光。离屏、背面、隐藏和透明遮挡不会凭空恢复。

原始读回、几何位置、参考阴影、参与评分的内部区域及支持区域均保存，便于检查误差；报告不会把“能稳定复现漏光”写成画质通过。当前只有硬阴影，没有边缘过滤、软阴影或时域处理，不应安装为通用防穿墙方案。96 次采样的真实 GPU 成本尚未测量。

### 本轮产物与重现

| 内容 | 本机产物 |
|---|---|
| 混合/材质分支检查 | `artifacts/single-light-stress-v2/report.json` |
| 遮挡检查、源文件 SHA、几何参考 | `artifacts/single-light-visibility-v2/report.json` 与 `*-reference.npz` |
| 实际读回预览 | `artifacts/single-light-visibility-v2/visibility.png`、`visibility-motion.gif` |
| 旧抓帧状态审计 | `artifacts/single-light-capture-audit-v1/report.json` |
| 单灯回归、景深回归 | `artifacts/single-light-validation-v4/report.json`、`artifacts/dof-composite-validation-v2/report.json` |

预览是灰色合成场景，以 Reinhard+sRGB 显示；不是游戏效果承诺。第一版遮挡验证保留为 v1，v2 修正了“已找到遮挡后仍沿剩余离屏线段回退”的问题，并增加对应断言。新一轮须使用新输出目录：

```powershell
C:\Python314\python.exe tools/validate_light_stress.py artifacts/single-light-stress-new
C:\Python314\python.exe tools/validate_light_visibility.py artifacts/single-light-visibility-new
C:\Python314\python.exe tools/test_audit_light_capture.py -v
C:\Python314\python.exe tools/audit_light_capture.py "E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online\game\FrameAnalysis-2026-10-08-021615\log.txt" artifacts/single-light-capture-audit-new
```

接下来先追踪历史两组光照目标的下游合成，并改善遮挡边界/采样误差。游戏测试应限定为单个注入路径、固定光位与白衣/肤色对照，明确区分执行、覆盖、材质响应和成本；在阶段证据补齐之前不要求用户盲测，也不同时推广两份注入。多灯、风格化与 SSGI 顺序不变。

## 当前接口审计

依据：提取清单与原始 DXBC、官方编译器反汇编、`build-audit/<hash>/original.asm`。生成器重新校验原始 SHA/FNV、指令精确往返、资源/输入输出签名及常量缓冲范围。以前的主光照帧定位只是候选依据，不是本轮新灯执行证据。

| 项目 | 已确认的字节码关系 | 原型处理 |
|---|---|---|
| 像素位置 | 两个 shader 都使用 `SV_POSITION.xy` | 使用相同像素坐标，包含半像素中心 |
| 深度 | t0/s0；原版 swizzle 后取深度 x | 同槽采样，0/1 深度端点视为无效背景；近裁剪面精确端点也暂排除 |
| UV 与视口 | b0[0] 提供像素到纹理 UV 的缩放/偏移；b0[1] 提供像素到裁剪 XY 的变换 | 保留两个独立变换，不假定全尺寸无偏移视口 |
| 位置 | b1[14..17] 为逆投影四行，点乘 clip 后除以齐次 w | 与原版重建一致；不硬编码正向/反向 Z 或摄像机前向符号 |
| 法线 | t3/s2.xyz 减 0.5，以 b1[0..2].xyz 转换，再归一化 | 使用同一解码；近零/非有限法线不添加灯光 |
| 主光变体 | `8b384acd7a03c836` 与 `e9f57e0834b642f5` | 两个候选分别验证，不推断已覆盖所有路径 |
| 输出 0 | 主光 DiffuseColor 参与计算，最终分别由 r3/r10 写入 o0 | 在最终写入前向 RGB 加单灯漫反射项，alpha 不变 |
| 输出 1 | 原有镜面光分支输出 o1 | 完全不修改；读回要求逐像素一致 |
| 下游合成 | 本轮没有捕获真实材质合成及混合状态 | “漫反射辐照度候选”是阶段解释，不等于所有材质已适配；不得直接加在最终色调/UI 之后冒充物理光 |

灯位明确为 **view-space** 坐标，单位沿用重建坐标；不是已经校准的米或世界坐标。相机移动时，烘焙在视空间的灯会随相机变化。世界固定灯位需在后续审计逆视图/世界变换后实现。

## 灯模型

可调参数为视空间 xyz、线性 RGB、强度、范围。只实现漫反射：`max(N·L,0)/π`，乘以有限距离衰减 `(max(1-d²/r²,0))²/(1+d²)`。这是一种有界的艺术控制模型，未校准光度单位；光源处避免除零，范围边界平滑归零。不钳制或重新染色原始画面，保持原有高光目标和 alpha。

白灯在合成白色、肤色与蓝色参考材质上不改变线性 RGB 色度。这个检查只覆盖原型漫反射模型，不代表实际游戏皮肤次表面、白布高光、曝光或色调映射已经通过。后续材质适配不能以本项通过代替实机验证。

## 实际渲染工具与证据

`tools/offline/render_ps.cpp` 创建系统 D3D11 WARP 设备，绑定纹理、结构缓冲、常量、采样器和多个浮点输出目标，调用 `Draw`。随后 `CopyResource` 到 staging texture，再 `Map` 按 RowPitch 读回 RGBA32F。支持自定义 VS、偏移视口以及同设备逐帧常量更新。默认采样器为 point/clamp；未来验证过滤时必须明确扩展采样器配置，不能将该默认状态当作游戏原始采样器。

实现方式参考 Microsoft 的 [WARP 设备文档](https://learn.microsoft.com/en-us/windows/win32/direct3d11/overviews-direct3d-11-devices-create-warp) 与 [D3D11 staging 资源说明](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ne-d3d11-d3d11_usage)。WARP 是软件光栅化，真实执行 D3D11 绘制但不代表用户显卡的 GPU 成本。

`tools/offline_render.py` 自动使用本机 Visual Studio C++ 工具和 Windows SDK 构建 renderer。所有 job、输入、shader、逐帧浮点读回、差分数组及报告保存在新 artifacts 目录，方便重放。可直接运行 `render_ps.exe <job.txt>`；输出文件存在时拒绝覆盖，需换一个输出前缀。

本轮结果：`artifacts/single-light-validation-v3/report.json`，**84 项检查全部通过**，另有 **4 项包/参数/恢复测试通过**。

| 验证 | 判据与结果 |
|---|---|
| 坐标重建 | 8 组配置：透视、反向 Z、右手投影、旋转法线、斜面、偏移视口、投影抖动、宽屏；位置最大绝对误差约 2.04e-5 |
| 灯移动 | 同设备 13 帧 x=-3 到 +3；受光质心从约 41.94 移至 117.06 像素，单调向右；逐帧 RGB 对参考最大误差约 1.22e-6 |
| 参数与边界 | 红灯、强度倍增、范围变化、灯在表面背面、范围外、零强度、无效深度与法线；结果满足参考及零贡献条件 |
| 确定性 | 灯移开再回到同位置，原型读回逐像素相同；不声称已验证游戏时域缓存 |
| 两份真实游戏 shader | 原始 DXBC 与实际封装插入版都执行；中心/左暖/右冷/短范围的输出 0 增量与参考最大误差约 1.47e-7 |
| 保留通道 | 输出 0 alpha 与完整输出 1 差分为 0；零强度返回原字节码，读回与原版完全一致 |
| 管理 | 默认关闭，禁止与占用同 hash 的旧阴影组混装；测试启停、备份、切回 r10 后精确恢复 |

第一轮验证发现零强度 helper 被编译器优化成无资源常量 shader，已修复：仅识别严格的全零返回指令，直接保留原字节码，不捏造资源声明。失败运行保留于 `single-light-validation-v1`；通过结果以 v3 为准。

预览：`artifacts/single-light-validation-v3/moving-light.png` 与 `moving-light.gif`。预览使用 Reinhard + sRGB 显示合成材质结果；线性浮点文件才是数值验证依据。

## 重现与参数控制

```powershell
C:\Python314\python.exe tools/offline_render.py
C:\Python314\python.exe tools/validate_single_light.py artifacts/single-light-validation-new
C:\Python314\python.exe tools/test_single_light.py -v
```

验证依赖已生成的本地候选包；如首次构建：

```powershell
C:\Python314\python.exe tools/build_single_light.py artifacts/client-2026.09.15 artifacts/preview-2026.09.15-r10-managed artifacts/experimental-2026.09.15-single-light-v1 --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe --position 0 0 0 --color 1 1 1 --intensity 2 --range 8
```

换灯位/颜色时必须使用新的输出目录，不覆盖 v1。shader 包不包含原始游戏字节码的发布授权；原始数据与构建产物只保留在本机 artifacts，不提交或发布。

候选包将原 `shadows` 组替换为 `single-light`，因为它们占用相同的两个 shader hash，不能同时安装两个替换。其他组及运行库保持与 r10 相同。管理器可明确选择该包后 `--enable single-light` 或 `--isolate single-light`，关闭则 `--disable single-light`。本轮没有执行这些真实客户端写入；尚不安排大范围游戏测试。

## 已知限制与下一道实机门槛

- v1 游戏候选无遮挡求解，可能穿墙照亮另一面。第二轮已有独立离线遮挡研究，尚未打入游戏包。屏幕深度只含最近可见表面，无法恢复离屏、背面或隐藏几何；不能承诺灯光投射正确阴影。
- 只处理这两份延迟光照 shader 的可见深度/法线。透明、头发、眼睛、粒子、皮肤/特殊材质及独立渲染通道未适配。
- 在原有主光照 draw 内注入；若同一像素经过多次相同阶段，可能叠加多次，或受到原有 stencil/blend/半透明状态限制。真实次数、输出范围和能量域是下一次小规模实机测试的先决检查。
- 新实验无实际显卡帧时间测量；不以 WARP 耗时或采样数推算 FPS。成本在真实单灯/原版对照中单独测量。
- 下一轮先确认注入覆盖/次数和白布、肤色能量响应，再比较三个已知灯位。实机通过后才设计连续交互参数通道；不直接推广 b13 或旧 r5 机制。

之后依用户顺序研究遮挡与材质、多灯摄影预设、SSGI；硬件光追独立可行性研究。

## 景深与反射研究继续

已有实验实现未删除。当前“不明显”只表示尚无明确画质收益；执行与成本分别保留状态。

本轮还用新工具真正执行了原始景深合成 `4b85fee6dc176fb3`：`tools/validate_dof_composite.py` 在四类输入下绘制 **264 帧**，核对近远各两级层、权重过渡、曝光、平方/开方域、近层零覆盖边界和黑场，全部通过。输出位于 `artifacts/dof-composite-validation-v1/report.json`。这为完整散景开发建立当前合成基准，尚不覆盖 CoC 生成、模糊核、前景扩张或整条链的漏色。

后续景深要使用点光、恒色、前景遮挡、焦点扫动和长宽比变化的已知输入；分别验证近远层核形状、半径、能量及边界。反射继续研究原追踪命中、采样边缘、材质相关过滤和运动稳定性；需补齐实际过滤器/层级深度与时间序列输入，不能把最终采样抖动等同于完整反射算法改进。当前没有新增反射画质结论。
