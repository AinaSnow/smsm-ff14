# T1：色调曲线预设对比

2026-10-10。候选包 `artifacts/r11-tone-presets-t1`，基于 c2，只改 tone shader
（`72a656dfd52149ad`）和 INI 按键。**已部署，下次启动生效，默认 R10。**

Ctrl＋F8 循环 R10 → A → B → C，Ctrl＋F7 隐藏左上角标签；启动默认 R10。

| 标签 | 内容 |
|---|---|
| R10（蓝） | 现行 50% 游戏 + 50% SMSM，逐像素不变 |
| A（绿） | 100% SMSM 曲线作用于最大通道，保持色相 |
| B（橙） | 游戏色调的颜色 + SMSM 曲线的明暗（按 Rec.709 亮度比缩放，比值上限 4） |
| C（紫） | 同 A；曲线输出超过 0.7 后逐渐混向中性白（最多 50%） |

动机见[计划](PLAN-3DMIGOTO-RETURN-2026-10-10.md)：原 SMSM 逐通道套曲线且不用游戏 tone LUT，导致偏白。

## 输出上限

初版在 A/B/C 末尾把超过 1 的颜色按最大通道压回 1，R10 没有这一步，四种模式对比时会混入与曲线无关的差别，
因此已去掉。四种模式都只截掉负值，大于 1 的值照常传给后续阶段。
A/C 的峰值受曲线自身限制（约 `1/W`，合成用例 1.02–2.05）；
B 保留游戏色调的饱和度，饱和亮色可能明显超过 1。

## 离线验证

`docs/validation/tone-presets-t1.json`：

- 4 组曝光/LUT 条件、6 类颜色 HDR 渐变，实际 WARP 绘制/读回。
- 独立 numpy 参考先复现 c2 的 R10 输出（最大误差约 `2.1e-6`），再对照 A/B/C：相对误差 ≤ `5.7e-7`。
- 模式 0 与 c2 逐像素一致；alpha 不变；无负值、无非有限值；A/C 中性渐变单调。
- A、B 色相比例误差约 `6e-8`；C 在曲线输出 ≤0.7 处与 A 逐像素一致。
- 标签只改动边界内像素，A/B/C 字形逐格验证，四种标签各不相同。
- 官方 1.3.16 独立子进程按 `x7=0..3` 启动，输出与 WARP 最大差 ≤ `1.4e-6`。
- `test_tone_presets.py`：相对 c2 只改 shader 与 INI，相对 H3 只改 shader 与 INI，H3 → T1 → H3 精确回退。

**局限：** 合成 LUT 为常数增益，游戏色调不做压缩，所以 B 在此用例中峰值达 6–12，
这一数字不代表游戏画面。真实 LUT 下 B 的高光表现需要实景确认。
实机按键、切图和画质均未验证。

## 开发重跑

```powershell
python tools/build_tone_presets.py artifacts/r11-compat-c2 artifacts/r11-tone-presets-t1
python tools/validate_tone_presets.py artifacts/r11-compat-c2 artifacts/r11-tone-presets-t1 artifacts/tone-presets-validation-t1 --runtime-check
python tools/test_tone_presets.py -v
```

输出目录必须不存在。

## 安装与回退

2026-10-10 22:58（上海时间）在游戏退出状态由管理器从 H3 切换到 T1（`--profile daily`）。
清单 SHA-256：`b1a3b5d067f37f03216c31525f41fc1c5af82e5b2645d8749c99b76fb125cd51`；
Dalamud `IsDisableViewport=true` 已确认保持。安装记录：`artifacts/return-deployment/t1-install.json`。

退出游戏后回到 H3：

```powershell
python tools/manage_preview.py rollback --client-root '<客户端目录>' --backup '<备份绝对路径>'
```

备份目录为 `artifacts/install-backups/20261010T145824Z-94f938b34508443ebd2aca5db61dfca0`。
只想看 R10 时，按 Ctrl＋F8 循环回蓝色 R10 即可。

## 实景对照（2026-10-10 第一组）

用户三场景各四张（白天户外街道、户外角色近景、室内暖灯 + 彩色玻璃），标签按 R10/A/B/C 顺序识别正确，
T1 实际加载，Ctrl＋F8 四种模式均可切换。记录：`docs/validation/tone-presets-t1-scene-2026-10-10.json`。

| | 裁切像素（户外 / 室内） | 观察 |
|---|---|---|
| R10 | 0.96% / 1.74% | 近处台灯光芯为一片白 |
| A | 0.36% / 0.88% | 台灯保留暖色和灯罩结构；彩色玻璃橙红花纹分离更清楚；天空略蓝 |
| B | 4.72% / 1.57% | 观感接近 R10；户外天空单通道成片裁切，白屋顶、裙子也有裁切 |
| C | 0.36% / 0.87% | 裁切同 A，但灯芯和亮玻璃泛白、天空偏灰 |

近景场景镜头和表情有变化，肤色只作定性参考，四种模式差别不大。
初步建议 A；**用户选定 A。**

## A 默认版（已部署）

`artifacts/r11-tone-a-default`（`build_tone_presets.py --default-a`）：shader 与 T1 逐字节相同，只改 INI——
启动 A、标签隐藏，Ctrl＋F8 在 A / R10 间切换，Ctrl＋F7 显示标签。官方 1.3.16 按原包启动输出与 WARP 的 A 一致
（`docs/validation/tone-a-default.json`）。

2026-10-10 23:49（上海时间）游戏退出状态由 T1 切换。清单 SHA-256：
`e0804b681fcd63abc6f8b0792c5e6548478bd5f15e1f3dcf60329ec716322617`；`IsDisableViewport=true` 保持。
回到 T1 的备份：`artifacts/install-backups/20261010T154913Z-edbc829d5de44feb862dc0d0216077ae`。
记录：`artifacts/return-deployment/a-default-install.json`。待实机确认：启动即 A、Ctrl＋F8 首按切到 R10。

## 原待办

在白天户外、室内暖灯、角色近景三类场景，各截 R10/A/B/C 四张（标签可见）。
重点看：肤色和浅色衣料是否仍偏白；地区调色是否保留（B）；亮灯、日光衣料是否过艳（A 对 C）；
B 的高光是否过亮。选一个作为默认；没有一个优于 R10 就保留 R10，结束色调项。
