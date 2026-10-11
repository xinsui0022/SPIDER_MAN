# 门、Health 实例身份候选：阶段成果

找到并实际读取了独立于 entity local handle 的 64-bit 数组键。当前只称 raw candidate；来源、跨存档加载稳定性、跨主客机映射和动态 spawn 唯一性仍未核验。不能把它直接升级为 network entity ID。

## 固定构建与证据

SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。脚本 `research/world_entity_identity_probe.py` 只读游戏 PE 文件，复核 10 个固定反汇编范围与 RTTI inheritance。JSON 保存指令字节和 RVA。所有 native 入口只用于静态核对，没有调用。

`0x159DA80` 是 15 字节 leaf getter：从 `[entity+0xC]` 取 index，从 `[game+0x7A4A450]` 取数组指针，再读 `array[index*8]`，返回 qword。索引/8-byte 布局已闭合；数组 allocation/capacity 和键的生产者尚未闭合。

`0x1F7B550 → 0x1F7B8E0` 被 DoorScriptAction `0x1F35643` 调用来构造 source actor key。builder 有三条路径：

| 路径 | 来源 | reverse resolver | 判断边界 |
|---|---|---|---|
| 高位为 1 的 qword | `0x159DA80` 数组键 | `0x1F7B760` 经字典 `game+0x7A4A458` / `0x1BCF530` 查 entity | 目前最有价值的稳定 actor 身份候选；仍未知生产/存档/跨机来源 |
| tag `0x1000000000000` | entity `+0xA8` 经 `0x1984400` 得 state object 的 `+4` DWORD | 低 DWORD 又交 `0x1984400`，查本地 pool `game+0x7A65F00`，核对 generation byte `+0x11D` | native state/pool handle 路径，不能当已验证的跨机稳定 ID |
| tag `0x2000000000000` | component engine descriptor `0x7C54E80` 的 `+0x104` DWORD | 经 `0x215F100` 与 entity local resolver | RTTI/vtable getter 将 descriptor 闭合到 ShotBase，属于剧情镜头对象；不适合当通用门/敌人 ID |

builder 优先 state 路径；否则只有数组键高位为 1 时直接返回它，非负数组值还会查 ShotBase。数组值本身与这些 tagged 表示必须区分。`ActorUID` 名称在静态 metadata `0x4FD4678` 出现，是进一步查找 actor 身份的线索；尚未把该类型名称和上述无符号函数链闭合，名称也不能证明每个 raw 数值具备稳定语义。

## 已实现的一次有界只读验证

`research/world_identity_runtime_probe.py` 只从已完成的 JSONL 行选择最多 16 个 previously accepted Door/Health 实例，使用既有 `WindowsBackend/Session` 的 executable hash / PID / process path / module gate；另外复核 live getter 的 15 字节与固定构建一致。只使用读/查询权限，不 scan 全进程、不调用游戏函数、不注入、不 hook、不写游戏。

读取前后验证 global entity table/count/key-array pointer；每个对象验证 entity index/generation、component vtable/owner/local handle、两次 raw qword key。原始 source table/count/identity 不匹配就拒绝。限制 512 reads / 4096 bytes，最大单读 15 bytes；array capacity 仍明确 unknown。前后相等不保证排除 ABA。

纯 mock `research/world_identity_probe_selfcheck.py` 已通过 22 项检查：身份/键/全局 header 变化、错误 vtable、短读、16-object 与 reads/bytes 配额。没有使用游戏进程。

实际新进程 PID `10516` 的成功保存结果：accepted `16`、gaps `0`，类型 `{'DoorAnimated': 1, 'Health': 15}`，其中高位为 1 的 key `15`；实际 budget `{'read_calls': 199, 'read_bytes': 1143, 'max_read_calls': 512, 'max_read_bytes': 4096}`。见 `world_entity_identity_runtime_20261011_10516_level.json`。初次读取旧 scene 记录时全部16候选在 entity identity 重验失败，未接受key，说明场景切换时不能沿用旧handle。

一扇 DoorAnimated 的 raw key 是 `0x966E09ABC9EE1EF3`，只是在当前进程内该观测窗口不变。后续应在同一保存点重载及第二台主客机验证同一场景 actor 的一致性，并检查多实例/dynamic spawn 会否重复；目前没有完成这些检验。

## Health 与 BotHealth 的实际关系

RTTI hierarchy 明确 `BotHealth → Health → Component`，三个 subobject displacement 都为 0。Health 和 BotHealth 可沿用已闭合的 base Health 字段读取布局。RTTI 名称没有把实际 actor 标注为玩家或敌人；直接把所有 Health 算玩家、只把 BotHealth 算敌人会漏掉待核实对象。

本轮 log 已观测许多 Health、少量 DoorAnimated/DoorSlide，尚未观测 BotHealth；这属于 incomplete rolling window 的采样分布，不能证明游戏没有 BotHealth，或某个 Health 必然是敌人。成功的 raw key probe 为 15 Health + 1 DoorAnimated。

## 下一版合理的采样改进

当前 table count 为 92160，滚动每窗口最多128，所以理想条件也需720窗口才遍历一圈；采样间隔100ms时至少约72秒。真实记录还会遇到 map/budget/record cap。因此该发现扫描可以找实例，却难以捕捉短时间伤害或门变化。

下一版可保留 discovery 的 rolling window，并另设最多16或32个已发现实例的持续采样 cache，每 tick 重新检查 table/owner/generation/component handle/vtable/map binding 后读 raw 字段；身份变化立即移除，metadata声明coverage不完整和缓存上限。Health 与 BotHealth 都保留；按可见战斗动作、已有任务时间、同owner的已审计 AI/Player component 类型关联确定角色，而不按类名猜测。

同样可给已审计数组候选键加一次 raw 记录，为主客机同场景/重载比较收集证据。这些只读改进须在下一次构建/重载模块时实施；本轮没有改已加载 DLL 源码，也没有启用世界控制或复制。
