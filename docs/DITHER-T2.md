# T2：去色带抖动对比

2026-10-11。候选包 `artifacts/r11-dither-t2`（`tools/build_dither_t2.py`），基于已部署的色调 A 默认版，
加入 r10 已移植、当前管线实际执行的两个抖动 shader。**已部署，下次启动生效：色调 A + 抖动开。**

| shader | 作用 |
|---|---|
| `23d27700572e0c4d` | 色调映射后的场景输出拷贝：加 ±1/255 的居中噪点，黑白端点渐隐，保留 NaN 清理和 alpha |
| `782e995758bf001d` | 暗角：alpha 加 ±1/128 的 Bayer 8×8 抖动 |

`12dd4d7295446a19`（旧输出抖动）在 2026.09.15 抓帧中未执行，不加入。

## 想解决的问题

8 位输出下，天空渐变、暗部、雾和暗角会出现一圈圈色阶条纹。色调 A 提高了对比，条纹可能更明显。
预期：同一场景开启后条纹变成细密均匀的颗粒，近看无明显噪点、整体亮度不变。

## 按键

- 启动：色调 A + 抖动开。
- Ctrl＋F6：抖动开 / 关（两个 shader 同时）。
- Ctrl＋F7：显示标签；抖动开启时绿色 A 右边多一个白色 **D**。
- Ctrl＋F8：色调 A / R10，不变。

输出拷贝 shader 在一帧里会被调用多次。沿用 r10 的阶段标记：色调映射置 `x=1`，最终拷贝消费后置 0，Present 复位，
只有色调之后那一次加噪点。

## 离线验证

`docs/validation/dither-t2.json`，WARP 实际绘制：

- 关：与游戏原 shader 在有限输入上逐像素一致（含 NaN 清理）；未被标记的拷贝即使开关为开也不变。
- 开：与 r10 二进制逐像素一致；噪点 ≤ 1/255，中间调平均偏移 `1.6e-6`，纯黑纯白不变，alpha 不变。
- 模拟 8 位量化后，渐变按列平均的色阶误差 0.25 → 0.083 级。
- 暗角：关与游戏原 shader 完全一致，开与 r10 一致。
- “D” 只在标签和抖动都开时出现，只改动 40–50 × 28–42 范围。
- 官方 1.3.16 子进程按原包启动：暗角启动即开；没有色调阶段时拷贝保持原样。阶段标记需要真实帧，未在离线测试中触发。
- `test_dither_t2.py`：相对 A 默认版只新增两组 shader 文件并改 INI；仅选色调时不安装抖动 shader；A → T2 → A 精确回退。

**已知：** r10 的暗角抖动在暗角强度为 0 时仍会给约一半像素加最多 1/128 的暗角颜色（平均约 0.2%）。属于 r10 原行为，未修改。

## 安装与回退

2026-10-11 00:44（上海时间）游戏退出状态由 A 默认版切换（`--profile daily` = 色调 + 抖动）。
清单 SHA-256：`696d9478733955b70a1df36f1893573cf7218a8537a985ffd5bac56d00ba15fc`；`IsDisableViewport=true` 保持。
记录：`artifacts/return-deployment/t2-install.json`。回到 A 默认版的备份：
`artifacts/install-backups/20261010T164402Z-700f138698c747289e98d07404b71994`（退出游戏后 `manage_preview.py rollback`）。
只想临时关抖动按 Ctrl＋F6。

## 实景对照（待做）

找有天空渐变（晴天或黄昏）、暗室或雾的场景，站定不动，按 Ctrl＋F6 各截一张（开标签）。
看条纹是否减少，近看颗粒是否可接受。有明显收益就把抖动并入日常默认；看不出差别也可以保留（代价很小），
出现可见噪点就关闭。

## 开发重跑

```powershell
python tools/build_dither_t2.py artifacts/r11-tone-a-default artifacts/r11-dither-t2
python tools/validate_dither_t2.py artifacts/r11-dither-t2 artifacts/dither-t2-validation --runtime-check
python tools/test_dither_t2.py -v
```
