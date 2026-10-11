# Cinematic2 控制可行性：跨电脑 / AI 交接

本轮确认了正规跳转/结束候选的完整入口 `0x166C7F0` 及其原生 UI 调用链，仍未验证可调用 ABI、线程、剧情实例身份或任务收尾。**可调用接口、真实剧情 phase、正常玩家 Skip 和世界收尾能力全部保持 false。** 用户已改任务为整理上传 GitHub，本轮不再测试游戏。

游戏固定 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。所有地址为 RVA，运行时需加重新核验的模块基址。脚本只读磁盘 EXE，不打开进程、不 hook、不注入、不调用游戏函数。JSON 保存元数据、指令字节、原生调用点和 unwind 片段关联。

## 当前交接状态

- 已完成：固定构建静态证据整理、资源布局消费路径、原生跳尾候选及 UI 数字命令调用链。
- 未完成：`cinematic_resource_runtime_probe.py` 没有创建，也没有 mock 自检；中断前只是计划，不能算成果。
- 未完成：DDL `Skippable` 到资源 packed flag 的转换绑定；跨资源类型、生命周期、线程、任务门/敌人/检查点收尾的实录。
- 本轮不修改已加载 DLL、不启动新测试。原有只读诊断与历史日志保持原来的语义边界。

## A8/B0 的真实读取布局

| 位置 | 宽度 | 已核验的静态含义 |
|---|---:|---|
| Component `+A8` | 8 B | checked resource-reference token |
| Component `+B0` | 8 B | 指向外部资源对象的指针，非内嵌资源对象 |
| Resource `+8` | 8 B | 与 A8 高/低 32 位逐一核对的 token |
| Resource `+10` | 8 B | 校验后取出的 data 指针；尚未闭合到 Cinematic2Def 类型 |
| Resource `+30` | 4 B | packed flags；bit 3 门控 `166C7F0` |
| Resource `+3C` | 4 B | `movss` 消费的时长 / end-time 候选 |

准确指令：`166C7F6 MOV R8,QWORD [RCX+B0]`；`166C809 MOV RDX,QWORD [RCX+A8]`；`166C81A MOV RAX,QWORD [R8+8]`。高/低 32 位不全等直接退出。通过后 `166C85A MOV EAX,DWORD [R8+30]` → `166C85E SHR EAX,3` → TEST AL,1。`1668B4D` 另一路读取 `QWORD [R9+10]`；`16716E5` 读取 `float [RDX+3C]`。

这套布局允许将来设计有界只读资源快照。届时需要前后复查 System/vtable/selection、component vtable/owner/handle、A8/B0 和 resource+8；失稳丢弃。不执行 getter 或 callback。当前**没有**这样的新增运行时采样器。

## 可跳过属性与运行时门控分开

`Cinematic2Def` descriptor `6AA04B0` 有 47 字段：names `51174A0`、offsets `5117D80`、hashes `5117380`、descriptions `5118370`。

- index 9 `Skippable`，定义对象 `+168`，hash `F0DC1233`，游戏自带说明 “Allows cinematic to be skipped in game.”
- index 10 `ResetOnFinished`，定义对象 `+169`，hash `4AA36328`，说明结束后可重新初始化到 ready。
- DDL 字段复制函数 `261AFB0` 的 `261B173 MOVZX BYTE [RSI+168]` / `261B17E MOV BYTE [RCX+168]` 证明确为 1 字节属性；ResetOnFinished 的相邻 byte 复制见 JSON 指令。
- `Cinematic2GlobalEventTrackDef` descriptor `6A9F5B0` 有 `IgnoreOnSkip +C8`（hash `AE4CF01E`），说明跳过时可忽略该轨道动作。因此不同跳跃标志可能改变任务事件执行，不能任意 seek。

**尚未证明 Skippable 的 +168 转换成 Resource+30 bit3。** 这两个证据彼此相关但还没有编译/装载转换闭环。Resource+10 的 data 指针也不能直接按 Cinematic2Def 解读，尤其不能对资源 `+168` 读 bool。

## 166C7F0 正规控制候选

完整入口 `166C7F0`，RET `166C97D`；`166C8E0` 是链式 unwind 片段，绝不能当函数入口。静态观察 RCX 为 component 候选。执行前必须有 B0、A8/B0 token 一致、Resource+30 bit3 为 1。

候选从 `60449B8` 取原生回调，传入 component RCX，取得 float 目的地；回调存在且目的地不晚于当前 F0 时退出。磁盘默认回调是 leaf `1671690`，校验 token 后返回 Resource+3C float，失败返回零。**运行中 callback 可被替换，当前值未验证。**

目的地被 clamp 到 `[0, length]`：

- 中间目的地：以 packed float / flags `0x10` 调 `1666FB0`，再有条件转发 AlmostDone。Seek 本身会解析 shot/clip、改变 actor 状态并处理轨道事件，绝不等于写一个时间值。
- 到尾部：设置 Component+4C bit21，找 actor 并调 `164F9C0`，然后 `166C4A0` 请求 / 切换 raw state 12，走原生更新。
- raw 12 更新 `16694DC` 从资源 `+3C` 取 float，按组件 flags 构造 seek 参数，调 `1666FB0`；然后写 raw13 并发 TimedOut。raw13 更新进入 `16695C0`，有 actor/typed event、原生清理和有条件 LastFrame 转发。

这比直接调用 `166A320(EndCinematic)` 或修改 F0 更接近游戏自己的路径，但仍不是已验证 mod 接口。完整函数入口不意味着拥有正确线程、this 生命周期、资源/场景前置或无重入保证。不能从只读 sampler 线程执行它。

## 原生调用者

`7DC400` 的 `7DC4E4` 从输入对象 `[R8+20]` 传数字命令给 `7DE150`，先验证 `[R8+18]&8F == 4`。`7DE150` 的内嵌映射表 `7DE3C8` / `7DE39C` 把数字 7 映射到 `7DE2C9`：枚举 Cinematic2 类型组件，经 `1661A90` predicate，且 raw58 为 10 或 11，再在 `7DE341` 调完整 `166C7F0`。predicate 的完整业务语义和 UI 输入实际送达尚未实录。

另一个入口 `7DE8C0` 有同样的组件枚举 / predicate / raw58 门控，在 `7DE93D` 调 `166C7F0`。本轮覆盖的全 EXE E8/E9 直接引用、绝对函数指针、部分 REX MOV/LEA RIP 取址未找到 `7DE8C0` 的引用，不能据此声明不可达。

`623020` 用 `Cinematic2SkipDestinationEvent` hash `3E955A02` 找事件时间，失败退回 checked Resource+3C；也是静态候选，本轮未找到原生调用者。该 typed event 是轨道目的地数据，不能作为“用户请求跳过”事件。

反例：RTTI `CineQTEEndAction` vtable `387A9C0` 槽50→`627760`；`6277DE` 对解析出的 component 传命令6 EndCinematic。此 QTE 脚本调用只证明原生显式结束用途，不能把命令6等同正常玩家 Skip。

## 菜单反例必须保留

父任务的离线日志分析：主菜单完整350 samples，其中36 samples匹配同一 component / 资源候选 `9a05b474457c6ab3`，EC/F0变化35次，raw float约9.828..10.877。这里是父任务保存的观察摘要，本脚本没有采样游戏。

因此关卡70个匹配样本、同资源和计时变化**不能证明捕获了救平民剧情**。`6045C30` 是 System+11D0 枚举选择槽：每次清空，随后每个 C7!=0 的 Cinematic2 component 都覆写，最后一个满足条件的组件留在槽里。`165FEF0` 构造 RTTI `Cinematic2CameraPaneEvent`（vtable `4ED4DB0`），EventType 0，置 C7=1；`166AAE0` 发相同类型 EventType 1，清 C7。System `1672430` 给所有组件更新，不是单独的剧情导演。

这支持“标记的 camera-pane component 候选”，仍无法区分菜单背景、环境镜头和任务过场；phase 保持 false。真实剧情绑定要把资源和 owner/action/scene/mission 身份连起来，不能只用选择槽、raw10或时间变化。

## 后续实际路径与缺证据

1. 保存 raw 诊断与菜单对照，先闭合一个真实任务过场实例身份及调用 epoch。
2. 补上 DDL Skippable→Resource flags 转换、装载类型和 callback slot 的运行值，保留所有失败门控。
3. 在以后授权的测试阶段，被动记录完整 `7DE150` / `166C7F0` 原生调用的线程、caller、component identity 和事件顺序；不先执行未知 ABI。
4. 用原生 Skip 与自然结束分别验证任务、门/碰撞、敌人、检查点收尾，再设计游戏线程命令队列和主机权威联机 adapter。

## 跨电脑路径清单

| 文件 | 迁移注意 |
|---|---|
| `cinematic_static_probe.py:21/23` | GAME 默认 D:/STEAM__/...；OBJDUMP 默认 C:/TDM-GCC-64/bin/objdump.exe。CLI 可 `--game` / `--objdump` 覆盖 |
| `cinematic_native_next_probe.py` / 本 probe | 导入以上默认，均支持覆盖参数 |
| `cinematic_runtime_probe.py:22` | GAME 绝对路径硬编码；CLI没有 `--game`。跨电脑需由接手者参数化后再使用 |
| `ui_skip_probe.py` | 导入静态默认，CLI没有 game/objdump覆盖参数 |
| `ui_skip_runtime_probe.py` | 继承 cinematic_runtime_probe 的 GAME 与 Windows 进程环境 |
| 上述生成器及 `cinematic_recording_analysis.py` | 历史 Markdown命令含 C:/Users/xinsui/...Python311；使用接手电脑的 python/py命令 |
| 历史日志 | PID、absolute pointer、module base、路径是历史证据，不可复制当有效调用参数 |

依赖为 Python、`pefile` 与 GNU objdump（Intel syntax）。读取不同 EXE hash 时停止；不能把这批 RVA 用于其他版本。

## 有界复现

在项目根目录运行（按接手电脑实际路径替换参数）：

```powershell
python -X utf8 -B .\research\cinematic_control_feasibility_probe.py --game 'D:\YourSteamLibrary\steamapps\common\Marvel''s Spider-Man Remastered\Spider-Man.exe' --objdump 'C:\YourTools\bin\objdump.exe'
```

本次整理限定 19 个反汇编范围，共 8854 字节；每段最多 2449 字节。22 条 pinned 指令断言、描述符成员断言和 UI table/callback 默认值断言通过，仅证明静态包复现，不是运行时功能验收。新的资源 runtime probe 和 mock tests 没有实现。
