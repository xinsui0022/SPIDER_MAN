# AI 开发接手说明

先阅读 `交接资料/START_HERE.md`、`交接资料/AI_HANDOFF.md`、`交接资料/STATUS.md`、`交接资料/NEXT_STEPS.md`，再查看 `CoopSync/ADAPTER_CONTRACT.md`。

## 项目目标

实现真正双人合作：主机权威场景/门/碰撞/敌人/任务/检查点；两人攻击由主机结算；普通1级新游戏、奖励升级与保存继续。剧情先召集、双方就绪后进入同一段，任意一人跳过则双方走正常结束流程。原 SMT 仅是参考，自主实现不限于其闭源接口。

## 当前边界

- `CoopSync/src` 有真实 Windows TCP 协调器；当前可执行入口要求 `--simulate`，游戏动作仍是模拟。
- `CoopSync/src/runtime` 是真实加载验证过的只读观察 DLL；不是已实现控制的游戏后端。
- 分开标注 static / mock / real-process / human-report / dual-game evidence。localhost TCP、任务摘要或原始字段相同，不能证明游戏世界复制。
- 当前 Health 实例不必是敌人；负64位 key 只是身份候选，不能直接用作跨电脑实体 ID。
- 菜单也有相同 Cinematic2 资源和变化中的计时，不能仅以选取槽或 EC/F0 判断任务剧情。

## 开发约定

- 实际游戏安装路径用当前电脑配置；保留固定游戏 SHA-256/AMD64/大小/实例核验，未知构建拒绝固定 RVA。
- 历史日志只作证据，不能把原机 PID、pointer、账户目录或输出路径复用为当前对象。
- 不把脚本名、RTTI、反汇编候选入口当作已验证 ABI。控制前需要实例、线程、参数和正常收尾证据。
- 不以穿门、改任务完成标记、各端独立战斗或只同步血条代替需求验收。
- 文件清单、历史原始日志和存档对照留作溯源；新结果创建独立目录并更新状态。
- 运行合适的对应检查；构建与离线测试应先于游戏内验证。不要为未改动部分反复跑长测试。
- 每项交付说明“改了什么、测试是什么、还缺什么”；不能宣称完整联机已完成。

## 关键入口

`CoopSync/build.cmd`、`validate.cmd`、`build_runtime.cmd`；`src/coordinator.*`、`wire.*`、`tcp_transport.*`、`game_adapter.*`；`src/runtime/*`；`tools/runtime_control.py`、`tools/analyze_native_runtime.py`；`research/cinematic_control_feasibility.md`、`world_entity_identity_handoff.md`。
