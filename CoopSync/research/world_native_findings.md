# 门、敌人原生接口静态复核与只读采样

这份成果接通了 Door/Health 的真实对象观测路径：从已审计的 ECS 表枚举、严格校验类与 owner，读取少量有代码证据的原始字段。门命令与 native 状态注册链已找到。当前没有执行开门、改血、生成敌人或网络复制；这份报告也不能证明当前机房门故障的原因。

## 固定构建与复现

- 游戏：`D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered\Spider-Man.exe`
- SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`
- 所有地址是该构建的 RVA，实际地址必须加已核验的模块基址。
- 本脚本 `world_native_probe.py` 只读 PE 文件，不打开游戏进程；导入同目录 `cinematic_static_probe.py` 的 PE/objdump 帮助函数。
- 运行：`python research/world_native_probe.py`。可用 `--game` 和 `--objdump` 指定本地文件； hash 不符即拒绝。
- 解码 27 个固定范围，总 10569 字节，每段最多 `0x4000`。指令、文件位置和 RTTI 闭合结果保存在同名 JSON。

## 对象类型：两种 descriptor 不可混用

| 类 | vtable RVA | MSVC RTTI TypeDescriptor | ECS engine descriptor/map key | virtual +0x48 getter |
|---|---|---|---|---|
| Door | `0x4f67720` | `0x6c41c78` | `0x7c32140` | `0x1f30770` |
| DoorAnimated | `0x4f677c8` | `0x6c41c98` | `0x7c32250` | `0x1f332c0` |
| DoorSlide | `0x4f67bb8` | `0x6c41d70` | `0x7c32650` | `0x1f35c60` |
| Health | `0x3839e08` | `0x6baa978` | `0x7c2c290` | `0x1f155c0` |
| BotHealth | `0x3839e98` | `0x6baa9f8` | `0x6c87910` | `0x3ce4e0` |

脚本逐一核验 RTTI 类名 → COL → vtable 前置指针；再核验 virtual `+0x48` 的 `lea/ret` 确实返回对应 ECS engine descriptor。constructor 和派生初始化的指令证据也保留在 JSON。类型证据只能确定类关联，不能确定实时对象仍然存活或它就是玩家眼前某扇门、某个敌人。

## owner 与本地实例身份

`0x1676150` 将 component `+0x8` 绑定到实体表 entry，将输入 handle DWORD 放入 `+0x14`。`0x1676070` 从 owner 的 `+0xC/+0x10` 重组实体 handle；`0x15A0560` 拆成 20 位 index 和 11 位 generation，从全局 `0x7A44380`、count `0x7A4439C` 及 stride `0xC0` 解析并检查 generation。

这些是当前进程内的 lifetime handle。另一台电脑、重载后的同一实体可能不同；它们没有被当成 network ID。跨主客机的稳定 actor/asset key 仍缺证据。

compact component map 位于 entity `+0x68`，WORD count 位于 `+0x70`； hashed map 位于 `+0x80`，WORD capacity 位于 `+0x88`。每个 entry 是 16 字节的 descriptor/component 指针对。`0x167AB40` 是 compact lookup，`0x16799A0` 是 hash lookup，`0x1679A10` 用 compact map 构造 hash map，`0x1676720` teardown 也枚举 compact map。hash 中可有继承别名，所以采样器只枚举 compact map 并要求 exact key 和 exact vtable；缺失/未知都记 coverage gap。

## 门：已找到的命令与状态注册

DoorScriptAction `0x1F355B0` 的命令 enum descriptor 是 `0x50AE260`，具有下列六个名称/hash；分支调用在代码中可核对。

| 命令名称 | hash | dispatcher 分支 | native callee |
|---|---|---|---|
| Open | `0x94e04314` | `0x1f356a8` | `0x1f32710` |
| Close | `0xa524d05` | `0x1f35696` | `0x1f31360` |
| Lock | `0xb71f5bbe` | `0x1f356de` | `0x1f326b0` |
| Unlock | `0x549cfe88` | `0x1f3568a` | `0x1f32aa0` |
| SnapOpen | `0x79090c64` | `0x1f35676` | `0x1f32710` |
| SnapClosed | `0xf3e3cb9d` | `0x1f356ca` | `0x1f31360` |

Open/Close 路径进入 component `+0x18` 的 native 状态请求对象，再调用 `0x1984370 → 0x19858E0 → 0x1985F20 → 0x1985D50`。请求有 16 字节 payload，其中前 8 字节来自 opaque R9 key，第 8/9 字节来自 DL/R8B，其他表示和调用上下文尚未闭合。此静态链证明游戏存在原生命令入口，尚不足以安全执行调用。

Door `0x1F31A90` 用共同 registrar `0x1984190` 注册 `+0x48[12]`、`+0xBC[1]`、`+0xC1[1]`、`+0xBF[1]`、`+0x58[8]`； callback 注册指向 `0x1F32790/0x1F32820`。采样器读取前四项和有 saved-state 路径证据的 `+0xC2[1]`、`+0xC3[1]`、`+0xC4[4]`；`+0x58` 的表示未闭合，故不读取。

`SaveOpenedState`/ActorSaveComponent 的描述以及 `0x1F30C50` 的恢复路径表明存在门状态存档机制。`+0xC1` callback 涉及 entity enabled 流程，但尚不能等同于物理碰撞就绪。原始字节不会被解释成“已打开”“客机可穿过”。旧 DoorStep 只是玩家位置移动；其中使用指针的 scene hash 也不能用于跨进程身份。

## Health：原生状态登记与数值路径

Health `0x1F168F0` 登记 `+0x80[4]`、`+0x84[4]`、`+0x88[4]`、`+0xAC[2]`； `0x32E940` 读取 `+0x88` float。`0x1F16FC0` 的静态代码将输入限制到 `[0,+0x80]`、保存旧 `+0x88` 至 `+0x8C`、写新值并调用 `0x1676B90` 标记状态变化。callbacks `0x1F16CE0/0x1F16DA0` 根据数值和 flags 有条件触发事件。

采样器只输出 `+0x80[16]` 与 `+0xAC[2]` 的 raw hex。上述代码支持 cap/value/previous-value 的候选解释，但尚未把真实实例对应到可见敌人，也未核验伤害、死亡、AI、奖励及 spawn 生命周期。不能仅复制一个 float 就宣称敌人同步完成。

## GameNet 结论的边界

先前 `序章修复调查/电梯门初始化_GameNet只读复核_20261007.md/json` 已复核 GameNet manager、GameStateSystem 与 registry。这里补核 registry `0x1F02AB0` 队列以及 `0x1F02C90/0x1F02D40` 请求/完成，确有本地实体 handle 解析及 `0x1986230` deserialize 调用。Door 与 Health 自身有 native 状态登记，使它们成为合理的进一步调查目标；但当前场景初始快照、network transport、host authority 和碰撞覆盖仍没有闭合。不能据此说启用 GameNet 即解决门或怪不一致。

## 已实现的只读模块与验证

接口：`coopsync::runtime::CaptureWorldRaw(base, image_size, sequence)`，源码 `src/runtime/runtime_world.h/.cpp`。调用者须先通过固定构建 hash gate。它只使用 `ReadProcessMemory(GetCurrentProcess())`：每次滚动最多 128 entity，map 最多 128 slot，最多 16384 read / 1MiB，并保留最终 global table 校验预算；最多接受 32 component，输出控制在世界采样 48KiB 配额内。

每份接受记录要求两次 raw 字段相同、component vtable/owner/handle 相同、map key/value 相同、entity index/generation/map header 相同，以及最终 global table pointer/count 相同。失败、预算耗尽、map 超限都显式记录 gap。前后相等不能排除所有 interleaving/ABA，因此它只是局部原始观察，没有 coherent 全世界 snapshot 保证。

输出始终声明 coverage 不完整、local handle 不是 network ID，并将 door-open/collision-ready/enemy-health-or-death/world-replication verified 设为 false。没有 hook、game calls、game writes。纯 mock 测试 `research/runtime_world_mock_tests.cpp` 直接编译生产实现，已通过 37 项确定性检查，覆盖读取中变化、短读拒绝、预算、游标及 33 Door 下记录/输出配额。MSVC `/std:c++17 /W4 /WX` 编译通过；测试没有使用游戏进程。

下一步需要真实 Door/Health 接受记录与可见开门/战斗动作的对应证据，再闭合跨主客机 actor key、门视觉/碰撞状态以及敌人 spawn/AI/伤害/死亡 authority；最后核实 game-thread、对象生命周期和调用 ABI，才能启用控制。
