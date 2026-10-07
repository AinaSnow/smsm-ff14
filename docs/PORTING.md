# 国际服着色器适配记录

目标客户端构建：`2026.09.15.0000.0000`。这是读取本机 `game/ffxivgame.ver` 得到的构建号，不是对未来补丁的兼容承诺。

## 当前状态

2026-10-08：r5 出现按键无可见变化及无响应，已暂停测试。用户回退 r4 后正常，随后安装 r6 并确认辉光正常；客户端安装清单已核对为 r6。这是该场景的反馈，不代表全部效果或长期稳定性通过。新的颜色候选 `artifacts/preview-2026.09.15-r7-static25` 仅修改色调映射，固定混合 75% 游戏输出与 25% SMSM 输出；其余 8 个 shader、INI 和运行时 DLL 与 r6 完全一致，待实际颜色对比。r5 排查记录、r6/r7 验证步骤见文末。

首批代码已提交为 `1378a15`。第二批 `artifacts/preview-2026.09.15-r4` 已构建，共 13 个替换，覆盖当前捕获到的景深、反射、主光照法线阴影和输出抖动路径。新增效果通过离线检查，尚待实际安装后的画面和性能测试；不能将旧包抓帧中的阶段命中当作新效果已经验证。下表“首批测试包”及首次抓帧结果是历史记录，第二批处理见文末。

已完成离线提取、候选匹配、编译和首批接口检查。首批测试包已由用户通过管理员 PowerShell 安装；已从实际游戏进程确认加载游戏目录内的 d3d11.dll、d3dcompiler_46.dll 和 nvapi64.dll。用户进入场景并用 F9 对比后确认“有明显变化，画面正常”。这通过了首次加载和当前场景的基本目视检查；逐 shader 命中、其他场景、性能及 DLSS/FSR/TSCMAA 组合仍需验证。

shader 类别共有 319 个资源文件，提取出 34,309 份 DXBC，去重后为 31,018 份。哈希使用 3DMigoto 的 64 位无种子 FNV-1，且只覆盖 DXBC 数据，不包括 SHCD/SHPK 容器头。SHA-256 另用于完整性检查。

旧项目的 17 个哈希中有 8 个仍在资源包内。存在不代表当前画质设置下会执行；渲染调用需要游戏内确认。

| 旧哈希 | 当前结果 | 首批测试包 |
|---|---|---|
| `72a656dfd52149ad` | 原始字节码哈希仍存在，色调映射 | 包含 |
| `98b1bbd7925dc288` | 原始哈希仍存在，Bloom 提取 | 包含 |
| `5813cf7e6d426c37` | 原始哈希仍存在，Bloom 模糊 | 包含；修正 TEXCOORD0 为 float2 |
| `d0bcbd729a678569` | 原始哈希仍存在，Bloom 第二次模糊 | 包含；修正 TEXCOORD0 为 float2 |
| `a617dec7fe8f1603` | 原始哈希仍存在，Bloom 合成 | 包含 |
| `12dd4d7295446a19` | 原始哈希仍存在，输出抖动 | 包含 |
| `782e995758bf001d` | 原始哈希仍存在，暗角抖动 | 包含 |
| `c366310c6e0bd092` | 原始哈希仍存在，深度处理 | 暂不单独启用 |
| `0fed9c59a976fd24` | 对应新版 `91f970e6bbe57d99` | 已移植，包含 |
| `5867edfea21645a9` | 候选 `d6be0b6332618e80`，新增动态视口参数 | 待抓帧确认景深阶段 |
| `522bc90ae2005807` | 候选 `ad1c9b241ae204e1`，新增视图矩阵、Gather、深度上限 | 待重新适配 |
| `6dd11ec05e8b6088` | `1cabaa31b64f7f1b` 有相同 LUT 资源，新版增加 cLutParam.z 混合 | 保留游戏实现；旧文件主要是原样转写 |
| `b1cf3fdfc9a12624` | 旧三纹理混合方式不能直接用于新版候选 | 待抓帧确认 |
| `091dc34d666ac86f`、`5613235b3daabe76` | 无旧哈希；反射资源/算法需要重新定位 | 不包含 |
| `df9efe52325098cf`、`f7bc496f9f1b7e0d` | 无旧哈希；光照/阴影阶段需要重新定位 | 不包含 |

候选相似度只用于缩小搜索范围，不用于自动重命名或部署。尤其不能把最高分候选当作已确认映射。

## 本次代码修改

- 新增 `91f970e6bbe57d99-ps_replace.txt`：保留 SMSM 的 8 次抖动采样；新增 b0 动态视口常量，将径向模糊常量放到 b1；按新版反汇编保留 `saturate → xy 缩放 → zw 上限` 的纹理坐标处理；累加器显式初始化为零。
- 两个 Bloom shader 的入口 TEXCOORD0 从 float4 改为原始接口的 float2，其余输入寄存器保持一致。
- `Common.h` 的抖动模式 3 修正 `==` 为 `=`。默认模式仍是 4。
- 首批包仅包含经过审核的 8 个替换，独立使用 `SMSM-ShaderFixes`。不会自动把仓库所有旧替换放入新版客户端。

## 重现流程

需要 Windows、.NET 10 SDK、Python 3，以及项目自带的 x64 d3dcompiler_46.dll。Lumina 7.6.0 由 NuGet 还原。

在仓库根目录运行；输出目录必须是新目录。

```powershell
dotnet run --project tools/ShaderAudit -- 'E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online' artifacts/client-2026.09.15
python tools/compare_shaders.py artifacts/client-2026.09.15 ShaderFixes
python tools/shader_compile.py compile ShaderFixes artifacts/compile --dll "$PWD\d3dcompiler_46.dll"
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview
```

提取器只读取客户端，在工作区写出 `manifest.json` 与 DXBC。比较工具写出反汇编和候选报告。`artifacts/` 已加入忽略规则，不提交游戏原始资源。

打包器使用当前构建的白名单，核对原始 DXBC 的 FNV 和 SHA-256、重新编译源码，并检查资源槽位/类型、常量访问范围及输入输出签名。它不会证明游戏内实际执行或画面正确，也不以自动接口检查代替常量含义和布局的人工复核。

## 安装与回退

关闭游戏后运行：

```powershell
./tools/Install-Preview.ps1 -ClientRoot 'E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online' -Package artifacts/preview
```

脚本检查客户端构建号和包校验值，拒绝覆盖已有同名文件，并生成安装凭据。若启动失败，先关闭游戏，然后用相同包卸载：

```powershell
./tools/Install-Preview.ps1 -ClientRoot 'E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online' -Package artifacts/preview -Uninstall
```

卸载只移除凭据中列出且未被改动的文件，保留抓帧和日志。用户编辑过的文件会阻止自动卸载，需要先保存并核对。运行时依旧使用仓库自带 3DMigoto 1.3.11，已确认能加载到当前客户端，长期稳定性仍待验证。

本次实际安装使用的包是 `artifacts/preview-2026.09.15-r2`；卸载时应指定这个包。游戏目录需要管理员写权限时，请在管理员 PowerShell 执行安装或卸载命令，不必修改目录 ACL。

若 hunting 文字和 F9 正常，但 F8 不生成 `FrameAnalysis-*` 目录，先检查目录写权限。本机的 game 目录 ACL 授权给旧 Windows 账号 SID，当前账号只通过 Everyone 获得读取权限。可在管理员 PowerShell 使用 `tools/Enable-FrameCapture.ps1 -ClientRoot <客户端根目录> -UserSid <运行游戏的用户 SID>`，只添加目录本身的 CreateDirectories 权限，不传播到现有文件。该脚本保存 `artifacts/capture-permission.json`；抓帧完成后用相同参数加 `-Revoke` 撤销这条授权。不要把整个游戏目录改成 Everyone 完全控制。

已通过的检查：18 个替换源码使用 d3dcompiler_46 编译；首批 8 个替换通过打包器全部检查；抖动模式 3 单独编译，并确认修正赋值后字节码发生变化；`tools/Test-Preview.ps1` 验证版本不匹配、文件碰撞、用户修改保护及安装/卸载流程。

## 首次实际抓帧结果

捕获目录：`game/FrameAnalysis-2026-10-08-020711`。创建子目录权限修复后，F8 成功生成 3,946 张渲染目标预览，以及 `log.txt` 和 `ShaderUsage.txt`。验证摘要保存在工作区 `artifacts/frame-validation.json`，包含捕获日志 SHA-256 和具体 draw 编号。

| 测试包着色器 | 本帧的输出 draw 编号 |
|---|---|
| 色调映射 `72a656dfd52149ad` | 1758 |
| Bloom 模糊 `5813cf7e6d426c37` | 1747、1748 |
| Bloom 第二次模糊 `d0bcbd729a678569` | 1744、1746 |
| Bloom 合成 `a617dec7fe8f1603` | 1749 |
| 更新后的径向模糊 `91f970e6bbe57d99` | 1751、1752、1753 |
| 暗角抖动 `782e995758bf001d` | 1770 |
| Bloom 提取 `98b1bbd7925dc288` | 本帧未使用；实际使用 `7a34722c12f5794d` |
| 输出抖动 `12dd4d7295446a19` | 本帧未使用，当前管线的适配仍未完成 |

重要发现：本帧 Bloom 提取变体 `7a34722c12f5794d` 在输入 RGB 上新增 `sqrt`，不可直接使用旧版不带该步骤的代码。`afe77c8a06f4c15c` 虽然与旧输出 shader 的指令相似，但实际是色调映射前的 soft-focus/glare 参数处理：alpha 来自 `cSoftFocusParam.glareCompositeRate`，不能当成最终输出抖动阶段。当前 LUT 阶段为 `33055a94eacb90ff`，另有暗部颜色矩阵和参数，不能覆盖成旧单矩阵版本。

已查看 draw 1772 的场景输出，图像完整；结合用户 F9 对比确认，首批画面基本正常。单帧不能证明所有效果、天气、场景或抗锯齿设置均已兼容。第二批补充景深、反射、阴影和当前管线的输出抖动实现，验证状态单独记录如下。

重现捕获分析：

```powershell
python tools/analyze_capture.py 'E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online\game\FrameAnalysis-2026-10-08-020711' artifacts/client-2026.09.15 artifacts/preview-2026.09.15-r2 artifacts/frame-validation.json
```

## 游戏内验证

1. 启动进入场景，确认画面和 UI 正常。按住 F9 临时显示原始效果，松开恢复替换；F10 重载。若键位未生效，先按小键盘 0 开启 hunting。
2. 对比明亮户外、夜晚、室内和强光源，检查肤色、天空渐变、Bloom、暗角以及 UI。记录抗锯齿、升频和动态分辨率设置。
3. 新构建默认关闭 F8；仅在需要诊断时用 `--capture` 构建独立抓帧包，再用小键盘 0 开启 hunting、按一次 F8，等待完成，不连续触发。抓帧只导出渲染目标预览；它不能替代精确 DDS/常量缓冲区捕获。历史 r2/r4/r5 包仍保留各自原有抓帧绑定。
4. 对选定目标按需启用 `dump_tex`、`dump_cb` 和 DDS，再核实景深、反射、法线和深度含义。不要在未知阶段直接套用旧阴影实现。
5. 对实际可用的 FSR、DLSS、TSCMAA、动态分辨率组合分别验证。全部完成前保持 `runtime_verified=false`。

参考：[3DMigoto 哈希实现](https://github.com/bo3b/3Dmigoto/blob/master/util.h)、[原项目](https://github.com/s-ilent/smsm-ff14)。

## 第二批：当前渲染路径

依据用户开启景深后的 `FrameAnalysis-2026-10-08-021615`，重新定位实际调用。旧 `d6be0b6332618e80` 和 `762c17c406a1cd4f` 候选未在这帧执行，不能代表当前 /gpose。

| 效果 | 第二批实现 | 旧包抓帧中的定位证据 |
|---|---|---|
| 景深散景 | `00f2b6068017c6c6`，为当前双层模糊的每个 tap 增加 ±10° 角度采样，16 → 48 次采样，保留原 CoC 权重和 alpha | draw 2370–2373 |
| 反射采样 | `4caad0714bdcc47e`，仅在最终反射颜色查询增加六纹素范围内的抖动，保留 Hi-Z 步进、命中判定、材质遮罩、距离衰减与 alpha | draw 2192 |
| 法线阴影 | `e9f57e0834b642f5` / `8b384acd7a03c836`，24 步法线积分，按新版深度重建和世界到视图法线变换采样 | 日志 draw 1735 / 2000；没有对应 JPG，但存在实际 Draw 调用 |
| 输出抖动 | `23d27700572e0c4d`，色调映射后启用，保留 RGB 的 NaN 清理和 alpha | 早期 draw 2334 禁用，最终 draw 2413 启用；普通场景对应 1692 / 1772 |

新版景深的 CoC 生成、前后景分离、两级合成继续由游戏负责，保留手动焦点和近远模糊参数。旧版的中心/边缘混合 hack 不适用于新的五纹理合成。散景保留 SMSM 增加采样以平滑光斑的意图，并非逐像素复刻旧版外观。

旧 `522bc90ae2005807`、`c366310c6e0bd092`、`6dd11ec05e8b6088`、`5613235b3daabe76`、`f7bc496f9f1b7e0d` 的有效主函数基本是原处理的转写；其探索代码多在注释或未调用函数中。这里保留当前游戏的深度、LUT、反射模糊和阴影贴图处理。`7a34722c12f5794d` 的新 Bloom 提取同样保留，避免丢失新增 sqrt。真正的额外法线阴影移入当前主光照阶段。

复杂光照与反射采用局部 ASM 插入，由 `tools/patch_shader_asm.py` 生成。先以原始 DXBC 验证反汇编/汇编后的指令字节完全一致，再插入独立临时寄存器中的效果；新资源与常量读取不能超出宿主绑定。这样无需依赖反编译器重新生成数百条材质/云影/散射指令。生成的游戏原始字节码和完整 ASM 留在被忽略的 artifacts 中，不提交到仓库。

输出 shader 是复用的拷贝，不能全局加噪点。独立包启用 `ini_params=120` 并保留 `x` 作为阶段标记：色调映射设置 1，目标拷贝消费后置 0，Present 再次复位。分析工具按实际调用顺序重放，确认两份捕获都跳过早期拷贝。标记的运行时行为仍需要新包抓帧确认。新增抖动去除了旧公式的均值偏移，黑白端点渐隐；位运算判断 NaN，避免编译器在 /O3 下消除 `isnan()`。

### 构建与离线验证

额外需要 [3DMigoto 官方 cmd_Decompiler 1.3.16](https://github.com/bo3b/3Dmigoto/releases/tag/1.3.16)。本次下载的 `cmd_Decompiler-1.3.16.zip` SHA-256 为 `5e72e067dfcb15c36f106efa74d805055eec5314dc84b8fca8e65d835683a1b2`，解压到 `artifacts/decompiler/1.3.16`。该工具只参与离线构建，客户端仍使用项目原有的 1.3.11 DLL。

```powershell
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview-extended --extended --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/validate_d3d11.py artifacts/preview-extended
./tools/Test-Preview.ps1 -Package artifacts/preview-extended
```

已通过：13 个 shader 哈希/接口检查；两个新增 HLSL 无编译警告；3 个 ASM 插入的原指令逐字节往返检查及修改后的汇编验证；13 个 shader 的 D3D11 WARP CreatePixelShader；r4 安装、版本拦截、同名文件保护、修改文件保护和卸载测试。WARP 创建检查只证明字节码能创建，不能证明画面或帧率。

实际待测包为 `artifacts/preview-2026.09.15-r4`。`r3`、`r3b`、`r3c` 都是构建中间产物，不用于安装。升级先关闭游戏，用首批 `r2` 包执行 `Install-Preview.ps1 -Uninstall`，再用 r4 执行安装。回退则先用 r4 卸载，再安装 r2；保留两份包及各自安装清单。

仍需验证：同一场景 F9 对照、/gpose 前后景和焦点滑块、反射表面、主光源阴影及帧率。当前实现只覆盖捕获确认的路径，其他画质下的 shader 变体及 DLSS/FSR 组合不视为已验证。新增采样可能增加 GPU 时间，若明显掉帧应先回退再按效果拆分测量。

## SDR 辉光恢复与画面校准（r5）

**当前状态：暂停安装和继续测试 r5。** 用户在安装后反馈绿色 hunting 文字可见，但 F6/F7/F9 没有可见变化，随后游戏无响应。离线检查不代表运行稳定。已确认当时安装文件与 r5 清单一致；用户授权结束游戏，现已回退 r4 并确认正常。r4 的偏白和台灯光晕减弱仍是已知问题。

同一会话留下 `FrameAnalysis-2026-10-08-024827` 和 `024828` 两份抓帧：前者日志标记 `Frame analysis aborted`，后者执行到 draw 2243。第二份包含 tone mapping draw 1936，以及输出拷贝 draw 1877 / 1951；日志实际记录了输出阶段 x 参数的复位、置 1、再次复位。该证据不能证明 F6/F7 的 y 参数变化、替换着色器最终输出正确，也不能确定无响应根因。抓帧与无响应发生在同一时段，应先在不抓帧的情况下恢复基本操作，避免连续按 F8。

回退前关闭游戏，使用 `preview-2026.09.15-r5-sdr-final` 执行卸载，再安装原封保留的 `preview-2026.09.15-r4`。安装脚本会核对清单并保留抓帧记录。游戏目录需要管理员写权限时，在管理员 PowerShell 使用 `powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "<安装脚本路径>"`；该执行策略只作用于这次子进程。下文保留实现和离线验证记录，不代表恢复推荐安装。

用户确认 Windows HDR 和自动 HDR 均关闭。截图 `023516`（SMSM）与 `023520`（原版）中人物肤色/头发的明暗层次不同；室内 `023715` 有明显台灯光晕，`023711` 光晕减弱。人物姿势并不完全一致，不能将两张图直接相减当成精确光照测量。

发现旧 Bloom 合成检查 `DisableWhitening`，而配置定义 `UseOriginalWhitening`；已统一名称，编译验证开启后与原版合成函数的指令字节一致。为了同时排除旧模糊采样范围和能量变化，校准包不部署 Bloom 提取、两次模糊和合成这 4 个替换，整条 Bloom 使用游戏实现。其余景深、反射、法线阴影、径向模糊和抖动保留。

色调映射加入 `TONEMAP_SMSM_PERCENT`。0% 与原版函数编译出的指令字节一致；100% 与此前 SMSM 二进制指令一致。校准包暂定 25%，在同一场景输入上混合原版曝光/LUT 曲线与 SMSM 曲线，不是统一压低输出亮度。25% 是人工对比的起点，不是经显示器测量得出的最终参数。

校准包额外启用 t120 的 y 通道作为曲线比较开关，x 仍用于最终输出抖动。F6 将 y 置 0（原版色调曲线），F7 将 y 置 1（25% SMSM），均为按一次切换；F9 仍是按住临时绕过所有替换。F6 不等于关闭 SMSM，不能用它验证原版景深/阴影。INI 插入现已严格匹配真正的节标题，防止向注释里的 `[Constants]` / `[Present]` 字样后写入活动命令。

### 构建和检查

```powershell
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview-sdr --extended --look calibrated --tonemap-percent 25 --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/test_calibration.py
python tools/validate_d3d11.py artifacts/preview-sdr
./tools/Test-Preview.ps1 -Package artifacts/preview-sdr
```

已通过色调映射两端的编译指令等价检查、Bloom 开关检查、INI 节位置检查、9 个 shader 的接口与 D3D11 WARP 创建检查，以及新包的安装/卸载与文件保护测试。旧头文件仍有既有的向量截断等编译警告；未将这些检查表述为无警告或已完成画面验证。

此前实际安装包为 `preview-2026.09.15-r5-sdr-final`，目前暂停安装。`r5-calibrated`、`r5-sdr` 是中间构建，不用于安装。保留该包及其清单用于卸载，不修改已有包。

### 对比顺序与验收目标

1. 保持 Windows HDR/自动 HDR 关闭。先保持现有游戏亮度、显示器亮度/对比度和 ICC 不变，避免同时调整多个环节。
2. 用同一个相机位置、同一个角色姿势和光照进行对比；/gpose 暂停动作，颜色滤镜保持标准，手动亮度设置一致。停下镜头后等曝光稳定再截图。
3. 半室内台灯场景先按 F6，再按住 F9 比较：确认灯芯周围的光晕恢复。两者还有阴影等其他效果差别，不能要求逐像素相同。发光灯芯本身可以饱和，不能以灯芯不过曝作为唯一标准。
4. 同一个白衣/肤色场景比较 F6 和 F7：衣服折纹和脸部明暗应保留，头发不应变成大片平白；同时检查树阴、墙角，避免为了压白而丢失暗部细节。
5. 再检查晴天、暖灯室内、夜景。不要通过消除场景本身的暖色光来追求“中性灰”。每轮只改色调混合强度，记录场景和按键状态。F7 仍偏白时可构建更低比例；F6 仍有问题时，应检查其他替换而非继续调曲线。

这里首先校准游戏渲染外观。PNG 对照不能测量显示器实际亮度、白点或生成可靠 ICC。如果原版游戏、桌面照片和灰阶都明显异常，再使用 Windows 的“校准显示器颜色”向导检查 gamma、亮度、对比度和色彩平衡；不建议为了修复单个 shader 的偏白去改全系统 gamma。参考：[Microsoft 显示器颜色校准说明](https://www.microsoft.com/en-us/windows/learning-center/how-to-color-calibrate-your-monitor)。若以后开启 HDR，需单独重新验证，可使用 [Windows HDR Calibration](https://support.microsoft.com/en-us/windows/hardware/display-graphics/calibrate-your-hdr-display-using-the-windows-hdr-calibration-app)，不能直接沿用这次 SDR 结论。

## r6：单独恢复原版 Bloom

测试包：`artifacts/preview-2026.09.15-r6-game-bloom-final`。移除 r4 的四个 Bloom 替换，其余九个编译二进制与 r4 的 SHA-256 全部一致，三个运行时 DLL 也逐字节一致。仍使用 100% SMSM 色调映射，不含 r5 的 y 参数或 F6/F7 切换，因此这一步不解决肤色偏白。INI 保留精确节标题插入修正和输出抖动 x 标记。

新构建默认关闭 F8 抓帧入口；诊断时才显式传 `--capture`。安装完成提示也按实际 INI 显示抓帧是否启用，兼容旧包。关闭抓帧只是减少测试变量，不等于已经确认或修复无响应的根因。

```powershell
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview-bloom-only --extended --look game-bloom --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/validate_d3d11.py artifacts/preview-bloom-only
./tools/Test-Preview.ps1 -Package artifacts/preview-bloom-only
```

已通过：原始 hash 与接口检查、ASM 原指令往返、9 个 shader 的 WARP 创建、安装/卸载和文件保护测试。额外核对删除的恰好是四个 Bloom hash、保留 shader 与 r4 二进制一致、运行时 DLL 不变、F8 和 F6/F7 均无绑定。摘要位于 `artifacts/r6-baseline-validation.json`。用户现已确认 r6 辉光正常；失败构建 `preview-2026.09.15-r6-game-bloom` 没有完整清单，不可安装。

安装顺序：退出游戏，用 r4 包卸载，再安装 r6 final；回退则反向操作。游戏目录需管理员权限。不要覆盖已安装文件，也不要在游戏运行时热换 DLL。进入半室内台灯场景，先确认能正常操作，再开启 hunting、按住和松开 F9 比较灯芯周围光晕。F9 按住是原版、松开是 SMSM；其他保留效果仍会产生差异。只需普通截图，暂不抓帧。待确认光晕和稳定性后，再单独验证静态色调混合，避免同时引入动态按键控制。

## r7：颜色路径检查与固定色调混合

代码检查结论：

- `COLORTONE=0`、`PSATURATION=0`、`CUBICCONTRAST=0`，目前没有启用旧配置中的去绿偏色、全局饱和度和附加对比度。不能因为头文件中存在这些参数就认为它们正在影响画面。
- `TONEMAP_EVILS=1` 的实际主函数是对 R/G/B 分别调用 `genericTonemap`，再除以公共白点；`EVILS(color)` 调用仍在注释中。它并没有执行头文件里的完整 EVILS 颜色重建。非线性逐通道映射会改变通道比例，有产生色相/饱和度偏移的条件，尤其在高光压缩区域。
- 100% SMSM 路径绕过原版 `cCommonTexParam.y` 曝光乘法和本阶段的 t1 tone LUT。后续游戏颜色处理仍保留，不能把这一点描述为移除了游戏全部 LUT。原版路径已与当前客户端反汇编逐步核对。
- 暗角 shader 沿用游戏提供的暗角 RGB，只对 alpha 加抖动；当前输出抖动有每通道 ±1/255 限幅和端点渐隐，并不等于全局色温滤镜。景深/反射/法线阴影仍会间接改变局部亮度，本次不修改它们。

这些是代码层面的原因和风险，不能仅凭旧截图断言每个像素的偏色来源。r7 使用现有 `GameToneMap` 与 SMSM 输出的固定混合：75% 游戏 + 25% SMSM，不新增饱和度、白平衡或色相旋转。数学上是在该 shader 输出处将相对游戏输出的 RGB 差值缩小为 1/4；不能声称最终感知色差或色相误差也精确降低 75%，更不能声称完全保色相。

```powershell
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview-color-static --extended --look calibrated-static --tonemap-percent 25 --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/test_calibration.py
python tools/validate_d3d11.py artifacts/preview-color-static
./tools/Test-Preview.ps1 -Package artifacts/preview-color-static
```

实际候选 `artifacts/preview-2026.09.15-r7-static25` 通过 9 个 shader 的接口和 WARP 创建检查，以及安装/卸载保护测试。测试验证 0% 与原版转写函数的编译指令一致、100% 与原 SMSM 编译指令一致；25% 保留 t1/s1 游戏 tone LUT，编译结果不读取 t120 参数。保留的另外 8 个 shader、d3dx.ini 和三个运行时 DLL 与 r6 逐字节一致；`artifacts/r7-color-validation.json` 保存检查摘要。F6/F7 和 F8 仍关闭，输出抖动原有的 t120.x 阶段标记继续保留。这不代表已解决 r5 无响应根因。

退出游戏，用 r6 final 卸载后安装 r7 static25；回退时使用相反顺序及各自清单。以普通截图对比白衣褶皱、肤色红润程度、浅蓝头发/衣料、草木绿与暖灯场景。保持 HDR 关闭、标准滤镜、固定镜头和曝光，不同时修改显示器或游戏亮度。按住 F9 显示全原版、松开显示候选；F9 同时绕过其他效果，不是严格仅隔离色调映射。先观察是否比此前 SMSM 的平白感减轻，并确认 r6 已恢复的辉光仍正常。25% 尚无实际视觉验收；若仍需更接近原版，可独立构建更低比例，避免一次改变多个颜色参数。
