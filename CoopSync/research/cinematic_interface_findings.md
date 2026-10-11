# 过场接口：只读定位与已保存基线

本报告由 `cinematic_static_probe.py` 从固定游戏构建生成，并汇总已保存的只读探针日志。生成器没有启动游戏、访问进程或修改游戏。

游戏 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。PE ImageBase：`0x140000000`。

## 字符串映射

| 名称 | 文件偏移 | RVA | 节 |
|---|---|---|---|
| SkipCinematic | `0x3a744b0` | `0x3a74eb0` | .rdata |
| SkipMovieNode | `0x3ce7e08` | `0x3ce8808` | .rdata |
| EndCinematic | `0x4ef3348` | `0x4ef3d48` | .rdata |
| SetToEnd | `0x4ef3368` | `0x4ef3d68` | .rdata |
| SetToEndAndHide | `0x4ef3378` | `0x4ef3d78` | .rdata |
| LastFrame | `0x4ef3b20` | `0x4ef4520` | .rdata |
| Skipped | `0x3b9c3e9` | `0x3b9cde9` | .rdata |
| Skipped | `0x3c316eb` | `0x3c320eb` | .rdata |
| Skipped | `0x3ca1dc2` | `0x3ca27c2` | .rdata |
| Skipped | `0x3ccaa90` | `0x3ccb490` | .rdata |
| Skipped | `0x4eba7dd` | `0x4ebb1dd` | .rdata |
| Skipped | `0x4ef3b30` | `0x4ef4530` | .rdata |
| Cinematic2Component | `0x3cf3750` | `0x3cf4150` | .rdata |
| Cinematic2Component | `0x4ef3436` | `0x4ef3e36` | .rdata |
| Cinematic2Manager | `0x3cf3eb8` | `0x3cf48b8` | .rdata |
| Cinematic2System | `0x3cf42d8` | `0x3cf4cd8` | .rdata |

## RTTI 与虚函数表

RTTI 证明类型关联，不能证明虚函数槽的语义。下列地址均为候选研究地址，不可直接调用。

- `.?AVCinematic2Component@@`：descriptor `0x6c23a20`，COL `0x56a6c30`，对象偏移 `0x0`，vtable `0x3cf4100`，连续代码指针 10 个。
- `.?AVCinematic2Manager@@`：descriptor `0x6c23b38`，COL `0x56a6f28`，对象偏移 `0x0`，vtable `0x3cf47b0`，连续代码指针 32 个。
- `.?AVCinematic2System@@`：descriptor `0x6c23c88`，COL `0x56a72b0`，对象偏移 `0x0`，vtable `0x3cf4c68`，连续代码指针 14 个。
- `.?AVCinematic2Action@@`：descriptor `0x6c23b90`，COL `0x56a7030`，对象偏移 `0x0`，vtable `0x3cf4908`，连续代码指针 12 个。
- `.?AVCinematic2ActionPrius@@`：descriptor `0x6c23be8`，COL `0x56a7148`，对象偏移 `0x0`，vtable `0x3cf4a80`，连续代码指针 13 个。
- `.?AVCinematic2ListenerAction@@`：descriptor `0x6c23b60`，COL `0x56a6fa8`，对象偏移 `0x0`，vtable `0x3cf4a00`，连续代码指针 11 个。
- `.?AVCinematic2ListenerActionPrius@@`：descriptor `0x6c23c50`，COL `0x56a7238`，对象偏移 `0x0`，vtable `0x3cf4bc0`，连续代码指针 13 个。

## 引用与函数边界

| 引用指令 RVA | 目标 | .pdata 函数起点 | 状态 |
|---|---|---|---|
| `0x183b7d` | Cinematic2Component | `0x183b73` | instruction boundary confirmed by objdump from .pdata function start |
| `0x183e15` | .?AVCinematic2Manager@@:vtable | `0x183dc0` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1661ff8` | .?AVCinematic2Component@@:vtable | `0x1661fd0` | instruction boundary confirmed by objdump from .pdata function start |
| `0x166fc7c` | Cinematic2Manager | `0x166fc60` | instruction boundary confirmed by objdump from .pdata function start |
| `0x166fed3` | .?AVCinematic2ActionPrius@@:vtable | `0x166feb0` | instruction boundary confirmed by objdump from .pdata function start |
| `0x166ff90` | .?AVCinematic2ActionPrius@@:vtable | `0x166ff80` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670493` | .?AVCinematic2ListenerActionPrius@@:vtable | `0x1670470` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670550` | .?AVCinematic2ListenerActionPrius@@:vtable | `0x1670540` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670a50` | .?AVCinematic2ActionPrius@@:vtable | `unknown` | raw RIP-relative candidate |
| `0x1670a70` | .?AVCinematic2ListenerActionPrius@@:vtable | `unknown` | raw RIP-relative candidate |
| `0x1670a86` | .?AVCinematic2ActionPrius@@:vtable | `0x1670a80` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670ae6` | .?AVCinematic2ListenerActionPrius@@:vtable | `0x1670ae0` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670b33` | .?AVCinematic2Action@@:vtable | `0x1670b10` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1670c23` | .?AVCinematic2ListenerAction@@:vtable | `0x1670c00` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1671164` | Cinematic2System | `0x1671070` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1671a7f` | Cinematic2System | `0x1671840` | instruction boundary confirmed by objdump from .pdata function start |
| `0x1b3232a` | .?AVCinematic2ActionPrius@@:vtable | `unknown` | raw RIP-relative candidate |
| `0x1b32360` | .?AVCinematic2ListenerActionPrius@@:vtable | `unknown` | raw RIP-relative candidate |

## 已闭合的静态命令分发链

`Cinematic2Action` RTTI vtable `0x3CF4908` 槽 `+0x50` → `0x166FFF0` → 读取命令描述符指针 `0x6253080`（内容指向 `0x4EF40B0`）→ 枚举解码 → 调用 `0x166A320` → 17 项 switch 表 `0x166A6E0`。
`Cinematic2ActionPrius` 元数据描述符 `0x6253EF0` 的构造回调 `0x1B32320` 安装 RTTI vtable `0x3CF4A80`；数据回调 `0x1B32340` 跳转到对象虚函数槽 `+0x50`。这些是元数据/类型关联，不代表已核验游戏内调用。

| 命令 | 枚举索引 | 分支 RVA | 游戏内描述 |
|---|---|---|---|
| Triggered | 2 | `0x166a410` | NONE |
| EndCinematic | 6 | `0x166a45f` | Immediately end the cinematic |
| SetToEnd | 8 | `0x166a475` | Set the cinematic to end state -- leaves possessed actors active |
| SetToEndAndHide | 9 | `0x166a48b` | Set the cinematic to end state -- deactivates possessed actors |

**不能把 EndCinematic 当作用户跳过接口。** 索引 6 的分支写入状态值 13，将 `TimedOut` 哈希 `0x3DCA3882` 传入有条件转发函数 `0x166B890`，公共收尾又传入 `AlmostDone` 哈希 `0xDA8C6E3A`；实际事件送达未验证，索引 8/9 的终态分支也不同。

## 用户手动 Skip 的定位状态

`SkipCinematic` 是 123 项 UI 选项枚举中的索引 7，哈希 `0xC96C7F67`。描述符 `0x3A73810` 由全局指针 `0x5EBCC08` 引用；代码使用处 `0x72E443`、`0x730D70`、`0x1147680` 是配置序列化/枚举转换，尚未连到手动跳过回调。
`SkipMovieNode` 当前只有元数据名称线索。`Skipped` 输出事件哈希为 `0x5D74A037`；唯一代码立即数引用位于 `0x2500818`，其上下文是事件编译，不能当作跳过接口。
另一路 `UI_SKIP_MOVIE` → `OverlayUI` 更新与 hold callback 的证据由 [ui_skip_findings.md](ui_skip_findings.md) 单独维护；callback 赋值来源/执行目标仍未闭合，不能声明原生 skip ABI 已可调用。

## 已确认的全局对象候选

| 类型 | 直接对象 RVA | 预期 vtable RVA | 静态证据 |
|---|---|---|---|
| Cinematic2Manager | `0x6044830` | `0x3cf47b0` | 0x183e15 LEA vtable; 0x183e1c MOV [ImageBase+0x6044830],RAX. |
| Cinematic2System | `0x6044a60` | `0x3cf4c68` | On-disk qword at 0x6044a60 points to RTTI-validated vtable; 0x2bc35a/361 registers this object address. |

它们是直接静态对象。配套 `cinematic_runtime_probe.py` 在已运行的固定构建中核验 SHA/path/module，只读核验两个对象 vtable，再读 System `+0x11D0` 的组件选择槽。组件非空且 vtable 为 `0x3CF4100` 时才读取以下原始字段；样本前后复核对象、指针与组件 vtable，失稳则丢弃字段。单样本最多 15 次/87 字节，只请求读取/查询权限。

## 组件选择槽与原始状态

`0x16731C6` 和另一更新路径 `0x16730F5` 都先清空 System `+0x11D0`；`0x1673268` 在类型检查通过、组件 `+0xC7 != 0` 时选入指针。组件 RTTI vtable `+0x48` → `0x165F170` 返回描述符 `0x7462DD0`，与更新中的类型检查目标一致。清零/非零变化只证明组件选择变化，不能视为开始/结束。

| 字段偏移 | 字节数 | 静态证据 | 语义边界 |
|---|---|---|---|
| `0x58` | 4 | dispatch reads/writes +0x58; update 0x1669228 reads it before switch | full enum meaning unverified |
| `0x5c` | 4 | SetToEnd 0x166a49d requests value 12 here | raw requested-state candidate, full meaning unverified |
| `0xc0` | 4 | SetToEnd/SetToEndAndHide 0x166a477/48b write 0/1 here | raw command-associated value only |
| `0xc7` | 1 | selection test 0x167325f | nonzero selects component; not independently proven playing flag |
| `0xc9` | 1 | Hide/Show 0x166a4f4/5a8 write 1/0; update 0x16688c0 exits when nonzero | raw Hide/Show-associated byte, full meaning unverified |
| `0xca` | 1 | action handler 0x167008c writes here | raw field only |

`0x1669228` 读取 `+0x58`，八项表 `0x16695A0` 以原始值 6 为基准。值 10 → `0x1669496` → `0x16699B0`，随后调用 `0x166DD60` 并读取浮点式 `+0xF0`；尚无独立枚举名称映射，因此不把 10 命名为 Playing。

## 身份候选与结束转发边界

`0x166B750` 以组件 `+0xA8` 的 64 位值与 `[组件+0xB0 指针+8]` 比较，分别核对高/低 32 位；只有全等才返回 `+0xB0` 指针。`0x1668AF9..0x1668B51` 重复此核验后读取 `[指针+0x10]`。这证明内部引用一致性检查，仍不能证明该值是可跨端/重载稳定的 cinematic_id、asset_id 或 generation；当前 runtime probe 未加入这组字段。
`0x166B890` 先调用组件虚表 `+0x30`（`0x1675FC0` 加载 owner `+8` 后跳 `0x159E040`），再解析组件 `+0xB8` 和描述符查找结果，均通过才转入 `0x1670F30` → `0x1672EE0` → `0x1670EB0` → `0x1923A90`。沿途有非空和虚函数结果门控，传入事件哈希不等于事件已送达，也不证明任务/门/碰撞/检查点收尾完成。

## 已保存只读运行日志

下列记录没有用户自然播放/手动跳过对照，也没有画面观察或场景就绪/世界收尾核验。

| 日志 | PID | 样本数 | 状态计数 | 槽值计数 |
|---|---|---|---|---|
| [logs/cinematic_identity_runtime_20261010.json](../logs/cinematic_identity_runtime_20261010.json) | 25612 | 1 | {"object_identities_match_state_and_calls_unverified": 1} | {"not_sampled": 1} |
| [logs/cinematic_readonly_baseline_20261010_current.jsonl](../logs/cinematic_readonly_baseline_20261010_current.jsonl) | 25612 | 3 | {"object_identities_match_no_flagged_component": 3} | {"0x0": 3} |
| [logs/runtime_baseline_20261010_recovered/cinematic.jsonl](../logs/runtime_baseline_20261010_recovered/cinematic.jsonl) | 25612 | 31 | {"object_identities_match_no_flagged_component": 24, "component_changed_during_reads": 1, "component_identity_match_raw_state_only": 6} | {"0x0": 24, "0x208807e7c30": 7} |

该日志稳定非空样本的原始字段：`{"0x58": [10], "0x5c": [10], "0xc0": [0], "0xc7": [1], "0xc9": [0], "0xca": [0]}`。


三秒基线出现同一组件 `0x208807e7c30` 与空槽交替，并有一次采样中指针变化；这与更新中先清零再选择的静态行为一致。它提供了保守处理选择变化的证据，不能单独确定正在播放或已结束。没有可调用接口被升级为 verified。

## runtime probe API 与复现

`probe(pid=None)` 保留单次 dict API；`with Session(pid) as session` 做一次 setup，`session.metadata` 返回会话记录，`session.snapshot(i)` 返回只读样本。CLI 默认每行一个 compact JSON，record_type 为 session/snapshot/end；snapshot 顶层保留 sample、monotonic_ms、status、component_slot、runtime_state_fields、verified_callable_interfaces（始终列表）。
`--output` 额外保存到独占创建的新文件，已有路径拒绝覆盖。`--self-check`/`--self-test` 同义，只执行内存 mock，不读游戏文件或进程。采样数量 1..3001，间隔至少 50ms，总计划时长不超过 300 秒，退出/失效会输出状态并停止；零/非零过渡仍不能证明组件整个生命期，瞬间 ABA 也无法由这些快照排除。

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\cinematic_runtime_probe.py --self-check
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\cinematic_runtime_probe.py --pid 25612 --samples 31 --interval-ms 100 --output .\logs\new_baseline.jsonl
```

## 真实适配状态

目前没有通过运行时核验的过场开始、跳过、结束、场景加载完成接口。
文件偏移、RVA、RTTI、vtable 匹配与原始字段不是可调用接口；未知参数、线程和生命周期不能凭名称推测。

## 下一步证据

1. 继续闭合 UI hold callback 的赋值来源与目标，核对参数和线程。
2. 对身份候选核对资源元数据类型和跨重载稳定性，再决定是否加入只读字段。
3. 后续受控自然播放/手动跳过对照需单独记录，不把现有静止/未知画面基线算作该验收。
4. 确认结束转发和任务、门/碰撞、检查点的实际收尾关系，再决定游戏适配器范围。

## 复现

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\cinematic_static_probe.py
```

环境依赖：上述 Python 已有 `pefile`；反汇编器为 `C:\TDM-GCC-64\bin\objdump.exe`。不需要 capstone 或联网安装。
JSON 包含有界反汇编、原始指令字节、.pdata 片段边界与引用证据。`.pdata` 可能拆分单个函数，线性解码也可能包含内嵌数据，不等同完整控制流恢复。脚本哈希不匹配时停止，不覆盖固定构建证据。
