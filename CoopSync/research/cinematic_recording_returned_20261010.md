# 用户返回后的组件/任务实录

生成时间：`2026-10-10T09:01:51.460507+00:00`。来源：`C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\CoopSync\logs\runtime_manual_skip_20261010_returned`。

记录标签 `manual-skip` 仅表示意图；当前记录状态 `observations_recorded`，完整结束记录 `True`。
没有操作游戏或重新启动记录器；分析器只读取已保存的 JSONL，PID/hash 与样本稳定性作为证据门控。

PID `25612`；固定构建 SHA-256 `e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。

组件样本 2982，时间跨度 299937ms，稳定非空组件样本 114。
状态计数：`{"object_identities_match_no_flagged_component": 2815, "component_changed_during_reads": 53, "component_identity_match_raw_state_only": 114}`。
选择槽值计数：`{"0x0": 2821, "0x208807e7c30": 161}`。
质量问题：`[]`；采样中组件变化 53 次，这些样本不用于字段判断。
另有 10 个失稳样本在字段读取前停下，未再复核 owner；缺少复核记录不等于 owner vtable 实际不匹配。

## 人工状态补充

任务保留数据不能独立证明已进入/正在关卡。人工状态如有收据则列在下方，时间均为消息收据时间，不能作为精确加载、播放或跳过时刻。

- 收据 monotonic `65627453` / UTC `2026-10-10T08:53:53.651388+00:00`：用户刚接手兄弟的开发工作，不熟悉旧测试流程；此前界面为主菜单或未打开游戏（reported retrospectively; exact event time unknown）。

- 收据 monotonic `65627453` / UTC `2026-10-10T08:53:53.651388+00:00`：已选择继续进入关卡，主要任务显示：阻止倒数（receipt only; no exact load timestamp or skip claim）。

人工结果如未给出则仍等待确认；manual-skip 标签不升级为完成事件。

收据 `65627453` 前后各 1 秒捕获 20 个组件样本：`{"object_identities_match_no_flagged_component": 20}`，槽值 `{"0x0": 20}`。只对齐收据，不能当作精确剧情起止。

收据 `65627453` 前后各 1 秒捕获 20 个组件样本：`{"object_identities_match_no_flagged_component": 20}`，槽值 `{"0x0": 20}`。只对齐收据，不能当作精确剧情起止。

## 稳定组件与原始字段

| 组件指针 | 稳定样本 | 首末样本 | 原始值集合 |
|---|---|---|---|
| `0x208807e7c30` | 114 | 27..1431 | `{"0x58": [10], "0x5c": [10], "0xc0": [0], "0xc7": [1], "0xc9": [0], "0xca": [0]}` |

同地址稳定样本的字段变化 0 次；稳定组件地址变化 0 次；重复出现至少两次的同字段变化模式 0 个。
槽清零/重选只记为选择变化，不能标注播放开始/结束。原始状态 10 不命名为 Playing。相同地址也不能证明组件完整生命期或跨端稳定 cinematic_id。

## 任务记录与时间邻近

任务观察记录 2 条，相邻任务记录中发生变化 1 次。任务观察器以一秒间隔轮询且仅输出变化；最后一条记录不等于该时刻之后的持续心跳。

任务记录 0：monotonic `65428203`，digest `bc42929dab21d56f316be070361ecb5bcc06921b5400802dbda45dd7ea3e2091`；state_raw=1 项：`["GP_A1_FISK_SECURITY_COUNTDOWN"]`。

任务记录 1：monotonic `65728592`，digest `c9147e42891c9f27cf9989a2fe219a4047ec0c6e358e50df130780a4eb177e73`；state_raw=1 项：`["GP_A1_FISK_HACK_CIN2"]`。

任务变化时间 `65728592`：`[{"mission_id_raw": "0xD3665CA4", "mission_name_raw": "GP_A1_FISK", "objective_name_raw": "GP_A1_FISK_HACK_CIN2", "before_raw": 0, "after_raw": 1}, {"mission_id_raw": "0xD3665CA4", "mission_name_raw": "GP_A1_FISK", "objective_name_raw": "GP_A1_FISK_SECURITY_COUNTDOWN", "before_raw": 1, "after_raw": 2}]`。
最近前/后稳定组件样本：`1431` / `None`；距离 156375ms / 未观测，不能把长观察空缺当作紧邻关系。

## 可复查结论

JSON 中保存了原始字段/任务变化及最近稳定样本，供继续对照；尚不能给原始字段赋予 skip 或 completion 语义。
没有经过验证的跳过接口、过场开始/结束接口、稳定 ID、场景就绪或完整世界同步证据；`verified_callable_interfaces=[]`，所有验收标志保持 false。

## 复现

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\cinematic_recording_analysis.py
```

记录期间可以重新生成报告以捕获新前缀；报告写入独立 research 文件，不改原始日志。JSON 保存源前缀字节数/hash、字段转换、指针身份与任务变化。
