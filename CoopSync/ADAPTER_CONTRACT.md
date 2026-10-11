# 游戏适配桥契约

`src/game_adapter.h/.cpp` 提供抽象 `IGameBackend` 和校验桥 `GameAdapterBridge`。**没有真实蜘蛛侠后端，没有已验证的游戏函数地址，也没有场景、门、碰撞或敌人复制实现。** 测试里的 `FakeGameBackend` 仅为离线夹具，所有结果明确标记 `OFFLINE_FAKE_ONLY`。

## 后端的证据义务

- `Observe(ticket)` 读取游戏当前待触发/正在播放的原生实例，通过后端建立的绑定返回 `epoch`、场景实例 token、过场实例 token、场景 ID、剧情资源/节点 ID。不得把传入 ticket 直接回填成所谓游戏证据。两个端的实例 token 可以不同，但逻辑 ticket 必须一致。
- `GatherAndHold` 之前，目标场景和待触发过场必须有已验证的实例绑定。当前玩家尚未加载到目标场景时可以等待准备；`Ready` 必须同时具有实际场景加载、碰撞就绪、玩家所属场景实例和落点就绪证据。准备过程不得自行开始剧情或改变主机剧情修订。
- `Execute(operation,ticket,expected_identity)` 必须在游戏线程实际执行时再核对原生实例和 epoch；如果预检后对象已改变，返回 false，不能执行命令。`Start` 成功返回后必须能观察到同一实例已进入 Playing 或已自然 Ended，不能用计时器假装成功。
- `GatherAndHold` 持有本地准备/结束屏障，客机不得独立提交任务。`Skip` 使用原生正常跳过路径，并保留任务结束过程；已经 Ended 的端不再执行 Skip，即使调用方尚未轮询结束事件。
- `Ended` 需要真实原生结束、任务状态稳定，以及经过验证的**当前场景范围**快照。固定覆盖项为任务、场景、门、碰撞和敌人；经确认不存在的对象可以作为“已验证为空”覆盖。仅任务节点哈希、固定常量摘要和未验证字段不能声明 `world_scope_verified`。
- `world_revision` 来自主机的权威快照流程；`state_digest` 必须对约定范围的稳定、规范化对象状态计算，不能含本机指针或随时变化的非同步字段。桥只检查后端证明标记和覆盖项；它不能证明后端读数真实，更不会传输或应用世界对象。
- 从本地 Ended 报告到 `Release` 必须保留该实例及稳定终态，释放票据与终态必须完全匹配。屏障摘要相等仅允许协调器决定释放，**不能证明全游戏世界已同步**。
- 桥输出 Blocked 后不再调用后端或自动恢复；已有原生屏障继续保留。真实实现必须有经验证的会话退出/人工恢复方案后才能部署，不能靠新 epoch 自动解锁。

`VerifiedGame` 是未来后端承担上述证据义务的标签，不是本项目已经完成验证的声明。默认构造桥拒绝 `Unverified` 与 `FakeForTests`；假后端仅能以显式 `AdapterMode::OfflineFakeTest` 构造，而且观察结果必须保持 Fake 标记。

## 接入协调器

仅把本地动作 `GatherLocal/StartLocal/SkipLocal/ReleaseLocal/BlockLocal` 交给 `bridge.Apply(action)`，周期调用 `bridge.Poll()`。将返回事件按下列方式处理；网络动作由现有传输层处理。

| 桥事件 | 主机处理 | 客机处理 |
| --- | --- | --- |
| Ready | `coordinator.LocalReady(epoch,scene_id,revision,now_ms)` | 发送当前 ticket 的 Ready |
| Ended | `coordinator.LocalEnded(epoch,end_state,now_ms)` | 发送当前 ticket 与 end_state 的 Ended |
| Blocked | `coordinator.Abort(reason)` | 报告错误并停止会话，不继续操作游戏 |

客机把收到的 Prepare/Start/Skip/Release/Blocked 映射为相应本地 Action 后使用同一桥。任意玩家的原生跳过意图应先进入协调器的 LocalSkip 或网络 SkipRequest，不能绕过当前实例检查。动作执行失败应立即停止当前批次的后续非 Block 动作，避免在已经失败的另一端继续开始/释放。

测试编译命令（需 MSVC 环境）：

```cmd
cl /nologo /std:c++17 /EHsc /W4 /WX src\coordinator.cpp src\game_adapter.cpp tests\game_adapter_tests.cpp /Fe:game_adapter_tests.exe
game_adapter_tests.exe
```

测试验证校验逻辑与双假后端/真实协调器的离线集成。真实双机游戏验收仍须另行完成。
