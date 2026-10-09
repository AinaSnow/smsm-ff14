# M2：Stagehand 临时单灯与有限采集薄桥

前置条件已由 M0/M1 普通模式测试取得：单灯持续受光，三轮开关恢复，颜色/灯位/范围有效，禁用 Stagehand 后恢复。M2 只把该过程连接到现有定点采集，不修改 shader，不定位新 GPU 灯缓冲，也不接受地图原有光照改善。

## 接口与所有权

独立 Dalamud 插件 `SMSM.StagehandBridge`，API 15 / .NET 10，固定官方 Stagehand.Api / Definitions 0.5.5，运行时要求 IPC major 1、minor 至少 2。加载时不创建灯，不自动运行；清理上次记录的自己所属 ID。

每次手动 run 分配 `smsm.m2.<随机 ID>`，在任何 native 创建之前持久记录所有权。只调用该 ID 的 create/update、visibility 和 destroy；不操作用户 local Stage，不枚举并删除所有 temporary Stage。实例及 journal 每次停止都会清理；provider 不可用时保留待清理 ID，恢复后重试。

固定版 API 的 create/update 实际立即建立 live Stage，故关闭预设采用禁用 Point 定义并隐藏，不能把文档里的“需 show”当成创建无副作用的保证。退出/异常路径也按可能已创建对象处理。

## 有限流程

`/smsm-light run` 或向已加载桥提交一次 run：

1. 要求普通游戏、角色可用、无切区、兼容 Stagehand，固定当前场景和玩家位置。灯位一次性锚定为玩家位置加 `(2,1.5,1.5)` 世界偏移；原位置只记私有日志。
2. 核对现有 ReShade 安装凭据与文件 hash，取得单会话锁，提交 off 并等回执，确保 r8、marker、其他 audit 关闭。
3. 依次 OFF、暖光 `(1,.35,.1)`、冷光 `(.1,.35,1)`。强度 8、范围 10，无额外阴影，一盏 Point。
4. 每态等待两秒，再向现有 `ambient-command.txt` 发 `sample e86f0d4916054deb 0`，只做已有的裙装路径取样。等待新目录和完整 sample 报告，最多 15 秒；拒绝旧目录、忙状态、错误身份和超过预算的报告。
5. 三次完成即销毁所属 Stage，释放锁；不保持补光、不进入连续动画。`stop` 可随时停止。移动超过 .15 世界单位、场景变化、注销、进入 GPose、provider 失去或插件禁用均停止并清理。

这只是控制参数到既有采集目录的协调，不声明捕获的是灯对应的某个缓冲区，也不做 M3 原生数据解释。固定 target/skip 是选择提示，后续必须核对当前帧是否仍是玩家裙装；不把它推广为全部角色。

## 安全与恢复行为

正常运行只在 framework 线程执行 IPC。所有阶段有限时；原 SDK 的 create/update、hide、destroy 结果要核对。中断先停止采集管线并删除自己的 Stage。命令不能覆盖 pending 文件；取消只移除自己尚未消费的请求，已消费的自己的 audit 发 off 终止，不清空别人队列。

所有参数、位置、场景、ID、状态与采集目录只写到私有 plugin config 日志。持久所有权用于插件 reload/crash 后恢复；旧 run 请求在启动时丢弃。status 只在变化时写入，默认 idle 不持续刷盘。

桥项目使用 AGPL-3.0-or-later，随本地最小包带 NOTICE 和许可证；只包自身 DLL、manifest/deps 及官方 API/Definitions，不把 Dalamud runtime 复制到插件目录。

## 检查与实机验收

14 项离线检查通过：官方 IPC definition 三预设往返、三态有限结束、warm 活跃期间移动/场景/provider 变化、采集错误/超时/手动停止、创建失败、重启所有权恢复、真实文件队列/新报告检查、错误 target 拒绝、外来队列不被取消、自己的 pending 和消费后未 poll 的 audit 清理。配置登记模拟保留原条目，并拒绝运行中修改。

上述不是实际 Dalamud IPC 或 GPU 采集成功的证据。下一次实机启用官方 Stagehand 与此桥，用户普通模式在咖啡馆站定，一次 run。应得到三份不同的完整目录、实际 IPC revision、三个参数状态和最终无所属 Stage；再验证一次手动/场景中断。通过前保持默认不运行。

2026-10-09，用户退出游戏后，已登记核对过的 0.1.0.0 最小包。实际配置比对确认其他开发插件条目保留，桥 StartOnBoot 为 false，原 M1 local 灯已禁用，r8、marker、audit 状态均关闭；本次没有修改游戏 DLL。登记完成仍不代表实际 IPC、三次采集或清理验收通过，需要重新进入普通模式并手动启用官方 Stagehand 与 SMSM Stagehand M2 Test Bridge。

使用 `/smsm-light status` 查看状态，`/smsm-light stop` 停止。已有 M1 local 灯保持禁用，避免两个测试灯混用。r8 关闭，r10 冻结包不变。切图/退出、阴影、GPose及性能的待验收项继续保留。

证据：[M2 离线准备](validation/stagehand-m2-preflight-2026-10-09.json)。
