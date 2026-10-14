# r11 — SMSM 3DMigoto 画质包

2026-10-14。国际服客户端 `2026.10.06.0000.0000`（shader 与 2026.09.15 完全一致，见下）。
运行库：官方 3DMigoto 1.3.16。下载：GitHub Release `r11` 的 `smsm-r11.zip`（附整包 `.sha256`）。

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

## 安装

前提：Python 3.10+；**Dalamud 必须关闭外部窗口（`IsDisableViewport=true`）**，否则 3DMigoto 会在额外窗口的
DirectComposition 路径崩溃（1.3.11 与 1.3.16 均如此），见 [3DMIGOTO-COMPATIBILITY](3DMIGOTO-COMPATIBILITY.md)。

将 ZIP 解压到独立目录（不要直接复制进游戏目录），**退出游戏**后：

```powershell
python tools/configure_compat_viewports.py --config "$env:APPDATA\XIVLauncher\dalamudConfig.json" --backup '<解压目录>\dalamud-backup' --game '<客户端目录>\game'
python tools/manage_preview.py install --client-root '<客户端目录>' --package '<解压目录>\package' --profile daily
python tools/manage_preview.py status --client-root '<客户端目录>'
```

不加 `--profile daily` 时默认零替换（只装运行库）。保留解压目录，管理器从该目录读取文件。

## 回退与卸载

每次安装都会输出备份目录；退出游戏后：

```powershell
python tools/manage_preview.py rollback --client-root '<客户端目录>' --backup '<备份目录>'
python tools/manage_preview.py uninstall --client-root '<客户端目录>'
```

只想临时看原版：用上表按键逐项关闭即可（色调按 Ctrl＋F8 切到 R10 仍是 50% SMSM 混合，不是纯原版）。
更多命令见 [MANAGEMENT](MANAGEMENT.md)。

## 游戏更新后

管理器发现客户端版本变化会拒绝安装。先用 ShaderAudit 重新提取 shader 并对比；只有被替换的 shader 全部未变时，
才用 `tools/retarget_client_build.py` 复制包并更新版本标签（文件不变）。2026.10.06 即按此流程：31,018 个 shader 与
2026.09.15 完全一致。被替换的 shader 有任何变化时必须重新适配，不能重标签。

## 已知限制

- 帧率经用户游玩确认可接受，但没有逐项测量；未做长时间稳定性测试。新增成本主要在：锐化 13 次采样（全屏一次）、
  法线阴影每个受阳光像素 24 步（48 次采样）、光束 8 对 4 次采样；景深散景不增加采样。
- 散景是“更亮更饱满”，不是硬边圆盘；硬边圆盘需更换采样核（未做）。
- 色调 A 比 R10 略亮。锐化轻档仍可能放大雨天湿地上的细碎反光。
- Dalamud 窗口必须留在游戏内（见上）。

## 校验

ZIP 附带 `SHA256SUMS.json`（逐文件）和 `.sha256`（整包）。包清单 `package/SMSM-preview.json` 记录每个 shader 的原始
与编译后 SHA-256、各效果在游戏内证明执行的依据，以及来源包。

## 来源与许可

源自 [Silent's Messy Shader Mod](https://github.com/s-ilent/smsm-ff14)。项目部分遵循 MIT；3DMigoto 遵循 GPLv3，
对应源码见 [官方 1.3.16 标签](https://github.com/bo3b/3Dmigoto/tree/1.3.16)。
