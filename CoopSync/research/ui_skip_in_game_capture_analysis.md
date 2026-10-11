# OverlayUI 手动测试记录的只读分析

来源：`C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\CoopSync\logs\runtime_manual_skip_20261010_in_game\ui_skip.jsonl`。本次读取 3611091 字节，SHA-256 `c7820349b56b449d3dbb3f6a02bc42e7dd0bfb56da0e34332e3c3b234d620b61`。已捕获结束记录。

共 2982 个样本，独立复核后接受 2982 个；最后 sample `2981`。接受条件包含固定对象 RVA、双虚表值/前后稳定标记、精确字段集合及指针与原始字节一致性。

| 字段 | 已接受样本的不同原始字节 |
| --- | --- |
| `0x210` | `00` |
| `0x214` | `00000000` |
| `0x220` | `0000000000000000` |
| `0x228` | `0000000000000000` |

稳定非零回调目标数量：**0**。已核验可调用接口数量：**0**。

人工报告只作为 receipt 保存：

- `2026-10-10T08:57:08.816656+00:00`：用户明确：我现在正在剧情中。已指导按游戏提示跳过，无提示则自然播完；尚未确认完成。。事件时间状态：receipt only; exact cinematic start unknown；skip_verified=`False`。
- `2026-10-10T08:58:17.420031+00:00`：用户已过完该段剧情；没有跳过剧情选项，随后重新进入战斗。。事件时间状态：retrospective natural-end report; exact start/end time unknown；skip_verified=`False`。
- `2026-10-10T09:00:32.768303+00:00`：战斗后屏幕提示战斗专注；用户确认机房门可以通过，已走到外面。。事件时间状态：retrospective receipt; exact traversal time unknown；skip_verified=`None`。

这些 receipt 不是精确加载、播放或跳过时刻。当前零槽不能证明没有过场；保留的任务/电影对象内存也不能证明存在活动场景。目录的 manual-skip 意图标签不证明玩家实际播放或跳过。分析器只读保存文件；不启动记录器，不打开游戏进程，不解引用上下文或执行游戏函数。
