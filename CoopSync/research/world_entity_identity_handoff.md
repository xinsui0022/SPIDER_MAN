# World identity 交接索引

当前成果是门/Health 的真实只读对象观测和实例键候选研究。**没有实现门、敌人的跨电脑复制，也没有开启 native 控制。negative 64-bit key 仍不是已验证的 peer ID。**

## 证据分层

| 层次 | 文件 | 已证实内容 | 尚未证实内容 |
|---|---|---|---|
| Static，固定 PE | `world_native_findings.md/json`、`world_native_probe.py` | 五类 RTTI/vtable/ECS descriptor、owner/local handle、Door 命令和 Door/Health native state 登记 | 当前 actor 角色、网络覆盖、可执行 ABI、碰撞就绪 |
| Static，固定 PE | `world_entity_identity_findings.md/json`、`world_entity_identity_probe.py` | 15-byte qword-array getter、三种 opaque key 路径、Health/BotHealth inheritance | 数组键生产者/capacity、存档/跨机稳定性、spawn 唯一性 |
| Real，单次只读 | `world_entity_identity_runtime_20261011_10516_level.json` | PID 10516 接受 1 DoorAnimated + 15 Health；199 reads/1143 bytes；字段/身份/全局 header 前后不变；15 key 高位为1 | 场景 actor 精确对应、玩家/敌人角色、peer ID、实际同步 |
| Real，安全拒绝 | `world_entity_identity_runtime_20261011_10516.json` | 场景切换后旧16对象 entity identity 不匹配，因此未接受key | 不能当作key观测成功；旧 status 名称只描述全局 header，accepted 数为0 |
| Real，权限失败 | `world_entity_identity_runtime_20261011.json` | 旧 PID 17652 hash/path 验证后 module 枚举 WinError5，未进入观测 | 没有内存结果 |
| Pure mock | `runtime_world_mock_tests.cpp` | exact C++ 实现：37项读途中变化、短读、窗口、预算、记录/输出配额检查 | 不证明游戏 runtime ABI 或语义 |
| Pure mock | `world_identity_probe_selfcheck.py` | exact Python reader：22项变化、短读、16对象及budget检查 | 不证明跨机身份 |

实际日志中 Health `+0x80[16]` 有变化，不能直接解释为某次火伤、某个敌人受伤或“伤害已同步”。跨72秒的滚动窗口尤其不能建立动作归因。

## 源码和复现

- DLL 内只读世界采样：`src/runtime/runtime_world.h/.cpp`，接口 `CaptureWorldRaw(base,image_size,sequence)`；调用者必须先核验固定构建。
- 独立候选键只读 probe：`research/world_identity_runtime_probe.py`，参数 `--pid`、`--source`、`--output`；最多16已接受实例，512 reads /4096 bytes。它复用 `cinematic_runtime_probe.py` 的 WindowsBackend/Session，不使用其 cinematic snapshot。
- Pure check：`python research/world_identity_probe_selfcheck.py`。
- Static report：`python research/world_native_probe.py` 与 `python research/world_entity_identity_probe.py`，可用 `--game` / `--objdump` 指定本地路径。
- static probe 依赖 `pefile` 与本机 GNU objdump；C++ mock 需要 x64 MSVC/C++17，使用 `/W4 /WX` 编译。
- 当前 runtime Python 的游戏路径来自 `cinematic_runtime_probe.GAME`，当前 build 脚本也含本机工具路径；跨电脑接手时使用项目统一路径配置或修改该本地配置，不复制别人的游戏安装目录。历史 PID、ASLR 地址和原始 pointer 都不可直接复用。
- 支持的游戏 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。build 不符必须停止 native 读取，不套旧 offset。

## 下一步待做

1. 在同一保存点重载、第二台电脑同场景加载时比较 raw negative key，证明同actor一致性与多实例唯一性；另查 dynamic spawn 的身份生产路径。
2. 追踪 `game+0x7A4A450` 数组的 allocation/capacity 与 key writer，闭合 asset/scene/lifetime 的具体来源。
3. 保留 Health 与 BotHealth 两类；利用 visible gameplay 对应和同owner的已审计 AI/player component 关联确定角色，不按类名猜测。
4. 下一版为少量已发现实例增加连续复核 cache，并保留有界 discovery；当前92160表项/128窗口至少720窗口，100ms间隔时约72秒一圈，容易错过短事件。身份/map binding 失效立即移除，预算与 coverage gap 必须保留。
5. 最后才核验 host authority、native ABI、game-thread 与生命周期，再接 Door 碰撞、敌人 spawn/AI/damage/death 和网络 apply。当前不存在可安全执行的已验证世界写接口。

截至交接，只做过说明中的两次 PID10516 有界读取。之后用户改为整理并上传项目，没有继续游戏测试，也没有改安装、存档或已加载 DLL。
