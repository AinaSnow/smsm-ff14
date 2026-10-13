# N0 / N1：法线阴影

2026-10-14。`artifacts/r11-shadow-n1`（`tools/build_shadow_n1.py`），基于 D1 强（`r11-dof-d1-strong`），客户端 2026.10.06。
**已部署**（同时带上 D1 默认强）。

## 背景

反射：用户认为游戏现有反射还行，跳过（2026-10-14）。

法线阴影在 r4 已移植进两个主太阳光 shader：`8b384acd7a03c836`、`e9f57e0834b642f5`。在每个像素沿太阳方向的屏幕投影
走 24 步（约 64 px），用法线和深度找出挡住阳光的细小起伏，把额外的细节阴影以 `min()` 并入游戏的阴影遮罩（t8）。
游戏阴影贴图分辨率不够的衣褶、砖缝、浮雕等处会多出贴合表面的小阴影。r10 中为实验、默认关闭，
**从未在画面上证明执行，用户也没对比过**。

## 做法

沿用 r10 的 ASM 插入（`patch_shader_asm`：原始指令精确往返；辅助代码寄存器重编号；常量读取不超出宿主）。
辅助 shader `tools/patches/normal_shadow_n1.hlsl` 与 r10 的 `normal_shadow.hlsl` 相同，只在开头读取 IniParams：

- **N1**（Ctrl＋F1，x5，启动为开）：开 = r10 法线阴影；关 = 返回 1，`min(遮罩, 1)` 保持游戏原值。
- **N0 诊断**（Ctrl＋F11，y5）：返回 0，太阳直射被完全遮住——画面中阳光照到的地方应明显变暗。
- 宿主原本没有 t120，额外加一条 `dcl_resource_texture1d ... t120`（3DMigoto 为所有 shader 绑定 IniParams）；
  其他资源必须是宿主已有。辅助代码的提前返回改为跳出外层 `loop`。
- 标签（Ctrl＋F7）：B 之后的浅蓝 **N**；底色延伸到 x 102。

## 离线验证

`docs/validation/shadow-n1.json`。沿用单灯研究的合成 G-buffer 与游戏原始 DXBC 渲染，太阳方向设为斜射：

- 两个 shader，平面 / 斜面 / 球 / 法线贴图起伏四种场景：**关 = 游戏原 shader 逐位一致**；
  **N0 = 遮罩为 0 时的游戏输出，逐位一致**；**N1 = r10 法线阴影，差 0**；N1 只会变暗。
- 平滑表面（平面、斜面、球）N1 不改变任何像素；法线贴图起伏（低太阳）中 6,144 个像素有 107 个（1.7%）多出阴影，
  均值变暗 0.005。离线效果很小，实际明显程度取决于游戏材质的法线贴图。
- 官方 1.3.16 按原包启动为 N1 开，与 WARP 差 `2.8e-7`。
- `test_shadow_n1.py`：相对 D1 强只新增两个光照 shader、改色调与 INI，可精确回退。

## 部署

2026-10-14 00:58（上海时间），游戏退出状态由 D1（普通默认）切换，D1 默认强随本包一起生效。清单 SHA-256：
`ba7afa24537a18c8e2eed76ce6e83490b7d5d73183f89c5169477f6153c3c307`。记录：`artifacts/return-deployment/n1-install.json`。
回退备份：`artifacts/install-backups/20261013T165848Z-68cc1ec94ade4b27a89829d791b3e933`。

## 游戏内测试（2026-10-14）

晴天低太阳、石板路与角色。N0 `010152`、N1 开 `010202`、N1 关 `010210`。记录：`docs/validation/shadow-n1-scene-2026-10-14.json`。

- **N0 生效**：路面阳光和柳树影子整片消失（全图均值 112 对 130），两个太阳光 shader 确实执行。
- **N1**：石板缝背光一侧阴影更深、更清楚，石板立体感增强；裙摆褶边下方阴影更多。静止石板区域 6.0% 像素变暗超过 4 级，
  平均变暗 0.6 级。用户反馈“开着的时候有些地方会有自然的阴影下来”。
- 放大可见新阴影边缘有轻微颗粒 / 锯齿，来自 N1 每像素的随机抖动采样；运动中可能表现为轻微闪烁，待用户确认。
- 柳树和角色待机动作在两张之间有移动，全图统计含运动差异。

## 原待办

白天晴天、太阳较低的户外（斜阳最明显），有衣褶、石墙、砖地的地方，开标签：

1. **N0**：Ctrl＋F11，阳光照到的地方应整片变暗（像突然阴天）；再按一次恢复。不变说明当前光照路径不走这两个 shader。
2. **N1**：Ctrl＋F1 开 / 关（看 N），各截一张，近看衣褶、墙面起伏处是否多出贴合的小阴影，是否有噪点或闪烁。

## 开发重跑

```powershell
python tools/build_shadow_n1.py artifacts/r11-dof-d1-strong artifacts/r11-shadow-n1
python tools/validate_shadow_n1.py artifacts/r11-dof-d1-strong artifacts/r11-shadow-n1 artifacts/shadow-n1-validation --runtime-check
python tools/test_shadow_n1.py -v
```

需要 `smsm-ff14/artifacts/decompiler/1.3.16/cmd_Decompiler.exe`。
