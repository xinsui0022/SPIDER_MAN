# 当前完成与未完成

| 工作 | 状态及证据 |
| --- | --- |
| 自主主机协调状态机 | 16项核心测试通过 |
| 有界二进制协议/真实Windows TCP | 186项检查通过 |
| 本机两个进程通信 | 5种实际TCP场景通过；10种异常会话场景通过 |
| 抽象游戏适配证据桥 | 14项假后端检查通过；真实控制后端未实现 |
| 原生只读DLL生命周期 | 41项假后端检查、生产DLL错误宿主拒绝检查通过 |
| 原生世界只读观察 | 37项模拟内存检查通过；真实Door/Health实例观察已取得 |
| 加载控制工具 | 38项合成ABI/旧DLL身份检查通过 |
| 原生日志分析 | 16个测试方法通过，严格区分incomplete/原始证据/能力false |
| 真实原版DLL加载启停 | PID17652，两次350/4432样本，Stop成功；原构建有留档 |
| 第三次剧情/受火伤实录 | PID10516，5844样本，无ended；分析为incomplete，不能写Stop成功 |
| 过场命令/资源/跳过候选研究 | 静态路径与参数前置研究完成；实际控制未验证 |
| 实体身份候选数组 | 22项mock与16对象真实只读观察；跨电脑稳定身份未验证 |
| 主机门、碰撞、机关复制 | 未实现/未验收 |
| 敌人生成、两人攻击、主机结算、死亡 | 未实现/未验收 |
| 客机召集与真实场景就绪 | 未接入 |
| 双端实际过场及任一方跳过 | 未接入 |
| 普通1级新游戏、合作奖励和存档继续 | 未验收，原机主要是50级NG+ |
| 第二台电脑真实游戏联机测试 | 没有本次自主模块的验收证据 |

近期目录：

- `CoopSync/logs/native_runtime_20261011_menu_verified/`
- `CoopSync/logs/native_runtime_20261011_level/`
- `CoopSync/logs/native_runtime_20261011_cinematic_combat_10516/`
- `CoopSync/logs/door_native_current_20261010_0901_audit/`
- `CoopSync/research/world_entity_identity_handoff.md`
- `CoopSync/research/cinematic_control_feasibility.md`

跨电脑改造的构建与检查结果另见 `BUILD_VERIFICATION.md`。原始日志里的能力声明始终为false；改变配置不会自动升级为已验证后端。
