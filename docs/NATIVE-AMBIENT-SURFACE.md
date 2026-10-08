# r4：原生区域环境漫反射实验

2026-10-09。首个原生光照材质候选，默认关闭。范围是精确网格 PS `980154264a89fba1` 的一项环境漫反射贡献；尚未证明实机画质收益、玩家材质覆盖或 GPU 成本，不代表完整迁移完成。

## 具体改变

原网格材质从本次绘制的 CB6 环境系数求漫反射。候选使用已有原生区域的形状、顺序和 SH 系数，在当前像素的原生 v6 视空间位置求值，以原生最终法线求方向响应，再替换原 `r8` 的 SH 漫反射部分。它继续走原材质的距离衰减、AO、反射、alpha/discard、曝光和输出编码。

它不会在原环境光上再加一份灯光。只有局部区域数量大于零时尝试替换；全局唯一场景、缺失/尺寸不符的区域资源、未知类型、不合法参数或相机关联失败，都保留原材质输出。半强度在漫反射项的线性能量域混合，不混合最终画面。

区域采用原生的球形（1）、盒形（2）和柱形（3）几何衰减，依原数组顺序取前三个有效条目并保留其层叠方式。区域中心以数学极限处理，避免 0/0。此候选只移植几何区域选择和 SH：背景材质额外的天空/遮挡权重没有照搬，网格本身的原生 AO/衰减继续使用。因而这是有边界的表面采样实验，不是完整背景光照算法等价移植。

## 运行时接入

独立编译选项 `--ambient-shader` 将经过验证的 shader 嵌入 Add-on。普通诊断构建不包含实验。实验包清单 `shader_replacement=true`、`default_enabled=false`，安装必须明确传 `--allow-shader-experiment`。

开启后，只在即时 context 的已识别全屏材质入口获取原生区域 CB2 和相机 CB1。每帧至多复制一份已绑定范围到插件自己的 structured buffer，最多 64 KiB；保留整数标记的原始位。网格绘制必须在同一帧，PS CB3 相机对象及范围完全相同，相关缓冲区没有观察到更新。遇到更新或延迟命令列表执行就失效回退。

针对该精确网格 PS，一次绘制临时使用候选及 t12/b8，执行原顶点/索引/实例参数后恢复原 PS、SRV 和包含 first/count 的 CB 绑定。没有额外复制整屏颜色/深度，没有 CPU 逐帧读回。RDEF 反射已去除，避免新增绑定带着旧反射说明；输入/输出签名与原始指令流的其余部分保留。

## 已验证与仍需验证

47 项真实 WARP 材质绘制检查通过：白色/肤色参考、方向法线、全局场景、原反射输入、湿润、金属、alpha、discard、深度拒绝、三种形状及不对称边界、三层重叠、区域逐帧移动、半强度、FP16 输出、异常输入回退。实际捕获的咖啡馆参数也通过 GPU 复制进入合成平面，并产生随位置变化的输出。它是合成几何，不冒充游戏截图或真实皮肤验收。

摘要见 [验证记录](validation/native-ambient-r4-2026-10-09.json)。候选 shader SHA 为 `47bd23612a5b0fda513578c81ca0acb3e2f23313c1d08ceab9165c7c89f938b3`，Add-on SHA 为 `f3c9f01671cae18dd00abc80cf532e254227c38ca0dad28bc34ef942f9f4de81`。咖啡馆真实参数在合成平面的最大 RGB 差约 0.00366，不能据此承诺肉眼明显；不放大系数来制造收益。

运行时桥单独用 WARP 实际绘制验证：带范围的原生 CB→专用 SRV 复制正确，相机/帧失效会回退，正常与异常路径均恢复状态。官方 ReShade 6.8.0 硬件零顶点 host 验证开关和回调连接，三次复制/三次受控绘制，关闭后计数不再增加；它不代表像素画质。停机升级、中断恢复、r10 回退和设置保留通过。

首版动态浮点常量索引导致区域类型位被浮点化，已由真实球形测试检出并修正。使用 GPU 复制后的 uint4 structured rows，整数标记保真；helper 从过度展开的代码降为约 188 条指令。指令数不是 GPU 时间，实机性能仍须单独测量。

下一次实机只在已有局部区域的固定场景对照，优先咖啡馆相同位置的肤色/白衣；有且仅有全局区域的地图不会显示本实验的空间差别。先核对运行计数，再看局部明暗是否自然；没有可辨认收益时保留结果并分析，不要求反复换地图。

## 构建、安装与开关

```powershell
python tools/validate_native_ambient.py artifacts/native-ambient-next
python tools/build_native_diagnostic.py artifacts/native-ambient-addon-next --ambient-shader artifacts/native-ambient-next/patch/native-ambient.bin
# 游戏退出后，在管理员终端更新；保持默认关闭。
python tools/native_environment.py update --game '<game 目录>' --package '<实验包目录>' --allow-shader-experiment
```

进入场景后使用普通用户可写的已初始化采集目录发送命令：

```powershell
python tools/request_native_ambient.py '<game 目录>' half
python tools/request_native_ambient.py '<game 目录>' status
python tools/request_native_ambient.py '<game 目录>' off
```

`on` 为完整强度，`half` 为半强度，`off` 立即回原材质，`status` 写出当前计数。结果在 `SMSM-native-captures/ambient-status.json`。开关在下一次 Present 消费，未消费请求不覆盖。开启诊断采集会关闭实验，保持诊断条件清楚。每次启动都默认关闭，不持久保存开启状态。

旧 r3/r2/r1 与原 r10 备份继续保留；停机更新回旧候选或按原恢复步骤回 r10。实机效果与性能待验收，日常默认尚未切换。

02:22（上海时间）确认游戏退出后，已停机安装 r4，摘要核对通过，默认关闭，设置保留。部署检查点和 r3 备份路径在本地 `artifacts/native-deployment/r4-ambient-deployment.json`。
