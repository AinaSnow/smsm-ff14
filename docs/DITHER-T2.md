# T2：去色带抖动对比

2026-10-11。当前候选 **T2b**：`artifacts/r11-dither-t2b`（`tools/build_dither_t2.py`），基于色调 A 默认版。
**已部署，下次启动生效：色调 A + 抖动开。**

## 想解决的问题

8 位输出下，天空渐变、暗部、雾和暗角会出现一圈圈色阶条纹；色调 A 提高了对比，条纹可能更明显。
预期：开启后条纹变成细密均匀的颗粒，近看无明显噪点、整体亮度不变。

## T2 第一版：抖动没有到达屏幕

第一版沿用 r10：抖动放在色调后的场景输出拷贝 `23d27700572e0c4d`，用 INI 阶段标记只处理色调后那一次。
实机标签只有 A、没有 D（截图前按过 Ctrl＋F6）。诊断版 `r11-dither-t2-diag` 让该 shader 每次运行都画彩色 D，
**DLSS 和 AMD FSR 下都没有 D**：这次拷贝的输出不在显示路径上。也就是说 r10 的“色调后输出抖动”
在当前客户端里实际上从未生效；r10 当时只用抓帧回放推断了调用顺序，没有实机确认。

## T2b：抖动放进色调 shader

色调 shader `72a656dfd52149ad` 的标签在 DLSS/FSR 下都可见，说明其输出会显示。T2b 在色调输出之后、标签之前
加入与 r10 完全相同的噪点（DitherMode 4，±1/255，纯黑纯白和大于 1 的值不动，alpha 不变）。
不再使用 `23d2…` 和 INI 阶段标记。暗角抖动 `782e995758bf001d` 保留。

| 按键 | 作用 |
|---|---|
| Ctrl＋F6 | 抖动开 / 关（色调内抖动和暗角抖动同时；启动为开） |
| Ctrl＋F7 | 显示标签；抖动开启时绿色 A 右边有白色 **D** |
| Ctrl＋F8 | 色调 A / R10，不变 |

注意：色调内抖动由 INI 的 z7 控制，属于色调 shader；管理器的 `dithering` 效果项只包含暗角 shader。

## 离线验证

`docs/validation/dither-t2b.json`，WARP 实际绘制：

- 抖动关：四种色调模式 × 标签开关，与已部署的 A 默认版逐像素一致。
- 抖动开：把 r10 原输出抖动 shader 作用在“抖动关”的图像上，结果与 T2b 逐像素一致（A 与 R10 两种模式）。
  噪点 ≤ 1/255，中间调平均偏移 `3.7e-7`。
- 中性渐变按列量化到 8 位后，列平均与精确值的误差 0.242 → 0.094 级。
- D 只在标签和抖动都开时出现，只改动标签范围。
- 暗角：关与游戏原 shader 一致，开与 r10 一致。
- 官方 1.3.16 按原包启动：A、标签隐藏、抖动开，与 WARP 最大差 `2.4e-6`。
- `test_dither_t2.py`：相对 A 默认版只改色调 shader 与 INI、新增暗角 shader；A → T2b → A 精确回退。

**已知：** r10 的暗角抖动在暗角强度为 0 时仍给约一半像素加最多 1/128 的暗角颜色（平均约 0.2%），未修改。
色调输出之后若还有更低精度的中间格式，±1/255 的噪点可能被部分吞掉，需要实景确认。

## 安装与回退

2026-10-11 01:21（上海时间）游戏退出状态由诊断版切换。清单 SHA-256：
`b6cbe48cc1ccf0fb9e045889ce03a47fd973908504e3e657578e28b586f2b0b4`；`23d2…` 文件与 INI 阶段标记已从游戏目录移除；
`IsDisableViewport=true` 保持。记录：`artifacts/return-deployment/t2b-install.json`。

回到 A 默认版（无抖动）：退出游戏后
`python tools/manage_preview.py install --client-root '<客户端根目录>' --package artifacts/r11-tone-a-default --profile daily`。
临时关闭抖动按 Ctrl＋F6。

## 实景对照（待做）

找有天空渐变（晴天或黄昏）、暗室或雾的场景，站定不动，开标签，按 Ctrl＋F6 各截一张 PNG（游戏截图键）。
看条纹是否减少，近看颗粒是否可接受。

## 开发重跑

```powershell
python tools/build_dither_t2.py artifacts/r11-tone-a-default artifacts/r11-dither-t2b
python tools/validate_dither_t2.py artifacts/r11-tone-a-default artifacts/r11-dither-t2b artifacts/dither-t2b-validation --runtime-check
python tools/test_dither_t2.py -v
```

第一版 T2 与诊断版由 Git 历史中的同名构建器生成，包目录保留在 artifacts。
