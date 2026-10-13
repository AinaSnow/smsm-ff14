# D0 / D1：GPose 景深高光散景

2026-10-14。`artifacts/r11-dof-d1`（`tools/build_dof_d1.py`），基于已部署 T2d（客户端 2026.10.06）。**已部署。**

## 原画面的问题

用户认为 GPose 景深“还可以”。截图 `ffxiv_20261013_235715_791`（光圈 12、自动对焦）放大检查：

- 人物与虚化背景交界干净，无光晕或渗色；虚化质地平滑，无块状。
- **背景灯光是软而暗的高斯团**，没有清晰边缘，亮度被平均成暗米色。真实镜头的焦外灯光是边缘较清楚、保持明亮的圆盘。

游戏模糊 pass `00f2b6068017c6c6`：每次 16 个采样，位置由顶点 shader 给出，权重只取决于各采样自身的 CoC（alpha），
与亮度无关；同一帧运行约 4 次（近 / 远层各两次），叠加后成为柔和的团状。r8 曾把每个采样旋转 ±10°（48 次），
叠加后几乎无差别，用户也看不出；且当时没证明替换实际执行。

## 做法

替换 `00f2b6068017c6c6`（`tools/patches/dof_bokeh_d1.hlsl`）：

- **关**：按游戏指令顺序重算，与游戏 shader 最大差 `1.4e-6`。
- **D1 高光散景**（Ctrl＋F2：关 / 普通 / 强，启动为普通）：亮采样在**颜色**平均中权重更大，
  `1 + k·h²`，`h = saturate((u − 0.45)/0.4)`，`u = 峰值/(1+峰值)`，普通 k = 6、强 k = 16。
  **alpha（CoC / 分层）仍用游戏权重**，近远层分离与边缘处理不变；不增加采样，性能不变。
- **D0 诊断**（Ctrl＋F3）：这一 pass 输出染成紫色，用来证明它在 GPose 中实际执行。
- 标签（Ctrl＋F7）：R 之后的 **B**，淡黄 = 普通、橙 = 强；底色延伸到 x 90。

## 离线验证

`docs/validation/dof-d1.json`、`docs/validation/dof-d1-synthetic.png`（自写顶点 shader 提供 16 点环形采样）：

- 全视口与 75% 动态视口：关与游戏 shader 差 ≤ `1.4e-6`。
- D1：alpha 与关完全相同（差 0）；采样范围内没有高光的像素完全相同。
- 单次 pass 中 6.0 点光源周围的平均亮度：关 0.30 → 普通 0.76 → 强 1.14。单次 pass 仍呈采样点阵；
  关时外圈逐渐变暗，D1 各点同样亮（多次叠加后应为边缘清楚的圆盘）。实际观感需 GPose 确认。
- D0：颜色按预期染紫，alpha 不变。色调 shader 不显示标签时与 T2d 完全相同。
- 官方 1.3.16 按原包启动为 D1 普通、诊断关，与 WARP 差 `6e-7`。
- `test_dof_d1.py`：相对 T2d 只新增模糊 shader、改色调与 INI，可精确回退。

## 部署

2026-10-14 00:04（上海时间），游戏退出状态由 T2d 切换。清单 SHA-256：
`cc86c1155e34e7fc8908b3a0328904e55be5b30fd3ebddda7153aaa730c1617b`。记录：`artifacts/return-deployment/d1-install.json`。
回到 T2d 的备份：`artifacts/install-backups/20261013T160447Z-2c8efa587a0b40adb43106075c48500b`。

## GPose 测试（2026-10-14）

光圈 F0.5（最强虚化）、自动对焦。记录：`docs/validation/dof-d1-gpose-2026-10-14.json`。

- **D0 生效**：虚化背景整片变紫，清晰的人物基本不变。`00f2b6068017c6c6` 确实在 GPose 中执行——r8 时缺的这一步已补上。
- **D1**：背景灯光区域 ≥240 的高亮像素 关 4,924 → 普通 6,043（+23%）→ 强 7,103（+44%）；区域平均亮度不变；
  人物与发丝边缘相同（全图平均差 1.0 级）。灯光核心更大更亮，但边缘仍是柔和渐变，不是硬边圆盘。
  原因：这些灯是有面积的灯罩而非点光源，且同一帧还有其他模糊 pass 叠加，会把边缘再次抹软；按亮度加权只能“更亮更饱满”。

## 结论：保留 D1，默认强

2026-10-14 用户选择保留 D1、默认强，景深项收尾。`artifacts/r11-dof-d1-strong`（`build_dof_d1.py --startup strong`）：
shader 与 `r11-dof-d1` 逐字节相同，INI 只把 `y6` 启动值从 1 改为 2。官方 1.3.16 按原包启动为强，与 WARP 差 `9.5e-7`
（`docs/validation/dof-d1-strong.json`）。2026-10-14 随 `r11-shadow-n1`（基于本包）一起部署。
如需硬边圆盘散景（D2：替换采样核，需先抓帧确认各模糊 pass 的作用）留到反射和法线阴影之后再考虑。

## 原待办

1. 开 GPose 景深，有背景灯光的场景，Ctrl＋F7 显示标签。
2. **D0**：按 Ctrl＋F3，虚化区域应明显变紫；再按一次恢复。不变紫说明当前 GPose 路径不走这个 shader，需要重新定位。
3. **D1**：Ctrl＋F2 切 关 / 普通 / 强（看 B 的颜色），各截一张，看背景灯光是否更亮、更像边缘清楚的圆盘。

## 开发重跑

```powershell
python tools/build_dof_d1.py artifacts/r11-radial-t2d-2026.10.06 artifacts/r11-dof-d1
python tools/validate_dof_d1.py artifacts/r11-radial-t2d-2026.10.06 artifacts/r11-dof-d1 artifacts/dof-d1-validation --runtime-check
python tools/test_dof_d1.py -v
```
