# Cinematic2 原生事件与资源身份：下一阶段静态证据

这轮闭合了资产字段绑定、原生命令入口和 Completed 时间阈值通知；仍没有可直接使用的真实播放开始/最终结束检测器，也没有可调用的跳过接口。

固定 EXE SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。所有地址均为 RVA。脚本只读磁盘 EXE，不访问进程，不 hook，不注入，不调用游戏函数。

## 资产 ID 与实例 ID 分开

`Cinematic2ComponentPrius` RTTI vtable `0x4EC60C0` 的 +0x38 叶函数 `0x1AC16B0` 返回 descriptor `0x62392A0`。该描述符的名称表 `0x4EC5CF0`、offset 表 `0x4EC5E20` 列出以下成员；游戏初始化指令独立验证了其中的资产字段绑定。

| Prius 字段 | 偏移 | 游戏自带说明 |
|---|---|---|
| CinematicAsset | `0x8` | Cinematic asset to be loaded |
| CinematicAssetId | `0x20` | NONE |
| PlayBackShot | `0x28` | ask runtime to only play selected shot |
| Autoload | `0x38` | Automatically load the cinematic on activate |
| ScriptDriven | `0x39` | Triggered by script so dont play on load |
| CodeDriven | `0x3a` | Triggered by code so don't create the manager automatically |
| IsWorldSpaceCinematic | `0x3b` | cine is world space |
| EditorSpawned | `0x3c` | flag to indicate this is editor spawned cine |
| ViewerSpawned | `0x3d` | flag to indicate this is viewer spawned cine |

组件初始化完整入口 `0x165F2F0`：`0x165F5D4` 读取 Prius `+0x20`，`0x165F5D8` 写入 Component `+0xA0`。如果该值高 32 位被测试为非负，则用 Prius `+0x8` 经 `0x1BB25D0` 解析，`0x165F5F8` 覆写 `+0xA0`。

命令 Triggered 的目标 `0x1668150` 读取 Component `+0xA0`，经 Manager `0x166FE30` 返回引用；组件 `+0xA8/+0xB0` 取的是返回引用的 token/指针组合。因此 A0 是 `CinematicAssetId` 的静态候选，A8 是引用一致性 token，不能混为一个跨端实例 ID。A0 是否跨重载、跨进程稳定仍需实录；相同资产可能重复播放，还需要独立的调用 epoch/实例代数。

## 开始路径还未闭合

`Cinematic2Action` vtable `0x3CF4908` 槽 `+0x50` → 完整入口 `0x166FFF0`：从 Action `+0x58` 以 hash `0xDB2783F1` 解析目标 actor，类型描述符 `0x7462DD0` 找到 Cinematic2Component，然后把命令 hash 解码为枚举并进入 `0x166A320`。

`Triggered` 枚举 2 → 分支 `0x166A410` → `0x1668150`，只是请求原始状态 10（某些标志请求 14）。状态 10 的转换分支 `0x166C3ED`/`0x1669C52` 发送的是 **OnReady**，所以不能凭 raw 10 将组件命名为 Playing。

`OnTriggered` hash `0x318B1410` 在辅助函数 `0x1666E10`；实际命令索引 4 `InterruptLoop` 调用这个辅助函数，不是 Triggered 的真实开始回调。`Started` hash `0x860D82C3` 在 Cinematic2 有界局部区间 `0x165F000..0x1671100` 无代码立即数，整 EXE 的 `0xC7BCC4` 属于另一个脚本节点。间接/表驱动发送仍可能存在，本轮没有闭合。

## Completed 通知早于最终收尾

完整 timeline 更新入口为 `0x166DD60`，RET 在 `0x166DFF8`；`.pdata` 把它拆成 6 个 unwind 片段，`0x166DF8A` 只是其中一片，不能作为完整函数入口。入口检查组件 `+0x408 & 1`。

`0x1666E90` 先核对组件 `+0xA8` 与 `[+0xB0 指针+8]` 的引用一致性，然后执行 float 比较 `输入 >= [资源+0x3C] - 0.5`（常量 RVA `0x382E128`）。timeline 更新在 `0x166DFBF` 检查旧 `+0xEC`、`0x166DFD3` 检查当前 `+0xF0`；只有旧值未到、当前值达到该阈值时，`0x166DFDC` 将 **Completed** hash `0x9A610B3E` 传入 `0x166B890`。

这闭合了游戏自身的阈值跨越通知，不能等同最终结束：它可能比资源阈值早 0.5 个时间单位（单位还需实录），没有在这个分支赋值 raw state 13，也不证明任务、门、碰撞、敌人或检查点收尾。`0x166B890` 还会检查 owner 虚函数、Action actor 引用和描述符；收到入口参数只是发送尝试，仍可能不转发。

raw state 13 的更新分支进入 `0x16695C0`，有 actor 处理、AlmostDone 和 LastFrame 路径。显式 EndCinematic 同样写 raw 13 并发 TimedOut，所以单独看到 13 也不能归因为自然结束或玩家跳过。

## 被动记录候选与边界

当前模块仍以只读快照为范围。未来若实现保留所有原始寄存器/栈/返回值的被动记录器，可优先验证下列完整入口；这些条目不授权直接执行游戏 ABI，也不表示已 hook。

| 完整入口 | 原生调用时可以记录的已见寄存器 | 不得推导 |
|---|---|---|
| `0x166a320` | Observed component argument register RCX, enum index EDX; component identity/asset candidate and native caller/thread | native command requested, not executed phase completion |
| `0x166b890` | Observed component register RCX, event hash EDX; log native callback path plus identity | attempted conditional forwarding, not delivery/cleanup proof |
| `0x1670f30` | Raw action object RCX, event hash EDX, native caller/thread | action forwards to script only when +58 exists; broader than cinematic component |

补充快照候选：A0、A8、EC、F0、408、438。组件 vtable/owner/引用需要前后核验；存量选择槽的零/非零仍只表示选择变化，不用于触发开始/结束。优先记录 command、native caller/thread、原始字段、任务变化和人工播放收据的同一时基，先建立实际顺序再决定 phase。

## 可复现与证据范围

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' -X utf8 -B .\research\cinematic_native_next_probe.py
```

反汇编限定 16 个范围，总计 7081 字节；函数 unwind 片段关联每入口最多检查后续 0x4000 字节。报告保存 hash、RTTI、字段表、事件表、必需指令核验和全部有界反汇编。没有网络下载或新依赖。

`verified_callable_interfaces=[]`；actual Started、原生跳过、资源/场景就绪、实例 generation、线程/生命周期、结束后世界一致性仍未验证。上一轮真实轨迹中 raw10 恒定、人工播放/结束收据附近选择槽为空，正是不能仅靠旧槽构造 phase 的运行证据；本报告不重标原始轨迹。
