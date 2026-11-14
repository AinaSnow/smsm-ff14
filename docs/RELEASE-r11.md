# r11.1 — SMSM 3DMigoto 画质包

2026-11-14。国际服客户端 `2026.11.03.0000.0000`（shader 与 2026.09.15 / 2026.10.06 完全一致，见下）。
运行库：官方 3DMigoto 1.3.16。r11.1 与 r11 的画面效果完全相同；新增双击安装，**不需要安装 Python**，也不再因游戏版本不同而拒绝安装。

每一项都在游戏内由用户对比后选定默认值，每项都有开关。关闭后的离线结果（WARP）：光束、法线阴影与游戏 shader 逐位一致；
景深与游戏差 ≤ 1.4e-6；抖动、锐化关闭时与未加该项的版本逐位一致。色调没有“原版”档，只能切回 R10（50% 混合）。
用户实际游玩确认帧率可接受（未记录具体数字）；未做长时间稳定性测试。

## 默认效果

| 效果 | 默认 | 说明 | 记录 |
|---|---|---|---|
| 色调 | A | 100% SMSM 曲线作用于最大通道、保持色相；亮灯与彩色玻璃不再一片白 | [TONE-PRESETS-T1](TONE-PRESETS-T1.md) |
| 去色带抖动 | 开 | ±1/255 噪点，消除天空和暗部的色阶条纹；放在色调 shader 内 | [DITHER-T2](DITHER-T2.md) |
| 锐化 | 轻 | 半径 2 反锐化，亮处（灯、太阳附近）自动减弱 | [SHARPEN-S1](SHARPEN-S1.md) |
| 光束 / 径向模糊 | SMSM | 8 次带抖动采样；太阳光芒更柔、更长 | [RADIAL-T2](RADIAL-T2.md) |
| GPose 景深散景 | 强 | 亮采样在颜色平均中权重更大，焦外灯光更亮更饱满；分层与边缘不变 | [DOF-D1](DOF-D1.md) |
| 法线阴影 | 开 | 太阳光下衣褶、石缝等处补充贴合表面的细节阴影 | [SHADOW-N1](SHADOW-N1.md) |

保留游戏原版：Bloom（检查无明显问题）、反射（用户认为还行）。

## 按键（不需要 hunting）

| 按键 | 作用 |
|---|---|
| Ctrl＋F7 | 显示 / 隐藏左上角标签：A（色调）D（抖动）S（锐化）R（光束）B（散景）N（法线阴影） |
| Ctrl＋F8 | 色调 A / R10 |
| Ctrl＋F6 | 抖动 开 / 关 |
| Ctrl＋F4 | 锐化 关 / 轻 / 中 / 强（S：绿 = 轻、浅蓝 = 中、橙 = 强） |
| Ctrl＋F5 | 光束 SMSM / 游戏 |
| Ctrl＋F2 | GPose 散景 关 / 普通 / 强（B：淡黄 = 普通、橙 = 强） |
| Ctrl＋F1 | 法线阴影 开 / 关 |
| Ctrl＋F3 | 诊断：GPose 模糊 pass 染紫（仅测试用） |
| Ctrl＋F11 | 诊断：去除太阳直射（仅测试用） |

开关状态不保存，重启游戏回到上表默认值。标签默认隐藏；截图对比时建议先按 Ctrl＋F7 显示标签，确认各项当前档位。

### 修改按键

按键写在游戏目录 `game/d3dx.ini` 末尾，与其他软件或游戏快捷键冲突时可改对应段落的 `key =` 一行（3DMigoto 语法，
例如 `key = ctrl shift no_alt VK_F8`），保存后重启游戏生效。用管理器重新安装或回退会恢复为包内原值。

| 段落 | 默认按键 | 控制 |
|---|---|---|
| `[KeySMSMCompareLabel]` | Ctrl＋F7 | 标签 |
| `[KeySMSMTonePreset]` | Ctrl＋F8 | 色调 |
| `[KeySMSMDither]` | Ctrl＋F6 | 抖动 |
| `[KeySMSMSharpen]` | Ctrl＋F4 | 锐化 |
| `[KeySMSMRadial]` | Ctrl＋F5 | 光束 |
| `[KeySMSMBokeh]` | Ctrl＋F2 | GPose 散景 |
| `[KeySMSMNormalShadow]` | Ctrl＋F1 | 法线阴影 |
| `[KeySMSMBokehDiagnostic]` | Ctrl＋F3 | 散景诊断 |
| `[KeySMSMNormalShadowDiagnostic]` | Ctrl＋F11 | 法线阴影诊断 |

想改默认档位：修改同文件 `[Constants]` 中的启动值（x7 色调 0 = R10 / 1 = A；z7 抖动；x6 锐化 0–3；w7 光束；
y6 散景 0–2；x5 法线阴影；y7 标签）。

## 安装（双击）

ZIP 自带官方嵌入式 Python 3.13.17（`python` 文件夹，来自 python.org，校验值与官方一致），**不需要另外安装 Python**。

1. 退出游戏，把 ZIP 解压到任意文件夹。
2. 双击 **`Install.cmd`**。它会：
   - 自动找到游戏目录（XIVLauncher 配置 → Steam 库 → Square Enix 默认路径）；
   - 检查游戏已退出；游戏版本与本包验证过的版本不同时只提示、照常安装（原因见下“游戏更新后”）；
   - **自动关闭 Dalamud 外部窗口**（`IsDisableViewport=true`，否则 3DMigoto 会崩溃），只在需要时修改并备份原配置；
   - 把包复制到 `%LOCALAPPDATA%\SMSM`，之后解压的文件夹可以删除；
   - 安装全部默认效果，并备份安装前的游戏文件。
3. 启动游戏即生效。

| 文件 | 作用 |
|---|---|
| `Install.cmd` | 安装 / 重装全部默认效果 |
| `Status.cmd` | 查看游戏目录、版本是否匹配、已装效果 |
| `Uninstall.cmd` | 卸载，恢复游戏原版文件（Dalamud 窗口设置保持关闭） |
| `Rollback.cmd` | 撤销上一次安装 / 卸载 / 回退 |

自动找不到游戏时，在命令行运行 `Install.cmd --client-root "<含 game 文件夹的游戏根目录>"`。
只装运行库、不启用效果：`Install.cmd --profile vanilla`。

### 手动安装（高级）

```powershell
python tools/configure_compat_viewports.py --config "$env:APPDATA\XIVLauncher\dalamudConfig.json" --backup '<备份目录>' --game '<客户端目录>\game'
python tools/manage_preview.py install --client-root '<客户端目录>' --package '<解压目录>\package' --profile daily --backup-root '<备份目录>'
```

手动安装需要系统里的 Python 3.10+，管理器直接从解压目录读取文件，需保留该目录；命令行管理器仍会在游戏版本不同时拒绝安装。更多命令见 [MANAGEMENT](MANAGEMENT.md)。

## 游戏更新后

游戏更新后不需要等新包：3DMigoto 按 shader 内容哈希替换。更新没改动的 shader，效果照常；更新改动了某个被替换的
shader，对应效果自动失效，不会替换到错误的 shader 上，也不会因此出错。所以 `Install.cmd` 在游戏版本与本包验证过的版本
不同时只提示、照常安装，`Status.cmd` 会注明“当前游戏版本未验证”。若某个效果在更新后消失，说明该 shader 被改动，
需要等维护者重新适配。

维护者流程（需要 .NET 10 SDK）：`python tools/check_client_update.py --client-root <游戏根目录> --package <当前包> --previous <上次提取>`
会重新提取全部 shader 并对比；被替换的 shader 全部未变时自动重标签并生成新 ZIP，有变化时停止并列出受影响的效果
（这些效果需要重新适配，不能重标签）。2026.10.06 与 2026.11.03 均已按此流程确认：31,018 个 shader 与 2026.09.15 完全一致。

## 已知限制

- 帧率经用户游玩确认可接受，但没有逐项测量；未做长时间稳定性测试。新增成本主要在：锐化 13 次采样（全屏一次）、
  法线阴影每个受阳光像素 24 步（48 次采样）、光束 8 对 4 次采样；景深散景不增加采样。
- 散景是“更亮更饱满”，不是硬边圆盘；硬边圆盘需更换采样核（未做）。
- 色调 A 比 R10 略亮。锐化轻档仍可能放大雨天湿地上的细碎反光。
- Dalamud 窗口必须留在游戏内（安装程序会自动设置）。
- 数据目录（`%LOCALAPPDATA%\SMSM`）路径过长（超过约 130 个字符）时安装程序会拒绝运行，避免触及 Windows 260 字符路径限制。

## 更新记录

- **r11.1（2026-11-14）**：客户端 2026.11.03（shader 未变，重标签）；新增双击安装 / 卸载 / 回退 / 状态，自动查找游戏目录、
  自动设置 Dalamud 窗口、包复制到 `%LOCALAPPDATA%\SMSM`（解压目录可删）；自带嵌入式 Python，不再需要安装 Python；
  游戏版本不同时不再拒绝安装；维护者一键更新检查。画面效果与 r11 相同。
- **r11（2026-10-14）**：首个最终版。

## 校验

ZIP 附带 `SHA256SUMS.json`（逐文件）和 `.sha256`（整包）。包清单 `package/SMSM-preview.json` 记录每个 shader 的原始
与编译后 SHA-256、各效果在游戏内证明执行的依据，以及来源包。

## 来源与许可

源自 [Silent's Messy Shader Mod](https://github.com/s-ilent/smsm-ff14)。项目部分遵循 MIT；3DMigoto 遵循 GPLv3，
对应源码见 [官方 1.3.16 标签](https://github.com/bo3b/3Dmigoto/tree/1.3.16)。
自带的嵌入式 Python 遵循 PSF License（见 `python/LICENSE.txt`）。
