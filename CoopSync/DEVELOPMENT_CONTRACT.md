# CoopSync 第一版开发约定

本目录为自主开发源码，原 SMT 只作为可选游戏适配基础。第一版先构建和测试原生 Windows 协调器与实际 TCP 通信；游戏适配器没有验证的操作不得以模拟成功代替。禁止把模拟过场或哈希一致当作游戏世界同步已经完成。

## 文件职责

- `src/coordinator.h`、`src/coordinator.cpp`、`tests/coordinator_tests.cpp`：纯 C++17 主机权威状态机，不含 Windows、网络或游戏地址。
- `src/wire.h`、`src/wire.cpp`、`src/tcp_transport.h`、`src/tcp_transport.cpp`、`tests/wire_tests.cpp`：有界二进制编解码与 Windows TCP 传输。
- `src/main.cpp`、构建脚本、集成测试和文档由主代理维护。
- `research/`：只读游戏接口定位证据；文件偏移和字符串不得冒充可调用接口。

## 状态机接口约定

命名空间 `coopsync`。定义 `Phase {Idle, Preparing, Playing, Ending, Blocked}`；`ActionType {PreparePeer, GatherLocal, StartPeer, StartLocal, SkipPeer, SkipLocal, ReleasePeer, ReleaseLocal, BlockPeer, BlockLocal}`。

`Ticket` 字段：`uint64_t epoch`、`uint64_t world_revision`、`uint32_t scene_id`、`std::string cinematic_id`、`float x,y,z`。过场ID最长128字节；场景ID和剧情修订来自未来游戏适配器，模拟使用固定测试值。

`EndState` 字段：`uint64_t world_revision`、`uint64_t state_digest`。摘要只是同步屏障输入，不包含世界数据，第一版不得声称已有门/敌人复制。

`Action` 字段：`ActionType type`、`Ticket ticket`、`EndState end_state`、`std::string reason`。

`HostCoordinator` 构造可设准备/结束超时（默认10秒）；方法均返回 `std::vector<Action>`：

- `Prepare(Ticket ticket, uint64_t now_ms)`：仅Idle可开始；epoch由协调器递增分配，发送PreparePeer和GatherLocal。
- `LocalReady(uint64_t epoch, uint32_t scene_id, uint64_t revision, uint64_t now_ms)`；`PeerReady(...)`：两端完全匹配才进入Playing并发StartPeer/StartLocal。
- `LocalSkip(uint64_t epoch, uint64_t now_ms)`；`PeerSkip(...)`：Preparing可记住跳过请求，双方开始后统一Skip；Playing/Ending接受，重复只产生一次跳过指令。
- `LocalEnded(uint64_t epoch, EndState state, uint64_t now_ms)`；`PeerEnded(...)`：可自然完成；两端完成结果相同才Release。不同则Blocked，不自动篡改任务或继续。
- `Tick(uint64_t now_ms)`：超时Blocked。`PeerDisconnected()`：活动中Blocked。`Abort(std::string reason)`：活动中Blocked。
- `phase()`、`ticket()`：只读访问。Blocked不允许自行Prepare；需要显式新建已核验会话，第一版不提供游戏内自动重连恢复。

旧epoch事件一律无作用；若重复Ready/Ended给出矛盾数据则Blocked；无效Ticket拒绝且不消耗epoch。所有时钟由调用方传入单调毫秒。

跳过指令只发给尚未报告Ended的端；已结束端保留屏障状态，避免结束后的请求作用到后续过场。重复Skip不延长结束期限。

## wire格式与消息约定

命名空间 `coopsync`。`enum class MessageType : uint16_t {Hello=1, Welcome=2, Prepare=3, Ready=4, Start=5, SkipRequest=6, Skip=7, Ended=8, Release=9, Blocked=10, Ping=11, Pong=12}`。

`Message` 字段：`MessageType type`、`uint64_t session`、`uint64_t sequence`、`Ticket ticket`、`EndState end_state`、`std::string reason`。wire.h 可include coordinator.h获取结构。

帧：4字节大端payload长度（最大1024字节），payload由 magic `CSY1`、版本1（u16）、类型u16、session u64、sequence u64、epoch u64、world_revision u64、scene_id u32、xyz各float32、end_revision u64、digest u64、cinematic_id长度u16及字节、reason长度u16及字节构成，整数大端，浮点按IEEE位模式大端。所有文本有界（ID128字节、reason256字节）、浮点有限、保留/未知类型拒绝、长度必须精确一致。session和sequence不可为0（Hello使用随机临时session，Welcome回送主机session）；具体类型语义由main验证。

API：`std::vector<uint8_t> Encode(const Message&)` 返回含长度头完整帧，无效输入抛异常；`Message Decode(const std::vector<uint8_t>& payload)` 解payload不含长度头。

`TcpConnection`：RAII移动类，`static TcpConnection Connect(const std::string& host,uint16_t port,uint32_t timeout_ms)`；`void Send(const Message&)`；`bool Receive(Message&,uint32_t timeout_ms)`：整帧未就绪返回false，接收状态保留处理拆包；关闭/错误/非法帧抛异常。`void Close()`。

`TcpListener`：RAII类，构造 `TcpListener(std::string bind_address,uint16_t port)`；`uint16_t port() const`；`TcpConnection Accept(uint32_t timeout_ms)` 超时抛异常。默认绑定127.0.0.1；外部监听必须显式指定。使用Windows Winsock，链ws2_32.lib。tcp实现内部初始化Winsock且处理部分收发；不自动改防火墙、不发送文件、不调用游戏。

第一版Connect和Listener均只接受数字IPv4/IPv6地址；不做DNS查询，以保证连接期限。

## 第一版命令行和验收

`CoopSync.exe host --port <端口> --scenario natural|host-skip|guest-skip` 与 `CoopSync.exe guest --host 127.0.0.1 --port <端口>` 在显式 `--simulate` 下驱动模拟适配器，真实两个进程TCP通信。无模拟参数且游戏操作尚未适配时，明确拒绝执行而非假装控制游戏。测试覆盖正常结束、主机/客机跳过、旧epoch、重复请求、准备中跳过、双方结果不一致、断线和超时、截断/超长帧；集成记录每端状态变化。
