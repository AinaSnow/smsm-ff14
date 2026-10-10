# H2 快捷对比版

2026-10-10，用户要求添加开关以确认效果是否生效。已在游戏退出状态安装。
下一次启动默认 r10 基线，H1 高光关闭，左上角显示蓝色 **R10**。

| 按键 | 行为 |
|---|---|
| Ctrl＋F8 | R10 基线 ↔ H1 高光候选；标签分别为蓝色 R10 / 橙色 H1 |
| Ctrl＋F7 | 隐藏 / 显示模式标签，方便截图 |

切换即时改变 shader 参数，不需要 F10，不重载 shader 文件，不替换 DLL。
按键只在游戏位于前台时处理。每次启动回到 R10，不保存上一次的高光开启状态。
这里比较的是**已接受的 r10 50% 色调与 H1 高光处理**，不是游戏全原版与 SMSM 的开关。
若场景没有超过处理阈值的亮部，画面差别可能很小；看标签可确认模式。
标签由目标 tone shader 绘制，因此比仅显示键盘状态更直接，但不能替代实景收益判断。
游戏后续 UI/画面处理可能覆盖标签；如果没有标签或按键无反应，应报告，不连续尝试 F9/F10。

## 验证

- WARP 对精确发行 shader 进行读回：标签隐藏时 OFF 与 r10 逐像素一致，ON 与 H1 逐像素一致，OFF 回归再次一致。
- 标签仅修改左上角 `[24,24)–[72,46)` 区域的 RGB，不改变 alpha；两个模式标签不同。
- 官方 3DMigoto 1.3.16 独立硬件子进程：真实创建并填充 IniParams `t120[7].xy`，
  分别初始化关闭/开启两种状态，输出与对应 WARP 参考最大差约 `4.77e-7` / `1.79e-7`。
  没有合成按键输入，也没有把不同子进程的初始化检查称为同一会话热切换验收。
- 官方固定源码的通用 `[Key]` 注册与 hunting 按键注册独立，可在 `hunting=0` 使用。
- 构建/回退测试通过。真实客户端仅变更 tone TXT/BIN 和 INI（及管理凭据），运行库 DLL 不变。
- 用户随后提供 R10/H1 两张同场景截图，标签和画面变化均可见，确认游戏内比较两状态已生效。切图、重复切换稳定性仍未由这组截图证明；H1 未获得画质收益验收。

只新增一个 1D 资源读取 `IniParams.Load(int2(7,0))`，x 控制高光，y 控制标签。
原有游戏纹理、LUT、常量和采样器绑定保留；没有重新启用 r5 的动态色调混合方案。
鉴于此前 r5 的挂起记录，本次明确验证了新分支的精确数值、实际 1.3.16 资源初始化，
仍保留首次实机按键的未验证状态，不由离线结果承诺稳定性。

开发重跑：

```powershell
python tools/build_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h2 --toggle
python tools/validate_tone_compare.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h1 artifacts/r11-tone-highlights-h2 artifacts/tone-compare-h2-final --runtime-check
python tools/test_tone_highlights.py -v
```

输出目录需不存在。验证复用既有绘制工具，为这次比较增加最小 Texture1D 输入和显式隔离运行库模式；
默认路径仍使用系统 WARP。不会向游戏进程注入测试程序。

## 安装与恢复

本机 20:54（上海时间）已安装 `daily`，即载入可比较的 tone shader，内部高光开关默认关闭。
清单 SHA-256：`abd5f29c10070199824ac7bb6513ea62fe481be8854c863aabb7c74e190f51ee`。
保留 `IsDisableViewport=true`。安装记录在 `artifacts/return-deployment/h2-install.json`。

精确返回 c2：退出游戏后使用管理器 `rollback`，备份参数为
`artifacts/install-backups/20261010T125419Z-9855e2d97bfb4e1293e65761899c56a0` 的绝对路径。
若需要进一步运行此前的 `restore_previous.py` 恢复 ReShade，先回退到 c2，不能绕过其版本检查。

独立 ZIP 默认零替换；如需安装对比版，退出游戏后运行：

```powershell
python tools/manage_preview.py install --client-root '<客户端目录>' --package package --profile daily
```

管理器的 `select --live` 仍被禁止，因为文件选择热重载未验证；这与 Ctrl＋F8 的 shader 参数切换不同。
不移动或修改已安装包的源目录。H1 的曲线假设和潜在白色变暗问题见 [H1 说明](TONE-HIGHLIGHTS-H1.md)。

## 首组实景对照（2026-10-10 21:25）

用户提供雨中木门前的 R10/H1 对照。H1 中浅色头发的亮丝反差减弱，蓝灯的明亮光芯被压低。
本次视觉判断是压缩过重，未显示足以抵消副作用的收益，因此不将 H1 提升为默认。
这是助手对截图的判断，不冒充用户审美结论。角色姿态、雨滴和灯光动画存在差别，
不做严格逐像素因果归因。截图只记录文件名和校验值，不上传原图。
详见 [实景记录](validation/tone-compare-h2-scene-2026-10-10.json)。

保持启动默认 R10；当前会话若在 H1，可按 Ctrl＋F8 切回蓝色 R10。没有修改游戏文件。
后续修订应优先缩小高光处理范围、减弱肩部压缩，保留头发反光与发光物体的明亮感，
再判断是否有值得保留的层次改善，而不是仅以变暗或小于 1 的数值作为成功标准。
