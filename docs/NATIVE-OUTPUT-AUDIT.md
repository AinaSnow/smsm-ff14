# r6：目标绘制输出审计

r5 在游戏里持续替换目标 hair PS，用户仍未见紫色。隔离硬件绘制证明同 DLL 的 marker 能改变真实像素，因此本轮定位实际游戏的输出状态和绘制前后颜色，不重复做肉眼找差异。

## 范围与证据

新增 `audit` 命令，只标记并采集下一个帧，帧末立即关闭标记，等待 GPU 完成后保存结果。保持环境光关闭，不将测试标记当成画质收益。

- 只匹配已核验的头发 PS `980154264a89fba1`，最多 128 条绘制状态和 occlusion query。记录 RTV 槽/本轮资源序号、写入掩码、混合因子/运算、sample mask、深度/模板函数、裁剪/视口和 predication。
- 前 4 次目标绘制的 RTV0 各保留绘制前、绘制后和帧末三份 staging 副本；另外保留 Present 入口的 backbuffer。总 staging 数据不超过 256 MiB。仅支持已知格式、单样本和单 slice；其他情况报告缺失/预算状态，不静默转换。
- 不改变实际绘制的深度、模板、混合、predication 或颜色写入掩码。仅采集用的 GPU copy 临时关闭 predication，并在实际 draw 前恢复。使用独立 query，异步检查 GPU 完成，十秒超时报状态，不进行无界等待。
- 继续保留原 marker shader 的 alpha/discard。自动绘制、间接绘制、延迟 context 不冒充已跟踪目标；ReShade 的 DrawAuto 以零实例回调，现明确跳过。

每份 raw 数据保存格式、宽高、subresource、字节数和 SHA。`analyze_native_output.py` 验证这些约束后统计同一目标的像素变化，包括“该 draw 改动后又在帧末被改动”的交集；支持的常见 RGBA/R11 格式另给 RGB 字节计数，避免把仅 alpha 改变解释为颜色变化。原始字节差异不是肉眼阈值。

Occlusion samples 仅为独立证据，不等于成功写色；有样本但 write mask 为零的测试正好说明这个区别。后续覆盖统计也不能确定覆盖它的具体 pass，backbuffer 只是最终阶段对照，不自动建立源目标到最终像素的完整合成关系。未采样的目标、其他头发变体及玩家对象关联保持未知。

## 已验证

官方 ReShade 硬件 host 使用真实三顶点、精确原始 PS 和完整合成输入，验证四种情况：

| 情况 | Occlusion samples | 绘制改动像素 | 随后又改变 |
|---|---:|---:|---:|
| 正常 marker | 768 | 768 | 0 |
| 颜色写入掩码为零 | 768 | 0 | 0 |
| marker 后清屏覆盖 | 768 | 768 | 768 |
| predication 阻止绘制 | 0 | 0 | 0 |

前/后/帧末 raw 读回及 hash 核对通过，predication 的对象/值恢复通过，结束后原输出恢复通过。模拟客户端验证 r5→r6、事务中断恢复、r10 恢复、配置/runtime 保留、旧候选拒绝 `audit` 和命令不覆盖。验证曾发现 `uint8_t` 被流输出为字符的问题，已将模板掩码显式转换成数值；测试期的失败候选不安装。

摘要见 [验证记录](validation/native-output-r6-2026-10-09.json)。这些是隔离场景证据，游戏里的“无紫色”原因仍待真实捕获，不能提前宣布是某种写入限制或后续覆盖。

## 操作

客户端停机更新，保留 r5/r4/r10。新包及新能力默认关闭。进游戏、固定场景站定后：

```powershell
python tools/request_native_ambient.py '<game 目录>' audit
python tools/analyze_native_output.py '<采集目录>' --output '<新的分析文件.json>'
```

状态文件的 `output_audit_active` 与 `output_audit_directory` 给出采集状态和本轮目录。采集完成后不自动开启任何效果；用户无需按热键、移动镜头或截图。原始资源和图像保留本地，不提交 Git。

2026-10-09 03:18（上海时间），用户确认退出后已安装 r6，插件 hash 和 `output_audit` 能力凭据核对通过，r5 单独备份，runtime/用户配置保留。当前等待进游戏后的单帧采集，默认关闭。
