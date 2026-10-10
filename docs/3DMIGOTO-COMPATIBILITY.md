# 3DMigoto / Dalamud 兼容记录

2026-10-10。R0 已完成，R1 配置规避候选已部署，用户暂时无法进行实机检查。
R1 完整验收、R2 稳定恢复及 R3 新效果仍未完成。本记录不宣布运行库问题已修复。

## 保存与分支

- 原支线：`feature/native-lighting-reshade-diagnostics`，原 HEAD `0569ea7`。
- 归档：`archive/reshade-native-lighting-2026-10-10`，未完成工作保存提交 `0283d03`。
  包括 0.3.0 冷光定点校准、材质目标、状态发布和测试修改；未继续开发、未部署该版本。
  归档入口冻结标记为后续提交 `953e17e`；完整 Git 历史另保存为原工作区
  `artifacts/archive-2026-10-10/reshade-native-lighting.bundle`，`git bundle verify` 通过。
- 新分支：`feature/3dmigoto-dalamud-compat`，起点为 r10 解析后的提交
  `7ec743255930cd0c45921cb72a7b1a4b27c921fe`（标注标签对象 `b6db09915a842da095568ab362682f66d3416cbd`）。
- 独立工作区：`../smsm-3dmigoto-compat`。原 `../smsm-ff14` 原地保留。
  未移植 ReShade/add-on/桥功能，只将当前计划复制到新分支；通用管理工具来自 r10。
- r10 ZIP SHA-256：`4e8bd8172abbcdd411c739b76bcb6434a05ac7a5d00b18ea0c69dad2205e3914`。
- r10 清单 SHA-256：`8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae`。

本地保留目录：原工作区 `artifacts/stagehand-m0`、`stagehand-m2`、`stagehand-m3`、
`native-*`、`install-backups`、`native-install-backups`、`releases` 和其他既有忽略目录。
Stagehand 的开发插件路径仍指向原工作区包；没有移动这些目录。原始画面、世界位置、
GPU 数据、用户配置和 dump 均不纳入 Git 或交付 ZIP。

## 崩溃证据与边界

现有本地日志 `dalamud_appcrash_20261010_024540_475_39056.log` 和
`dalamud_appcrash_20261010_024638_033_48776.log` 都指向：

```text
IDCompositionVisual.SetContent
Dx11Renderer.ViewportData.CreateDComposition
ViewportHandler.OnCreateWindow
ImGui.UpdatePlatformWindows
InterfaceManager.DxgiSwapChainPresentDetour
```

日志模块表确认 3DMigoto 1.3.11.0、Dalamud 15.0.3.6；当前客户端构建为
`2026.09.15.0000.0000`。崩溃时 shader 选择与完整注入条件未由日志单独证明，
不能据此把游戏内 B 组合（零替换）标记为已测试。
原始两份 dump 位于本机 XIVLauncher 数据目录，SHA-256、大小和原路径记录在
`artifacts/return-deployment/crash-evidence.json`；对应日志副本也保留在那里。

独立 C++ 子进程复现 Dalamud 的 composition swap-chain → visual → SetContent 路径。
不启动游戏、不注入游戏；每个运行库一个子进程，均不部署 shader：

| 离线组合 | 结果 |
|---|---|
| 系统 D3D11 | SetContent / Commit 成功 |
| 原 1.3.11 | 进入 SetContent 后退出 `0xC0000005` |
| 官方 1.3.16 | 同位置退出 `0xC0000005` |
| 系统 / 1.3.16 普通 HWND 交换链 | 创建、获取 backbuffer、清屏调用成功；隐藏窗口 Present 返回 `DXGI_STATUS_OCCLUDED` |

普通窗口测试说明该最小路径未崩溃，不证明可见 UI 绘制、实际 ImGui 输入或游戏稳定性。
没有反复撞游戏；没有把官方更新说明中的兼容修复当成本项目已修复的证据。

官方来源：[1.3.16 发布](https://github.com/bo3b/3Dmigoto/releases/tag/1.3.16)，
对应源码标签提交 `cbc4993ca67b6d639e06c578d4e3dc8b3780243f`。
下载 ZIP SHA-256：`1e097eaed99270f2444e3a70eff68194b751f6be19d0edadc40a780074152558`。
x64 `d3d11.dll` SHA-256：`a338374d1c1a335322d868a483369d8aa754ddbdc511ae48807662a7a9165f30`。
这些是本次官方下载的本地校验值，不表示上游签名认证。

## 已接受的配置规避与当前安装

用户明确选择“接受，先恢复游戏内 UI 和 r10 色调”。据此将
`IsDisableViewport` 从 false 改为 true，让 Dalamud 不再创建额外视口。
依据本地 Dalamud `InterfaceManager` 的实际代码，设置为 true 会移除
`ImGuiConfigFlags.ViewportsEnable`。副作用是窗口暂时不能拖出游戏边界。
未修改 Dalamud 二进制、游戏构建、图形设置或其他插件的启用状态。

按用户恢复色调的选择，直接部署 `r11-compat-c2` 的 `daily` 选择（只含 tone）；
包默认仍是 `vanilla`，便于需要时进行零替换隔离。该执行顺序不替代原计划的分组合验收。
保留游戏 Bloom/景深；不打包反射、阴影、抖动、径向模糊等实验。
色调源文件/二进制与 r10 完全一致；候选 INI 关闭 hunting、导出和持续详细日志。
候选 `SMSM-preview.json` SHA-256：`850f6ea5017ad97a8f3a435af8cb8dedc989b9522562e3b3c094272959e99c27`。

20:17（上海时间）在游戏退出状态完成：

1. 精确备份 Dalamud 配置，只改变外部窗口开关和 SMSM 测试桥的启动/登记状态。
2. 按原凭据备份并撤下 ReShade DLL、SMSM 原生诊断 add-on 和对应凭据。
3. 安装候选并核验全部已选择文件；当前仅 `tone`，`runtime_verified=false`。
4. 核验 `ReShade.ini` / `ReShadePreset.ini` 字节不变，Stagehand 本体登记不变。

本地部署检查点：`artifacts/return-deployment/deployment.json`。
ReShade 文件备份：原工作区 `artifacts/native-install-backups/60c912c746c14dc18340f93f7fc90377`。
配置备份：新工作区 `artifacts/return-deployment/config-backup`。
安装事务备份：新工作区 `artifacts/install-backups/20261010T121724Z-b6ed3e7c19f64a60bd307c3511c49de3`。

## 待做的一轮实机检查

用户当前暂时无法进游戏，以下没有填写通过结果：

- 打开 Dalamud 设置/插件管理器，点击、在游戏内拖动、输入、关闭重开。
- 当前 tone 选择的色调、普通场景及一次切图。
- 必要的零替换对照和独立核心 UI 对照；当前保留用户常用插件，未宣称纯净 A/C 组合通过。
- 效果关闭/恢复与 F10 shader 重载；候选 `hunting=0`，不可套用旧 r10 的 F9/F10 验收结论。

若再崩溃，保存新日志/dump，不重复同一组合。无实机结果前不发布稳定版本、不开新效果。
暂时以退出游戏后的 `select --profile vanilla` / `select --profile daily` 作为可回退选择操作。
管理器对此候选明确拒绝 `--live`，并记录 `pending-restart`；解除限制前需另做有依据的重载验证。

## 候选包使用

以下示例用于候选 ZIP 解压目录；已安装的本机候选无需重复安装。
先退出游戏，备份配置并关闭外部视口（脚本同时停用 SMSM 测试桥，保留独立 Stagehand）：

```powershell
python tools/configure_compat_viewports.py --config "$env:APPDATA\XIVLauncher\dalamudConfig.json" --backup artifacts/dalamud-before-compat --game '<客户端目录>/game'
python tools/manage_preview.py install --client-root '<客户端目录>' --package package
```

尖括号需替换为实际路径。默认零替换；在退出游戏状态选择色调：

```powershell
python tools/manage_preview.py select --client-root '<客户端目录>' --profile daily
```

恢复零替换用 `--profile vanilla`。安装器不会覆盖未登记的其他注入器；若仍装着 ReShade，
必须先使用其真实安装凭据保存并撤下，不直接覆盖 DLL。

## 构建与检查

```powershell
python tools/build_compat_preview.py artifacts/preview-2026.09.15-r10-managed artifacts/runtime/3Dmigoto-1.3.16.zip artifacts/r11-compat-c2
python tools/test_compat_preview.py -v
python tools/test_manage_preview.py -q
python tools/validate_d3d11.py artifacts/r11-compat-c2
python tools/check_dcomp_compat.py artifacts/new-main-check artifacts/r11-compat-c2 --main-only
```

构建输出目录必须不存在；原始 composition 复现会使子进程崩溃，已有证据无需重复。
上述开发测试命令在源代码工作区执行；候选 ZIP 仅包含包文件、安装/配置/校验工具和说明。
候选工具 4 项通过；管理器 20 项中 19 项通过、1 项因符号链接权限跳过。
目录联接拒绝检查在解除沙箱限制的测试进程中通过。WARP 接受唯一色调 shader。
事务测试覆盖零替换 → tone → 精确回退；配置测试确认保留独立 Stagehand 和其他设置，
并拒绝运行中修改及覆盖后续用户修改。离线结果位于 `artifacts/dcomp-compat-v1` 和 `dcomp-main-v1`。

## 恢复

所有 DLL 切换都必须退出游戏。当前候选可使用 `tools/manage_preview.py uninstall`
按凭据卸载，或通过管理器恢复上述安装前备份。此操作不会自动重新启用 ReShade。
不要将原 r10 的 1.3.11 与已开启的外部窗口组合重新投入使用。

本机提供 `artifacts/return-deployment/restore_previous.py`：根据已保存的精确文件和
校验值撤下候选、恢复原 ReShade 诊断环境及备份配置。它不是默认运行依赖，
仅使用原归档工作区的清理/恢复工具。若游戏启动、配置有后续修改或文件发生变化，
会拒绝自动恢复；此时应按配置备份逐项合并，不覆盖较新的用户设置。
Stagehand 包目录、原生安装备份和两个工作区在验收及恢复完成前均保留。
