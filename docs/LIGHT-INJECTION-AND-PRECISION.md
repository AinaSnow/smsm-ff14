# 单灯第三轮：下游资源、遮挡边缘与目标精度

2026-10-08，本地开发；未修改客户端、未安装新包。本文记录实际离线结果和历史抓帧证据，不能代替当前游戏执行与真实显卡性能验证。

## 两组光照走不同路径，随后写入同一场景目标

新增 `tools/trace_light_resources.py`，输入仍是 `FrameAnalysis-2026-10-08-021615/log.txt`。工具按资源对象地址区分相同 hash 的纹理，处理部分槽位更新、空绑定和 RTV/SRV 冲突，并以 SHA 校验后的原始 DXBC 静态纹理读取指令过滤 PS 槽位。绑定了但 shader 不读取的槽位不计入候选依赖。

| 光照来源 | 后续读取示例 | 证据 |
|---|---|---|
| draw 1735，e9f57e0834b642f5，o0/o1 | draw 2094，415a922293923fa4，t3/t4 | 反射信息命名为 `g_SamplerLightDiffuse.T` / `g_SamplerLightSpecular.T`；Draw(3) 全屏合成 |
| draw 2000，8b384acd7a03c836，o0/o1 | draw 2177，980154264a89fba1，t0/t1 | 名称为 `g_SamplerLightDiffuse` / `g_SamplerLightSpecular`；DrawIndexed(4323) 材质绘制 |
| draw 2000 的同组资源 | draw 2259、2316 等后续材质 shader | 对应槽位和读取指令保存在报告中，不依据绘制顺序推断具体人物/材质 |

上述 draw 2094、2177 的颜色输出对象均为 `0x0000020d4941c460`。这是两条路径在资源层面的汇合证据，不是逐像素重复加光的证明。两份示例下游 shader 均可看到材质相关计算，最后包含非负钳制、平方根及常量缩放；因此不能把中间光照缓冲和最终场景颜色当成相同能量域，更不能直接把单灯 RGB 加到色调之后。

报告 `artifacts/single-light-resource-trace-v3/report.json` 分开保存：

- `direct_consumers`：原输出**同一资源对象**后来被读取。期间可能已有其他写入，不能保证还保留原 draw 的全部内容。
- `potential_edges`：可见 PS 操作的潜在依赖上界。混合/模板状态不明时保留祖先集合，不推断精确像素来源。
- `gaps`：未建模的复制、计算 shader、命令列表等操作会中断祖先传播，不悄悄把缺口拼成完整帧图。
- `shared_consumer_outputs`：两组资源的消费者写入相同输出对象。

v1 的传播过于保守，在未建模操作处中断后遗漏了后续同资源读取；v2/v3 将对象身份读取与内容祖先分开。没有把缺失传播当作“该路径未使用”。解析测试覆盖部分更新中的空槽、实际静态读取槽、同 hash 不同对象和读写冲突；旧审计的绑定持续性与上下文失效测试也保留。

## 局部平面复核减少遮挡扩大，但尚未改善运动稳定性

上一版厚度步进只要线段点落入深度后方的假定厚度，就判为遮挡。这相当于把采样表面扩成一层体积，容易扩大阴影。

新增编译开关 `VISIBILITY_PLANE_REFINE`，默认 0。开启时先用原步进找候选，再使用候选法线求线段与局部切平面的交点；把交点重新投影，以该位置的深度复核，排除落在表面延长线外的命中。仍然只在离线程序启用，游戏构建器不引用它。

`tools/compare_visibility_edges.py` 使用未参与第一轮评分的倾斜、细条与高分辨率场景，参考为独立线段/有限矩形求交。每个接收面像素都计入误判，不只比较排除边缘后的内部区域：

| 场景 | 原厚度法误判像素 | 局部平面复核 |
|---|---:|---:|
| 正面挡板 | 146 | 126 |
| 倾斜 25° | 81 | 21 |
| 倾斜 65° | 314 | 10 |
| 细挡板 | 172 | 47 |
| 256×160 分辨率 | 376 | 199 |
| 抖动投影 | 120 | 70 |
| 合计 | **1209** | **473** |

总误判减少约 **60.9%**，六组均有减少；仍有误差，不能宣布边缘问题解决。最近点深度采样、有限步数和假定厚度仍然存在。游戏中的法线可能是贴图法线而非几何切平面法线，因此实际材质上仍可能误判。

13 帧小幅灯位移动使用同一个 D3D11 设备逐帧更新常量。相对几何参考的可见性平均误差从 0.01309 降到 0.01001，但相邻帧变化的误差从 0.005005 升到 0.005316，约增 6.2%。这是**静态边缘更准、该序列变化误差略差**的结果，不能称为运动稳定性改进。不用把真实移动阴影强行冻结来获得低变化分数。

产物：`artifacts/single-light-edge-comparison-v1/report.json`、`edge-comparison.png`、逐场景参考掩码、逐帧浮点读回。原模式与复核模式分别通过 `single-light-visibility-baseline-v3` / `single-light-visibility-refined-v2` 的 48 项基本检查（共 96 项），包括关闭时恒等、有限值、已知遮挡、离屏回退和缺失几何漏光。

## R11G11B10 写入精度是实际注入门槛

历史日志在 draw 1735/2000 的两路输出均标出 `R11G11B10_FLOAT`，且 JPEG 导出报错 `0x80070032`。这提供格式线索，不提供原始浮点纹理内容；不能把失败导出的 JPEG 当作定量输入。

renderer 现支持 `target_format="r11g11b10"`：真正创建该格式的 D3D11 输出目标、绘制、复制到 staging 并 Map 读回原始 `.r11` 数据；默认仍为 RGBA32F。Python 解码遵循 [Microsoft DXGI 格式定义](https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format)：RGB 分别为 11/11/10 位无符号浮点，没有 alpha。返回数组的 alpha=1 只是工具接口占位，不是 shader alpha 的验证结果。

`tools/validate_light_target_format.py` 先以精确可表示值、非规格化最小值、最大有限值及非精确值校准，再实际运行两份原版/插入版游戏 shader。使用 v1 包的白灯、强度 2、范围 8；合成几何为 64×40 球面与背景平面，仅改变原有主光的漫反射亮度。两份目标在此输入下得到相同结果：

| 原主光亮度倍率 | 新灯全部 RGB 增量消失的像素比例 | 仅蓝通道增量消失的比例 |
|---|---:|---:|
| 0.25 | 3.91% | 22.34% |
| 1 | **34.06%** | **80.16%** |
| 4 | 88.59% | 92.81% |
| 16 | 96.56% | 98.44% |

“消失”指 RGBA32F 对照中有正增量，但两个 packed 输出值完全相同，并非零光照或肉眼问卷。蓝通道精度较低，白灯的小幅增量也可能出现 RGB 不同程度的量化。这些比例仅属于合成场景，不是游戏截图测量；不能用来解释此前景深/反射的肉眼差异。

v1 测试最初错误地假定四舍五入的半 ULP 误差界，实际本机 WARP 读回呈正数截断。v2 增加能区分截断与四舍五入的校准值，并检查小于一 ULP 的转换误差界，**25 项通过**，packed 镜面目标仍逐像素不变。失败证据保留，未覆盖旧输出。该 WARP 转换行为不保证所有显卡完全相同。

产物：`artifacts/single-light-target-format-v2/report.json`，所有 packed 与 float32 对照保留。这里的内部浮点目标与 Windows HDR 开关是不同问题，不要求用户改变当前 SDR 设置。

## 决策、回归与下一步

当前 v1 游戏候选保持默认关闭，暂不要求用户安装测试：只靠小增量在 R11G11B10 光照目标上累加，不能保证自然且稳定的颜色变化。也不直接用提高强度掩盖量化问题。

下一步优先审计并离线复现**材质合成中、开方/曝光缩放之前**的注入候选，比较小幅白灯能量、白布和肤色以及目标格式转换；必须保留材质响应，不能跳到最终画面叠色。两条材质路径分别处理，先证明单条路径再考虑组合。遮挡复核仍是独立实验，接着测贴图法线、曲面和运动误差，不宣称完整防穿墙。多灯与 SSGI 排在这些验证之后。

共享 renderer 修改后的回归：单灯 84 项（v5）、混合/分支 213 项（v3）、原景深合成 264 帧（v3）；包管理及审计/资源解析共 8 项测试通过。没有真实 GPU 帧时间数据。

```powershell
C:\Python314\python.exe tools/compare_visibility_edges.py artifacts/single-light-edge-comparison-new
C:\Python314\python.exe tools/validate_light_visibility.py artifacts/single-light-visibility-refined-new --refine
C:\Python314\python.exe tools/validate_light_target_format.py artifacts/single-light-target-format-new
C:\Python314\python.exe tools/trace_light_resources.py "E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online\game\FrameAnalysis-2026-10-08-021615\log.txt" artifacts/single-light-resource-trace-new
```

所有输出目录必须新建；本机游戏字节码、反汇编与读回仅留 artifacts，不提交发布。
