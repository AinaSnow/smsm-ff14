# 日常色调与高光：H1 离线候选

2026-10-10。用户选择下一项聚焦“日常色调与高光层次”。
H1 已构建和离线验证，**没有安装到游戏**，默认零替换；当前仍使用 c2 / r10 固定 50% 色调。
当前 c2 用户反馈无崩溃、色调初步正常，并确认操作过 Dalamud 窗口；尚未切图。
完整 R1/R2 仍未通过，H1 属于后续单项效果的离线准备，不替代兼容验收。

## 要解决的问题与假设

r10 输出可能高于 1。如果后续 SDR 显示步骤将这些值裁到 1，明亮渐变可能合并为同一片白色。
H1 尝试在固定 50% 混合之后，对超过 0.85 的 RGB 峰值施加连续、单调的压缩，渐近于 1。
所有通道按同一比例缩放；低于阈值的颜色、alpha、原游戏 LUT/曝光接口保持原样。
没有更换运行库、INI、采样器或资源绑定，没有添加帧间状态或运行时常量控制。

**这仍是待实景验证的假设。** 合成输入能复现超范围输出，但不能证明用户当前场景
存在可见裁切，也不能证明亮部压缩一定改善了游戏画面。阈值是首轮实验参数，不是已校准值。
该实验面向 SDR；没有验证 HDR 显示链。

## 已验证与限制

| 项目 | 结果 |
|---|---|
| 编译与资源接口 | 编译成功，与 c2 的纹理/常量/采样器绑定一致 |
| 修改范围 | 只改变一个 tone shader 的 TXT/BIN；c2 包不变 |
| WARP 真正绘制/读回 | 4 组曝光/LUT 条件，每组 6 类颜色、512 级输入 |
| 暗部和中间调 | 测试中阈值以下最大误差为 0 |
| Alpha | 最大误差为 0 |
| RGB 比例 | 最大误差约 `5.96e-8` |
| 中性渐变 | 未出现反向变化；输出有限、非负、峰值小于 1 |
| 合成亮部裁切对照 | 裁至 0–1 后，原版超范围中性段相邻变化数为 0，候选为 58–169 |
| 安装管理 | 临时客户端中 c2 → H1 → c2 精确恢复通过；没有操作真实客户端 |
| 游戏实景收益 | 未验证；未安装 |

合成 LUT 为常数增益，输入为中性、暖色和饱和色渐变，不是游戏抓帧。
表中的亮部变化数使用浮点结果，不表示最终屏幕的可见灰阶数量。
数值记录见源代码仓库的 `docs/validation/tone-highlights-h1.json`。

潜在副作用：白色衣服、明亮肤色、灯光和发光特效可能显得更暗，Bloom 的视觉强度也可能改变。
峰值为 1 的输入会压到约 0.925，这是此曲线的明确取舍。
保留 RGB 比例并不保证主观肤色或饱和度感受不变。

## 下一轮只看两个场景

先完成 c2 的一次正常切图，确认没有新的兼容异常。之后在相同设置、时间和相机下对照：

1. 日间有亮云/白墙/白色衣服的场景：检查亮部层次是否增加，白色是否变灰。
2. 常用角色的明暗交界或室内灯光场景：检查肤色、暗部和发光材质。

只有明确可见的收益且副作用可接受，才考虑保留。没有收益就回到 c2；不因编译或数值通过而升级验收状态。
效果开关当前只支持停止游戏后的文件选择。官方 1.3.16 的 `hunting=0` 不注册 F9 / shader 重载，
F10 配置重载不能替代 shader 重载；不要通过连续按键尝试应用。

## 构建（源代码工作区）

```powershell
python tools/build_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h1
python tools/test_tone_highlights.py -v
python tools/validate_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h1 artifacts/tone-highlights-validation-h1
python tools/validate_d3d11.py artifacts/r11-tone-highlights-h1
```

输出目录必须不存在。候选生成只读 c2；只修改复制出的 tone 文件。
离线脚本使用既有 WARP 绘制工具，没有扩建采集链。原始数值保留于忽略的 `artifacts`。

## 对照安装与恢复（尚未执行）

沿用 c2 的 `IsDisableViewport=true`，窗口留在游戏内。不要在游戏运行时操作。
解压测试 ZIP 后，在管理员终端中安装其中的 `package` 并显式选择 tone：

```powershell
python tools/manage_preview.py install --client-root '<客户端目录>' --package package --profile daily
```

省略 `--profile daily` 时默认零替换。保留输出的备份路径以及源包目录。
返回这次安装前的 c2：

```powershell
python tools/manage_preview.py rollback --client-root '<客户端目录>' --backup '<安装 H1 时输出的备份目录>'
```

也可在退出游戏后显式安装保留的 c2 包并选择 `daily`。禁止用 H1 覆盖原 c2 包目录或 r10 发布物。
