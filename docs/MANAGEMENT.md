# 可选效果与安装管理

当前管理包：`artifacts/preview-2026.09.15-r10-managed`。它包含 r9 相同的八个 shader 二进制，默认仅部署固定 50% 色调。游戏 Bloom/景深不替换；其他效果可单独开启但仍是实验。用户已确认色调 F10 切换有变化且无异常，并反馈传送、室内外与短战斗检查没有问题；长期稳定性及性能仍待验证。

旧 r2–r9 及诊断包的目录和清单保持不变。新管理工具能读取旧安装清单并一次升级，无需先手动卸载。`Install-Preview.ps1` 继续服务旧包，对新管理包明确拒绝，避免使用静态旧清单误卸载已改变的效果组合。

## 构建

```powershell
python tools/build_preview.py artifacts/client-2026.09.15 artifacts/preview-managed --managed --extended --look calibrated-static --tonemap-percent 50 --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/validate_d3d11.py artifacts/preview-managed
```

`SMSM-preview.json` 是不可变功能库清单。`SMSM-state.json` 记录当前部署的文件、请求开启的效果、来源包和待应用状态。工具从原包读取文件，所以不要移动/编辑已安装管理包的源目录；要换位置或升级，请明确执行 `install --package <新包>`。

## 本机操作

客户端目录需要管理员写权限。在**管理员 PowerShell** 先设置下面三个变量；只定义本次终端变量，不修改系统设置：

```powershell
$smsmClient = 'E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online'
$smsmManager = 'E:\SapphireServer\Dalamud Dev\smsm-ff14\tools\manage_preview.py'
$smsmPackage = 'E:\SapphireServer\Dalamud Dev\smsm-ff14\artifacts\preview-2026.09.15-r10-managed'
```

以下使用本机已验证的 Python 路径；在其他机器上换为可用的 Python 3.10+。

**首次升级：退出游戏，一条命令即可。** 原来装着景深诊断包或 r9 都能按真实凭据升级，自动保存原安装文件备份。

```powershell
C:\Python314\python.exe $smsmManager install --client-root $smsmClient --package $smsmPackage
```

默认 `daily` 只有色调。需要复现 r9 完整实验组合，可显式加 `--profile r9-baseline`；它不表示所有效果已经通过验证。

**状态与文件校验：**

```powershell
C:\Python314\python.exe $smsmManager status --client-root $smsmClient
```

输出是磁盘状态，`pending-restart-or-F10` 表示不能由文件状态证明游戏已应用；重启/按键成功也不自动证明某个 shader 在当前场景被调用。不要把 `runtime_verified=false` 人工改为 true 来消除提示。

**逐项开关：** 未做过受控 F10 测试时，先在游戏退出状态选择，下一次启动生效。

```powershell
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --enable reflection
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --disable reflection
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --effects tone,dithering
```

效果名：`tone`、`reflection`、`shadows`、`dithering`、`radial`。`--enable/--disable` 保留其余选项；`--effects` 给出完整组合。没有景深选项，因为未证实收益的景深实验不进入管理包。

**仅对照一个效果：**

```powershell
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --isolate reflection
```

此时色调和其他替换都停用，F9 只对照反射。恢复预设：

```powershell
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --profile daily
```

**第一次受控热切换只测色调：** 开启游戏，固定已知可见的场景，运行下面一条并回游戏按一次 F10：

```powershell
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --disable tone --live
```

确认画面变为原版色调且没有错误，再运行下面一条并按一次 F10：

```powershell
C:\Python314\python.exe $smsmManager select --client-root $smsmClient --enable tone --live
```

按键无效时可先用小键盘 0 开启 hunting，再按一次 F10，不连续按。`--live` 只允许选项变更；实际改变的只能是 shader TXT/BIN 和管理状态。DLL、头文件、INI 改变会被拒绝。出现无响应/重载错误就停止，退出后恢复；这不是已验证的无重启保证。F8 默认关闭。

### 从独立诊断包切换 shader

`select --package <新包> --live` 现在支持明确选择另一个不可变管理包，只允许 shader TXT/BIN、包凭据和选择状态发生变化。客户端版本和所有文件哈希仍需匹配；DLL、INI、头文件的变化（包括增加或删除）会阻止操作。它不能用于完整运行库升级，也不允许绕过同一路径的包被修改检查。每次操作仍生成备份。省略 `--package` 时继续使用当前状态指向的包。

反射紫红色执行诊断的构建、切换、恢复和判断标准见 [REFLECTION-DIAGNOSTIC.md](REFLECTION-DIAGNOSTIC.md)。诊断效果不能和其他效果同时开启，默认预设仍只选择色调。

## 备份、恢复和所有权

每次文件变更都会输出一个 `artifacts/install-backups/<UTC时间-UUID>` 备份目录，包含变更前全部清单所有文件与状态。保留它；这些目录不会被自动清理。工具不执行递归删除、不改游戏原文件、不改已有目录 ACL。当前包外的 ReShade 等文件、已修改文件、shader 目录中的未登记文件、符号链接/目录联接和跨客户端备份会阻止操作。

退出游戏后回到指定备份：

```powershell
C:\Python314\python.exe $smsmManager rollback --client-root $smsmClient --backup '<实际输出的备份目录>'
```

若安装过程中断，留下 `game/SMSM-transaction.json`，先退出游戏再恢复变更前文件：

```powershell
C:\Python314\python.exe $smsmManager recover --client-root $smsmClient
```

检测到事务后的人工作业会阻止自动恢复，避免覆盖。备份/磁盘本身损坏或权限持续不足时需要先处理该问题，不能保证任何故障下都自动成功。

卸载（使用当前选择清单，保留日志和抓帧）：

```powershell
C:\Python314\python.exe $smsmManager uninstall --client-root $smsmClient
```

## 游戏更新后的检查

版本不符会阻止安装和切换；卸载仍可用。先离线重新提取新客户端，执行审计：

```powershell
C:\Python314\python.exe $smsmManager audit --client-root $smsmClient --extraction '<新提取目录>'
```

可用 `--package` 审计指定包。输出的 `original_matches` 只比较提取记录与原始 SHA-256，`execution_proven` 始终为 false；这个工具不会自动修改兼容版本、替换 hash 或开启 shader。匹配失败后必须重新核对接口与处理阶段。

## 记录简洁游戏测试

运行 `tools/record_validation.py`，每条记录提供一个场景和事实描述。普通测试可只记观察 FPS 范围，不伪造帧时间：

```powershell
C:\Python314\python.exe 'E:\SapphireServer\Dalamud Dev\smsm-ff14\tools\record_validation.py' --client-root $smsmClient --scenario teleport --outcome normal --notes '<实际观察，例如两次传送后正常，无闪烁>' --settings '<实际分辨率、抗锯齿/升频、帧率限制>' --fps-range <实际最低FPS> <实际最高FPS>
```

尖括号是填写提示，不能原样运行。场景支持 `teleport`、`combat`、`indoor-outdoor`、`effect-comparison`、`reload-check`。结果 `normal` / `issue` / `inconclusive` 是人工观察标签，不是自动认证。

有真实帧时间 CSV 时，加 `--frames <CSV> --column <毫秒列名>`；默认列名 `frame_time_ms`，采集工具若导出 `MsBetweenPresents`，应明确指定。混合进程数据使用 `--process ffxiv_dx11.exe`（要求 `Application` 列）。配对测试用相同 `--pair` 标签、分别填 `--condition on` / `off`。工具计算样本数、平均/中位帧时间、P95/P99和最大停顿，不自动采集、不丢弃离群值、不推断 shader 单独 GPU 成本。无 CSV 时 `frame_times=null`。

首轮只需：一次色调 F10 关闭/恢复确认，再做路线文档中的传送、室内外、短战斗检查。其他实验和景深等待新的明确证据。

## 本轮离线验证记录

另有 2026-10-08 首次实机重载反馈：用户报告色调 F10 对照有变化、无卡顿和错误。只读检查确认 r10 包 SHA-256 为 `8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae`，完整性通过，当前仅选择 `tone`。人工观察已存入 `artifacts/validation`；没有帧时间数据。磁盘状态中的 `pending-restart-or-F10` 保持原样，因为管理器无法检测游戏是否完成应用；本次反馈独立记录，不提升其他效果的验证状态。

2026-10-08：管理工具 15 个测试中 14 个通过，1 个因 Windows 符号链接创建权限缺失跳过；实际 Windows 目录联接拒绝测试通过。3 个帧时间统计测试全部通过。管理测试覆盖旧包升级/精确回退、每项隔离、运行进程拦截、只变更 shader 的 live 模式、文件修改和冲突保护、事务中断恢复、备份损坏及备份期间的并发修改。

8 个 shader 通过 WARP 创建检查；二进制、INI、DLL 与 r9 相同，3 份 ASM TXT 仅生成时间注释不同。旧安装器的版本、碰撞、修改保护和安装/卸载测试通过。审计工具已对当前提取清单运行，匹配结果仍明确标为“不证明执行”。这些结果保存在工作区 `artifacts/r10-management-validation.json` 及工具输出中；未填写虚构的实机验收或性能数据。

重跑（目录联接测试需在允许创建联接的终端运行）：

```powershell
python tools/test_manage_preview.py -v
python tools/test_record_validation.py -v
```

管理测试使用固定的本地 r10/r9 包作为夹具，并只在 `artifacts/manager-test-*` 临时客户端写入；真实客户端不参与写操作。
