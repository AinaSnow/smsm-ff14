# H3：减弱高光压缩的对比候选

2026-10-10。根据首组截图中 H1 压弱头发亮丝、蓝灯光芯的结果修订。
**已部署，下一次启动默认 R10；Ctrl＋F8 对比 R10 / H3，Ctrl＋F7 显示或隐藏标签。**
H3 标签为橙色，R10 标签仍为蓝色。没有修改按键、INI、DLL 或 Dalamud 配置。
游戏文件仅更新 tone TXT/BIN 和管理凭据；没有进行热重载。

## 修改与取舍

H1 在最终混合之后，将峰值超过 0.85 的 RGB 整体压向 1。这一固定上限在首组实景中
削弱了明亮头发和发光物体，不能仅凭合成渐变保留更多数值就判为画质改进。

H3 将起点提高到 0.95，使用平滑权重，并限制各 RGB 分量相对 r10 最多降低 6%。
不设置固定输出上限，允许发光物体继续保留大于 1 的值。
阈值以下完全不变；RGB 比例及 alpha 保持原样。
这先解决上一版过压的问题，**尚不能证明 H3 比 r10 更好**，也不承诺恢复已裁切的细节。
效果可能很轻，最终取舍取决于实景是否有可见收益。

令 `p=max(R,G,B)`，`t=max(p−0.95,0)/0.75`，各 RGB 分量乘以 `1−0.06×t²/(1+t²)`。
这些数值是 shader 输出域，不是截图显示亮度百分比。

| r10 峰值 | H1 峰值（约） | H3 峰值（约） |
|---:|---:|---:|
| 0.85 | 0.85 | 0.85 |
| 1 | 0.925 | 0.999735 |
| 1.5 | 0.971875 | 1.468526 |
| 2 | 0.982692 | 1.920541 |
| 4 | 0.993182 | 3.773685 |
| 8 | 0.996918 | 7.525372 |

## 验证结果

- 4 组曝光/LUT 条件、6 类颜色渐变，实际 WARP 绘制/读回通过。
- 阈值以下和 alpha 最大误差均为 0；RGB 比例误差约 `5.96e-8`。
- 实测最大衰减约 5.997%，不超过 6%；中性渐变局部斜率最低约 0.90169，没有出现反向或压平。
- 隐藏标签时，OFF 与 r10 逐像素一致；ON 与独立静态 H3 参考逐像素一致。
- H3 的数字 3 字形逐格验证通过，R10 的数字 1 单独保留。标签不修改 alpha 或范围外像素。
- 官方 1.3.16 独立硬件子进程测试关闭/开启初始化，输出与 WARP 的最大差均约 `4.77e-7`。
- 3 项构建/精确回退测试通过，验证 H2 → H3 仅有两份 shader 文件变化，原包不变。
- 新版实机按键、切图和画质收益未填写通过；H2 的截图证明不能替代 H3 的实景对照。

数值记录见 `docs/validation/tone-highlights-h3.json` 和 `docs/validation/tone-compare-h3.json`。
输入是合成 HDR 渐变和常数增益 LUT，不是游戏抓帧。在随后强行裁至 0–1 的合成测试里，
超范围中性段仍然可能裁平，因此没有将该测试记作“找回高光细节”。

## 一轮实景对照

继续用原来的开关，在类似明亮头发和蓝灯场景中，观察 R10 / H3：

1. 头发亮丝和蓝灯光芯是否仍有明亮感。
2. 与 R10 相比是否有值得保留的改善，而不仅是变暗或难以分辨的差异。

若没有明确收益，保留 R10，不将 H3 设为默认。启动本来就默认 R10；无需更改配置。

## 开发重跑

```powershell
python tools/build_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h3-reference --curve gentle
python tools/build_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h3 --curve gentle --toggle
python tools/validate_tone_highlights.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h3-reference artifacts/tone-highlights-validation-h3
python tools/validate_tone_compare.py artifacts/r11-compat-c2 artifacts/r11-tone-highlights-h3-reference artifacts/r11-tone-highlights-h3 artifacts/tone-compare-h3 --runtime-check
python tools/test_tone_highlights.py -v
```

输出目录必须不存在。H1/H2 的生成方式及不可变包保留，新候选不覆盖旧包。

## 安装与回退

本机 21:33（上海时间）在游戏退出状态完成 H2 → H3 切换。
安装清单 SHA-256：`9aea5c4944c569a1d9ea4f38097e16e2b4f8e47b483d80dbe77c2849b8fd4e99`。
安装记录：`artifacts/return-deployment/h3-install.json`。

管理器回到这次安装前的 H2 时，使用备份目录
`artifacts/install-backups/20261010T133304Z-b6bbe2dc8f7b49ef955a30b01945657f` 的绝对路径：

```powershell
python tools/manage_preview.py rollback --client-root '<客户端目录>' --backup '<上述备份绝对路径>'
```

均需退出游戏。仅想保留 R10 画面时，按 Ctrl＋F8 切回蓝色 R10 即可。
独立 ZIP 安装仍须明确选择 `--profile daily` 才会载入对比 shader；默认安装为零替换。
源包目录和所有备份继续保留，F9/F10 和 `select --live` 不作为这一版的切换流程。
