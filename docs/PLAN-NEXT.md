# 后续计划（2026-11-14）

r11 的画质项全部完成（见 [RELEASE-r11](RELEASE-r11.md)）。之后以维护和降低安装门槛为主，不再主动加新效果。

## 已完成（r11.1）

- 客户端 2026.11.03：重新提取 31,018 个 shader，与 2026.10.06 完全一致，包已重标签并安装到本机。
- 2026-10-14、2026-10-28 两次 Dalamud 崩溃已检查：调用栈分别来自 TriadTournament（经 OmenTools / KamiToolKit 回调）
  和 SimpleTweaks（卸载时保存配置），均不涉及 3DMigoto、渲染或 DirectComposition 窗口路径。
- 双击安装：`Install.cmd` / `Status.cmd` / `Uninstall.cmd` / `Rollback.cmd`（`tools/easy_install.py`），
  测试 `tools/test_easy_install.py` 在隔离的假环境中覆盖自动查找、Dalamud 设置、安装、重装、卸载、回退和版本不符。
- 维护者一键更新检查：`tools/check_client_update.py`（提取 → 对比 → 未变则重标签并打包，变了则列出受影响效果）。

## 待定

| 项目 | 内容 | 建议 |
|---|---|---|
| 发布 r11.1 | 推送并建 GitHub Release，附新 ZIP | 待用户确认 |
| 去掉 Python 依赖 | 打包嵌入式 Python（约 10 MB），或把安装器改写为 PowerShell | 有其他用户安装困难时再做；嵌入式 Python 改动最小 |
| 游戏更新后的门槛 | 现在版本不一致即拒绝安装，必须等新包。可改为：版本不一致时仍允许安装并警告“按哈希生效、变化的效果自动失效” | 保持严格：重标签只需几分钟，严格更安全 |
| 景深硬边圆盘（D2） | 替换采样核，需先抓帧确认各模糊 pass | 暂缓，有需要再做 |

## 游戏更新时的固定流程

1. `Status.cmd` 或管理器 `status` 看到版本不匹配。
2. `python tools/check_client_update.py --client-root <游戏根目录> --package <当前包> --previous <上次提取>`。
3. 全部未变：用新包安装并按需发布；有变化：只重新适配列出的效果，其他效果不动。
