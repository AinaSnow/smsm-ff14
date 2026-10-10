# S1：对比度自适应锐化

2026-10-11。候选包 `artifacts/r11-sharpen-s1`（`tools/build_sharpen_s1.py`），基于 T2b（色调 A + 抖动）。
**已部署，下次启动生效：色调 A + 抖动开 + 锐化中。**

## 想解决的问题

用户反馈角色头发边缘发软（当时 DLSS；两张抖动开关截图一样软，与色调/抖动无关）。用户随后改用 DLAA。
预期：发丝、睫毛、布料纹理更清楚，不出现白边或亮点噪点。

## 做法

色调 shader 已确认输出到屏幕，锐化放在其开头、两条色调曲线之前，作用于 HDR 输入：

- 参考 AMD FidelityFX CAS：中心 + 上下左右 5 点；局部对比已高的地方少锐化。
- 在 `u = c/(1+c)` 压缩域计算，高光不会冲高；结果限制在这 5 点的最小/最大值之间，不产生光晕。
- 强度 x6：中 0.5（CAS 峰值 −1/6.5）、强 1.0（−1/5，CAS 上限）。alpha 不变。

| 按键 | 作用 |
|---|---|
| Ctrl＋F4 | 锐化 关 / 中 / 强 循环（启动为中） |
| Ctrl＋F7 | 显示标签：A、D 之后的 **S**，浅蓝 = 中，橙 = 强；关闭时无 S |
| Ctrl＋F6 / F8 | 抖动、色调，不变 |

## 离线验证

`docs/validation/sharpen-s1.json`，WARP 实际绘制：

- 锐化关：模式 × 标签 × 抖动组合与已部署 T2b 逐像素一致。
- 平坦图像开强锐化最大变化 `8.9e-8`。
- 硬边、软渐变、细条纹、纹理噪声、HDR 高光 8.0、纯黑块：输出均在输入十字邻域色调结果的最小/最大之间
  （最大越界 `9.5e-7`），无光晕；纯黑不变。
- 横向平均梯度（含平坦区域）：关 → 中 → 强 单调上升，约 +3.5% / +5%。合成硬边受防光晕限制变化很小，
  主要作用在纹理和多像素的软边，正是 TAA/DLAA 之后的情况；实际强弱需要实景判断。
- S 标签只在标签开时出现，颜色对应强度。官方 1.3.16 按原包启动：A + 抖动 + 中锐化，与 WARP 差 `1.4e-6`。
- `test_sharpen_s1.py`：相对 T2b 只改色调 shader 与 INI，精确回退。

锐化在色调 shader 内，管理器的效果选择不能单独关闭它；用 Ctrl＋F4 关。

## 安装与回退

2026-10-11 01:37（上海时间），游戏退出状态由 T2b 切换。清单 SHA-256：
`29e5c6de0ed78f28b7d3ad2aba7131769384a4b48f48bc4fb58e9538b167e087`。记录：`artifacts/return-deployment/s1-install.json`。
回到 T2b 的备份：`artifacts/install-backups/20261010T173759Z-87c1955720324e9aaf7667f638cbc299`。

## 实景对照（2026-10-11）

DLAA，两组各 中 / 强 / 关。S 标签颜色正确，开关有效。用户反馈**看不出区别**。
记录：`docs/validation/sharpen-s1-scene-2026-10-11.json`。

- 角色有待机动作，三张之间头部位置不同，无法逐像素比较。
- 背景岩壁静止：细节能量 关 32.7 → 中 39.7（+21%）→ 强 43.1（+32%），但平均每像素只变 2–3 级，2 倍放大才看得出。
- 原因：CAS 上限本来就温和；1 像素十字半径只作用于单像素细节，DLAA 后的软边宽 2–3 像素；防光晕限制进一步封顶。

结论：S1 有效但低于肉眼可辨，按计划原则不作为默认。

## 原待办

DLAA 下，角色近景（头发、睫毛、布料）站定不动，开标签，按 Ctrl＋F4 截 关 / 中 / 强 三张 PNG。
看发丝是否更清楚、有没有白边或闪烁颗粒。选一档作为默认，或都不明显就关闭。
移动时注意是否有闪烁（锐化会放大 TAA 残留抖动）。

## 开发重跑

```powershell
python tools/build_sharpen_s1.py artifacts/r11-dither-t2b artifacts/r11-sharpen-s1
python tools/validate_sharpen_s1.py artifacts/r11-dither-t2b artifacts/r11-sharpen-s1 artifacts/sharpen-s1-validation --runtime-check
python tools/test_sharpen_s1.py -v
```
