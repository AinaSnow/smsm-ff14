# 反射执行诊断

2026-10-08。湿地面反射隔离对照未见差异；文件安装正确，但没有当前执行证据。此次只回答目标 shader 的输出是否参与可见画面，不评估画质或性能。

## 包与边界

- 包：`artifacts/diagnostic-2026.09.15-reflection-marker`。
- 基础包：`artifacts/preview-2026.09.15-r10-managed`，清单 SHA-256 `8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae`。
- 诊断清单 SHA-256：`697d03251255986824fdb5b53740dae04e23db705eb337c87fd80b9611952f55`。
- 客户端：`2026.09.15.0000.0000`；目标：`4caad0714bdcc47e`。
- 使用提取的原始反射字节码，不使用采样扰动实验。保留所有原始指令，仅在唯一的 `ret` 前追加 `mov o0.xyzw, l(1, 0, 1, 1)`。
- 强制紫红色与 alpha=1，刻意覆盖命中/衰减结果。它可能让局部甚至大片画面染色；不是新的反射效果，不用于日常游玩。后续合成仍可能遮蔽或衰减它，因此阴性结果不等于没有执行。
- 与 r10 相比，资产仅改变目标 TXT/BIN；运行库、INI、头文件和其他 shader 字节保持相同。F8 仍关闭，没有动态色调参数或自动按键。默认 `daily` 只开色调；开启诊断时禁止混合其他效果。

## 在同一场景切换

本机游戏目录需要管理员写权限。在管理员 PowerShell 执行：

```powershell
C:\Python314\python.exe "E:\SapphireServer\Dalamud Dev\smsm-ff14\tools\manage_preview.py" select --client-root "E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online" --package "E:\SapphireServer\Dalamud Dev\smsm-ff14\artifacts\diagnostic-2026.09.15-reflection-marker" --isolate reflection --live
```

回游戏按一次 F10（hunting 关闭时先用小键盘 0 显示调试文字）。松开 F9 观察是否有明确的紫红色区域，再按住 F9 看是否消失；固定镜头、地点和画质设置即可，不必继续寻找微小反射差异。色调此时关闭，单纯变暖/变冷不算标记出现。

判据：

- 紫红色标记随 F9 松开/按住而出现/消失：目标替换输出确实参与了该场景最终画面。只说明可见贡献，不证明扰动实验有效或低开销。
- 没有标记：仍不确定。可能与 F10 应用、反射画质所选路径、该场景未调用或后续遮罩/合成有关。先确认安装状态、按键和图形设置，再决定是否需要有针对性的日志或捕获；不直接增强效果参数。
- 出现错误或异常停顿：停止追加切换，保留错误与触发时间，退出游戏后按恢复命令操作。

测试后恢复 r10 日常包：

```powershell
C:\Python314\python.exe "E:\SapphireServer\Dalamud Dev\smsm-ff14\tools\manage_preview.py" select --client-root "E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online" --package "E:\SapphireServer\Dalamud Dev\smsm-ff14\artifacts\preview-2026.09.15-r10-managed" --profile daily --live
```

回游戏再按一次 F10。游戏已经退出时可省略 `--live`，随后启动。恢复包路径必须明确指定，不能仅开启诊断包中的 `reflection` 来做正常质量比较。两次选择都自动保存变更前备份；源包保持不变。

## 构建与离线验证

```powershell
python tools/build_reflection_probe.py artifacts/client-2026.09.15 artifacts/preview-2026.09.15-r10-managed artifacts/diagnostic-2026.09.15-reflection-marker --decompiler artifacts/decompiler/1.3.16/cmd_Decompiler.exe
python tools/test_reflection_probe.py -v
python tools/test_manage_preview.py -v
```

构建目录必须不存在。检查原始 SHA/FNV、原指令精确往返、仅追加一条输出指令、接口一致和包完整性。D3D11 WARP 接受全部八个打包 shader；这是创建验证，没有离线绘制，也不证明游戏实际执行。详细报告位于包的 `build-audit/validation.json`，游戏原始字节码和诊断产物不提交到 Git。

本轮三个诊断测试全部通过；管理测试 20 个中 19 个通过，1 个因 Windows 符号链接权限不足跳过。目录联接测试首次受沙箱限制失败，在沙箱外的临时客户端重跑通过。新增管理检查覆盖跨包 live 切换并精确恢复、禁止混合诊断、阻止运行库/INI/头文件变更或删除、版本不符、同路径篡改保护。测试未写真实游戏目录。

## 已观察到的结果

用户提供了湿地面与建筑大片紫红色的截图，并报告“有的 按F9 会消失 但是有残留转动下视角就没了”。只读检查确认当前是上述 coverage 诊断包，文件完整性通过且仅选择反射。由此确认目标替换输出在该场景参与了可见画面；这不证明 r10 原采样扰动有画质收益，也不代表所有反射路径都已覆盖。残留的具体来源未确定，不能直接归因为某个抗锯齿或缓存实现。后续对照必须在切换后转动视角、确认残留消失，再观察稳定画面。

结构化人工证据位于 `artifacts/validation/reflection-marker-confirmed-*.json`，单独记录目标、包 SHA、截图 SHA 和残留反馈。不可变包清单仍保留构建时的未验证状态，不事后篡改。

## 保留原始反射权重的后续诊断

第一包强制覆盖了 alpha 与命中/衰减结果，大片紫色不能作为正常反射强度图。第二包 `artifacts/diagnostic-2026.09.15-reflection-contribution` 将最终场景颜色采样的 RGB 改成紫红色，随后继续执行原版命中、材质权重乘法、亮度压缩及 alpha 输出。原始指令逐字节保留，仅插入一条 `mov r0.xyz`。它显示标记能否通过原有权重；固定输入辐射颜色不能精确量化真实反射能量或成本。

包清单 SHA-256：`f7051674340bb32458b166b7a103f0e6ec039cf70f7bb8a5063e663387dfa6fd`。仍仅改变目标 TXT/BIN，原 r10 与第一包不变。五个诊断检查通过，D3D11 WARP 创建八个 shader 通过；尚待实机对照。

构建时给上述命令换一个新输出目录，并加 `--mode contribution`。管理员 PowerShell 切换：

```powershell
C:\Python314\python.exe "E:\SapphireServer\Dalamud Dev\smsm-ff14\tools\manage_preview.py" select --client-root "E:\SteamLibrary\steamapps\common\FINAL FANTASY XIV Online" --package "E:\SapphireServer\Dalamud Dev\smsm-ff14\artifacts\diagnostic-2026.09.15-reflection-contribution" --isolate reflection --live
```

按一次 F10 后转动视角清除上一包残留，再回到固定机位观察。F9 对照也在残留消失后判断。若只剩局部或很弱的紫色，说明恒定标记在这些位置通过了原版权重与后续合成；若完全没有，则不能只凭颜色判断是零权重还是重载/后续处理问题。尚不能直接提升扰动幅度或开启为默认。测试后用上文明确指定 r10 包的恢复命令，按 F10 并确认残留清除。
