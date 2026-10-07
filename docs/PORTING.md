# 国际服着色器适配记录

目标客户端构建：`2026.09.15.0000.0000`。这是读取本机 `game/ffxivgame.ver` 得到的构建号，不是对未来补丁的兼容承诺。

## 当前状态

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
3. 用小键盘 0 开启 hunting，在需要分析的场景按一次 F8 抓帧。首批默认只导出渲染目标预览；它不能替代精确 DDS/常量缓冲区捕获。
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
