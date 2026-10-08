# 网格材质路径单灯：第五轮证据

后续第九轮已接入离线深度遮挡、两组连续灯位序列及斜面复核，见 [网格材质遮挡](MESH-VISIBILITY.md)。下文保留第五轮原始证据。

2026-10-08，客户端 `2026.09.15.0000.0000`。本轮在第四轮全屏材质路径之外，补充 `980154264a89fba1` 的原版渲染对照与单灯插入。新增 **61 项实际渲染检查通过**，原路径 **62 项回归通过**，新旧包的 **6 项审计/管理测试通过**。候选未安装到游戏，运行时覆盖、性能和两条路径的像素重叠仍未验证。

## 顶点与像素阶段审计

`tools/audit_forward_material.py` 读取已有 `FrameAnalysis-2026-10-08-021615/log.txt`，日志 SHA-256 为 `2844d46c132181fda4a2a04e0a0c6c50c79418e53e58943ed4ac4102ef83a92c`。结果保存在 `artifacts/forward-material-audit-v2/report.json`。

该 PS 的历史绘制共 **6 次**：2177、2179、2181、2183、2184、2186。前五次绑定 `d241dd6ca4f03df3` VS，最后一次绑定 `972493e7d05b8002` VS。原始 VS 均经过提取清单 SHA-256、FNV shader hash 和客户端版本校验。

两份 VS 将 `r22.xyz` 写到 `o6.xyz / TEXCOORD4`，同一位置又经过反射信息标为 `m_MainViewToProjectionMatrix` 的矩阵写出裁剪位置；第二份 VS 的条件变形分支还通过 ViewMatrix 更新该位置。这与 PS 将 `-v6.xyz` 用作视线方向的行为一致，支持将 v6 视为主视图空间位置的解释。PS 内 `v3/v4/v5` 构成法线/切线基，读取法线贴图后得到 `r1.xyz`，再与经 ViewMatrix 转换的共享 G-buffer 法线比较。

这些是接口与数据流证据，**没有回放原版蒙皮、变形、顶点/索引缓冲和深度模板状态**。绘制次数也不能证明像素重叠、对象名称或每像素加灯次数；状态指针不等于实际 blend/stencil 描述。不能据此声称该 PS 覆盖所有人物、头发、皮肤或透明材质。

## 插入点

原版先读取 `t0` 漫反射光，以共享法线和最终材质法线的夹角校正，再加入原有相机补光。本轮插入点在这一校正之后：

```text
native: r7 = sampledDiffuse * normalAlignment + nativeCameraLight
insert: r7 += pointLamp(finalNormal=r1, viewPosition=v6)
native: wetness/material/ambient/specular/alpha/discard/sqrt/exposure ...
```

新灯使用最终法线，因此不能再乘一次共享法线校正。新增专门的垂直法线测试：共享法线与网格法线相差 90°，原采样光贡献为零，但新灯在正确的一侧仍产生受光，输出与独立 Lambert 公式一致。

`tools/patch_forward_light.py` 编译无外部资源的烘焙 helper；通用插入器核对 helper 的两个输入声明，将其精确映射到宿主 r1 和 v6，且先重映射 helper 临时寄存器，防止误改宿主 r1。原始指令往返、插入区外恢复、接口、常量边界和资源绑定检查沿用前轮。保留 `forceEarlyDepthStencil` 和两处原始 `discard_nz`。零强度保留原字节码。

没有增加单灯自己的镜面高光或遮挡，也没有把原版相机光的阴影当成新灯阴影。原材质的 AO/高光/alpha 逻辑继续执行，但不能因此声称新灯拥有正确投影阴影或全部材质响应。

## 实际渲染验证

`tools/validate_forward_light.py` 用一个可审计的合成 VS 提供平面、切线基、UV、顶点色、视空间位置和湿润参数；真正执行完整原版 PS 和插入版 PS，读回 RGBA32F / RGBA16F。合成 VS 的用途是隔离像素阶段，不冒充游戏原始网格。

主对照把独立 CPU 灯光换算到原版 t0 输入：在夹角校正大于零的受控测试中，以 `lamp / normalAlignment` 修改对照纹理，使原版校正后恰好得到目标增量。**除法只存在于测试输入，不进入游戏候选**。垂直法线测试不使用这一除法，直接使用独立解析结果。

最新报告：`artifacts/forward-light-validation-v5/report.json`，61 项通过。

| 检查 | 判据与结果 |
|---|---|
| 13 类输入 | 白色/肤色/蓝色参考、倾斜法线贴图、半 alpha、零 alpha、深度拒绝、金属参数、湿润参数、曝光及 LightingType 1/2/3；完整原版 RGBA 对照通过 |
| 独立解析公式 | 简化材质采用 `sqrt(albedo × (B × alignment + lamp)) × exposure`；包括白色、肤色与倾斜法线 |
| alpha 与裁剪 | 所有配置新增灯前后 alpha 一致；零 alpha、遮挡深度输出为零；同屏深度拒绝的一半保持零，另一半正确加灯 |
| 灯具控制 | 左暖、右冷、表面背后、范围外；符合独立参考 |
| 垂直法线 | 原光校正归零后，新增灯仍按最终法线照亮正确方向 |
| 完整 PS 灯位序列 | 9 个烘焙灯位从 x=-3 到 +3；受光质心从 17.07 到 45.93 像素单调向右 |
| 混合/格式 | 实际源 alpha 混合使 RGB 正确减半；FP16 写入误差不超过一个可表示步长 |

除单独以 ULP 计的格式转换外，最大绝对误差约 **9.46e-8**。每个灯位用独立渲染 job/设备执行；这证明完整材质的空间响应，不等于游戏内连续调灯控制。数值材质 ID 不直接命名为实际皮肤或头发。

早期失败记录保留：v1 暴露无资源 helper 没有 Resource Bindings 反射节，已补充安全识别而非伪造资源；v2 的测试误将覆盖 alpha 放在 normal 纹理 x 通道，原版 swizzle 实际使用 w，已修正测试输入。v3/v4 通过后追加单步长 FP16 判据，最终以 v5 为准。没有修改原版材质公式以迎合测试。

## 候选包和管理

包：`artifacts/experimental-2026.09.15-material-light-v2`。

清单 SHA-256：`6243095317d11ccfc4f2a174e87307cb5d63debdecaa2d2ff8accbd3decd7863`。

默认 `daily` 仍仅开启 tone，新增灯都关闭。独立选择：

| profile | 替换路径 |
|---|---|
| `material-light-only` | 全屏材质 `415a922293923fa4` |
| `mesh-light-only` | 网格材质 `980154264a89fba1` |
| `material-light-both` | 两条路径；像素重叠与合成仍待实机检查 |

v2 以审核过的 r10 为基线，新增两组默认关闭实验；拒绝把前级 single-light 包作为输入。相对 v1，全屏路径的字节码完全相同，重建 TXT 仅反汇编器时间戳注释不同；其他既有文件完全相同。新增网格 shader 的 SHA 与 v5 实际渲染字节码一致。10 个打包 shader 的创建检查通过；创建检查与上述实际绘制检查分开记录。

`test_forward_light.py` 3 项测试通过：历史绑定持久化/清除、候选字节码及接口/default-off、两组独立选择/切换/备份/精确恢复。第四轮 `test_material_light.py` 3 项回归通过。真实游戏目录没有写入，不热换 DLL、不改 INI、不发送按键。

复现（仓库根目录，输出目录必须不存在）：

```powershell
C:\Python314\python.exe tools/validate_forward_light.py artifacts/forward-light-validation-new
C:\Python314\python.exe tools/build_material_light.py artifacts/experimental-material-light-new --include-mesh
C:\Python314\python.exe -m unittest discover -s tools -p test_forward_light.py -v
```

包测试绑定本轮 v2/v5 证据。原路径的最新 62 项回归结果在 `artifacts/material-light-validation-v5/report.json`。本轮没有修改共享 renderer、景深或反射实现，因此未重复无关的大范围测试，也没有新增它们的画质结论。

## 下一步

下一轮可将离线遮挡研究接到材质阶段，先用已知几何检查深度重建、光线终点、薄物体和法线边界，再比较加灯前后的边缘误差。继续保留无遮挡基准，避免用原有 AO 掩盖穿墙。

实机只安排固定相机/曝光、两条路径分别隔离、无灯与左右灯位三种状态的短测试：先证明覆盖和受光方向，再检查同时开启是否重复加光及白衣肤色。灯仍为相机相对的烘焙参数；连续控制、世界固定、透明覆盖、真实帧时间和两路径重叠需要各自证据。屏幕深度无法提供离屏/隐藏几何，完整硬件光追不属于本实现。
