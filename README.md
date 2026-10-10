# SMSM — FF14 原生 shader 画质改进

当前计划：[回归 3DMigoto（2026-10-10）](docs/PLAN-3DMIGOTO-RETURN-2026-10-10.md)。
执行记录与恢复说明：[3DMigoto / Dalamud 兼容候选](docs/3DMIGOTO-COMPATIBILITY.md)。

开发起点是已发布 **r10**，固定 50% 色调；保留游戏 Bloom 和景深。
新分支 `feature/3dmigoto-dalamud-compat` 从 r10 开始，ReShade/原生灯光研究已冻结。
历史源码和未完成冷光校准位于 `archive/reshade-native-lighting-2026-10-10`，
原工作区及忽略的配置、画面、GPU 数据、插件包和安装备份留在原位置。

## 当前快捷对比版

当前已部署 [H3](docs/TONE-HIGHLIGHTS-H3.md)：Ctrl＋F8 对比 r10 / H3，Ctrl＋F7 隐藏标签。
根据 H1 实景过压问题，H3 提高起点并将 RGB 衰减限制为最多 6%，取消固定输出上限。
启动默认 r10；离线验证通过，新版实景收益待确认。保留窗口在游戏内的兼容设置。

## c2 基线记录

`r11-compat-c2` 使用官方 3DMigoto 1.3.16，复用 r10 色调二进制。
**必须关闭 Dalamud 的外部窗口功能（`IsDisableViewport=true`）。**
独立复现发现 1.3.11 和 1.3.16 都会在额外窗口的 DirectComposition
`SetContent` 路径崩溃，升级本身没有解决该问题。
用户已接受暂时将 Dalamud 窗口留在游戏内。此前客户端安装此候选并开启色调；
用户已反馈本轮不会崩溃、色调初步看起来正常；Dalamud 窗口操作正常，切图及其他分项仍待确认，不是稳定版发布。

候选包默认 `vanilla`（零替换），只提供 `daily`（色调）作为另一预设。
其他历史效果没有加入此候选。Hunting、导出、持续详细日志均关闭。
使用管理器安装和回退；不要将仓库根目录或官方 hunting 配置直接复制进游戏。
原 r10 标签、ZIP 和校验值保持不变。

## 构建与管理

```powershell
python tools/build_compat_preview.py <r10-package> <official-3Dmigoto-1.3.16.zip> <new-output>
python tools/validate_d3d11.py <new-output>
```

构建器固定检查 r10 清单和官方运行库 ZIP 的 SHA-256；拒绝覆盖输出目录。
安装前按[兼容说明](docs/3DMIGOTO-COMPATIBILITY.md)设置 Dalamud。
通用安装、选择和回退命令见[管理说明](docs/MANAGEMENT.md)。
DLL 切换必须退出游戏；当前候选的 F9/F10 行为尚未实测。

## 后续顺序

先完成兼容验收与 r10 恢复，再选择一个明确的画面问题开展单项改进。
原 [ROADMAP](docs/ROADMAP.md) 与灯光研究计划仅作为历史，不继续执行其待办。

## 来源与许可

源自 [Silent's Messy Shader Mod](https://github.com/s-ilent/smsm-ff14)。
项目适用部分遵循 [MIT](LICENSE)；3DMigoto 遵循 [GPLv3](COPYING)，
对应源码见 [官方 1.3.16 标签](https://github.com/bo3b/3Dmigoto/tree/1.3.16)。

H1/H2 保留为历史候选；H3 沿用比较按键，默认关闭，实景收益待确认。
