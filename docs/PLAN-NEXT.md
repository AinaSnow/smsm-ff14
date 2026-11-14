# 后续计划（2026-11-14）

r11 的画质项全部完成（见 [RELEASE-r11](RELEASE-r11.md)）。之后以维护和降低安装门槛为主，不再主动加新效果。

## 已完成（r11.1）

- 客户端 2026.11.03：重新提取 31,018 个 shader，与 2026.10.06 完全一致，包已重标签并安装到本机。
- 2026-10-14、2026-10-28 两次 Dalamud 崩溃已检查：调用栈分别来自 TriadTournament（经 OmenTools / KamiToolKit 回调）
  和 SimpleTweaks（卸载时保存配置），均不涉及 3DMigoto、渲染或 DirectComposition 窗口路径。
- 双击安装：`Install.cmd` / `Status.cmd` / `Uninstall.cmd` / `Rollback.cmd`（`tools/easy_install.py`），
  测试 `tools/test_easy_install.py` 在隔离的假环境中覆盖自动查找、Dalamud 设置、安装、重装、卸载、回退和版本不符。
- 维护者一键更新检查：`tools/check_client_update.py`（提取 → 对比 → 未变则重标签并打包，变了则列出受影响效果）。

## r11.1 追加（用户决定，2026-11-14）

- **去掉 Python 依赖**：ZIP 自带官方嵌入式 Python 3.13.17（python.org，SHA-256 与官方一致），启动器优先使用它；
  在系统 PATH 中没有任何 Python 的环境下，安装 / 状态 / 卸载 / 回退全流程实测通过。
- **去掉版本检查**：双击安装在游戏版本不同时只提示并照常安装（3DMigoto 按 shader 哈希替换，改动过的 shader 对应效果
  自动失效）；命令行管理器保留严格检查，供维护者使用。
- 顺带修正：手动指定的游戏目录无效时报错，不再静默改用自动找到的目录；数据目录路径过长时在修改前拒绝。

## 待定

| 项目 | 内容 | 建议 |
|---|---|---|
| 景深硬边圆盘（D2） | 替换采样核，需先抓帧确认各模糊 pass | 暂缓，有需要再做 |

## 游戏更新时的固定流程

1. `Status.cmd` 显示“当前游戏版本未验证”，或某个效果消失。
2. `python tools/check_client_update.py --client-root <游戏根目录> --package <当前包> --previous <上次提取>`。
3. 全部未变：用新包安装并按需发布；有变化：只重新适配列出的效果，其他效果不动。
