# 国际服着色器适配记录

目标客户端构建：`2026.09.15.0000.0000`。这是读取本机 `game/ffxivgame.ver` 得到的构建号，不是对未来补丁的兼容承诺。

## 当前状态

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

已查看 draw 1772 的场景输出，图像完整；结合用户 F9 对比确认，首批画面基本正常。单帧不能证明所有效果、天气、场景或抗锯齿设置均已兼容。景深、反射、阴影和当前管线的输出抖动仍属于后续适配内容。

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
