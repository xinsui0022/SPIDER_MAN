# HeiHeiSMT 第一阶段只读静态审计报告

审计日期：2026-09-08  
审计目录：`C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod\HeiheiSMT0.5.1\HeiheiSMT`

## 审计结论与范围

**当前目录是 HeiHeiSMT 的发布包，不是源码仓库。**审计时其中有 38 个文件，但没有 `.cpp/.h/.cs` 源码、工程文件、Git 元数据或实际的 PDB 调试文件。因此，不能声称已经完成“完整源码理解”。

本轮完成了现有文件的**只读静态审计**：目录清点、配置读取、PE 导入／导出分析、Launcher 托管 IL 检查、DLL 局部反汇编、字符串交叉引用，以及存档和 UI 资源检查。审计过程中没有修改或新增文件，没有启动 Launcher、Mod 或游戏。本 Markdown 文档是在审计完成后，按用户另行要求新增的报告文件；上述 38 个文件的计数不包含本报告。

**这个版本确实有任务菜单和连接到实际调用代码的任务启动入口。**但尚未证明该入口会同步任务目标、检查点或存档进度，不能据此认定它支持完整合作剧情。

报告中的证据等级：

- **Confirmed**：本地文件内容、元数据或已检查的指令链直接支持。
- **Suspected**：有证据支持，但尚未闭合调用链或完成运行验证。
- **Unknown**：现有材料无法确定。

二进制位置使用 `FO` 表示文件偏移，`RVA` 表示模块相对地址；它们不是源码行号，也不是游戏运行时绝对地址。没有符号的原生函数用 RVA 标识，不把推定名称冒充原始函数名。

## 1. 项目总体架构与关键目录

```text
HeiheiSMT/
├─ SMT-Launcher.exe
├─ winmm.dll
├─ miniupnpc.dll
├─ discord-rpc.dll
├─ cache
└─ SMT/
   ├─ Connections.json
   ├─ Multiplayer.json
   ├─ Preferences.json
   ├─ Scripts/
   │  └─ smt.dll
   ├─ Assets/
   │  └─ UI
   ├─ UI/
   │  ├─ Title.gfx
   │  ├─ SystemOverlay_UIv2.gfx
   │  ├─ HUD.gfx
   │  ├─ Overlay.gfx
   │  └─ POIs.gfx
   └─ Save/
      └─ 23 个存档／备份／偏好文件
```

以下路径均相对于审计目录。

| 编号 | 文件／目录 | 已确认内容与职责边界 |
|---|---|---|
| E1 | `SMT-Launcher.exe` | .NET 单文件程序，内嵌 Launcher 程序集和运行依赖；负责界面、配置与启动游戏 |
| E2 | `winmm.dll` | 原生 x64 DLL；包含系统 WinMM 加载、导出函数代理和 Mod DLL 加载路径 |
| E3 | `SMT/Scripts/smt.dll` | 原生 x64 核心模块；包含联机菜单、Steam 接口、UPnP、游戏对象引用、签名及任务入口 |
| E4 | `SMT/Connections.json` | 保存连接项的 `ip`、`name` 和 `ShowIp`；报告不复述地址 |
| E5 | `SMT/Multiplayer.json` | 犯罪事件开关、敌人参数、移动、角色缩放和可见性配置 |
| E6 | `SMT/Preferences.json` | Discord、加入请求、控制台及 ImGui 偏好 |
| E7 | `SMT/Save/` | 多个槽位、手动存档、备份及用户偏好；并非仅一个指定存档 |
| E8 | `SMT/UI/` | GFx 界面资源，包含联机菜单、存档选择与任务显示相关标识 |
| E9 | `cache` | 6,833 字节二进制文件，核心 DLL 有代码引用；具体格式及用途未确认 |

`miniupnpc.dll` 的端口映射接口被 E3 实际调用。`discord-rpc.dll` 导出的是 Discord Presence／加入请求相关接口，不能把这里的“RPC”直接理解为任务同步 RPC。

`SMT/Assets/UI` 是无扩展名二进制资源，具体容器格式未确认。

## 2. 程序入口与 Launcher 工作方式

### 2.1 托管程序入口

**Confirmed — Launcher 的托管入口已定位。**

E1 内嵌 `SMT-Launcher.dll`：

- 在 EXE 中起始于 `FO 0x945000`。
- 程序集长度为 `27,374,592` 字节。
- 托管入口 Token：`0x06000003`。
- 入口：`SMT_Launcher.App.Main`，程序集内 `RVA 0x2069`。

已检查到的入口逻辑：

```text
App.Main
  → new App()
  → InitializeComponent()
  → Run()
```

元数据、WPF 类型和构建路径共同支持其为 **.NET 8/WPF Launcher**。

### 2.2 游戏启动函数

**Confirmed — 游戏启动函数已读取 IL，而不只是匹配名称。**

函数：`SMT_Launcher.ViewModels.MainViewModel.LaunchWithMultiPlayer`。  
位置：内嵌程序集 `RVA 0x33F8`。

| 模式 | 实际参数 |
|---|---|
| Steam 启动 | `steam://rungameid/1817070//-nolauncher`，联机时追加 ` -mp` |
| 直接启动 | 使用 `GameExePath`，工作目录设为游戏 EXE 所在目录；参数 `-nolauncher`，联机时追加 ` -mp` |

**这个已检查的启动函数没有执行远程进程内存写入或远程线程注入，而是构造启动信息并启动游戏。**这不代表整个程序所有方法都已排除其他行为。

### 2.3 其他关键方法

| 方法 | 内嵌程序集 RVA |
|---|---:|
| `MainViewModel.FindGameExecutable` | `0x3328` |
| `MainViewModel.LoadDataAsync` | `0x3224` |
| `MainViewModel.SaveAllAsync` | `0x325C` |
| `ConfigService.LoadSavedConnectionsAsync` | `0x38BC` |
| `ConfigService.LoadPreferencesAsync` | `0x394C` |

`SaveAllAsync` 等属于 Launcher 配置逻辑，不能当作游戏进度同步证据。

## 3. DLL 加载与 Hook 数据流

### 3.1 WinMM 代理加载

**Confirmed — `winmm.dll` 包含代理加载机制。**

E2 的实际代码链包括：

1. 获取 Windows 目录。
2. 拼接 `\System32\winmm.dll`。
3. 调用 `LoadLibraryA`。
4. 初始化对应导出入口。
5. 解析命令行并比较 `-mp`。
6. 命中后，把 `./SMT/Scripts` 交给目录加载函数。
7. 该函数使用 `LoadLibraryA` 加载 DLL。

| 关键位置 | E2 中的位置 |
|---|---|
| 系统 WinMM 路径与加载 | `RVA 0x5EEF`、`0x5EF5`、`0x5F17` |
| `-mp` 字符串 | `FO 0xB74C` |
| 参数比较 | `RVA 0x6098` |
| Mod 目录加载 | `RVA 0x60B8 → 0x2C10` |
| DLL 加载调用 | `RVA 0x3038` |

**Suspected — 实际部署依靠游戏加载同目录的代理 WinMM。**

这是与上述代码相符的架构，但当前包内没有游戏 EXE，尚未检查游戏导入表或运行时模块列表，不能确认 Windows 在当前安装中具体如何选中这份 DLL。

```text
Launcher：追加 -mp 并启动游戏                  [Confirmed]
                 ↓
游戏进程加载本地 winmm.dll                    [Suspected：需实际模块列表]
                 ↓
加载系统 WinMM，并按 -mp 加载 SMT/Scripts DLL  [Confirmed：静态代码]
                 ↓
smt.dll 初始化、解析游戏地址、接入游戏系统      [部分 Confirmed]
                 ↓
运行时实体／菜单／会话行为                    [尚未动态验证]
```

### 3.2 核心 DLL 入口

E3 的 PE 入口为 `RVA 0x6AE98`。已追踪到：

```text
0x6AE98 → 0x6AD70 → 0x24990
```

`0x24990` 具有 DLL 初始化回调形态，处理加载原因、命令行和后续初始化；没有源码符号，不能把推定名称冒充原始函数名。

## 4. 内存地址、签名扫描与游戏内部调用

| 检查项 | 结果 |
|---|---|
| 内存偏移访问 | **Confirmed**：存在大量对象字段偏移和全局指针访问 |
| Pattern／Signature 数据 | **Confirmed**：E3 中识别出 286 条符合十六进制通配签名格式的完整可读字符串 |
| 地址解析及保存 | **Confirmed**：检查到将匹配结果／相对位移计算结果写入全局指针的代码 |
| 间接函数调用 | **Confirmed**：包括任务入口使用的全局函数指针 |
| 内存修改相关 API | **Confirmed**：导入 `VirtualProtect`、`VirtualAlloc`、`FlushInstructionCache` 等 |
| 全部 Hook 目标及安装顺序 | **Unknown** |
| MinHook／Detours 等具体框架 | **Unknown**：没有发现名称，不能排除静态链接 |
| 对特定游戏版本的完整适配条件 | **Unknown** |

### 4.1 与任务直接相关的调用链

```text
任务 UI 回调 RVA 0x61910
  → 读取参数中的 "mission"
  → 调用 RVA 0x2D920
  → 间接跳转到 [模块基址 + 0xC0810]
```

该目标指针在 `RVA 0x2D84D` 写入；其前面的解析流程引用签名字符串 `FO 0x793A8`。

**Confirmed：任务入口不是仅有名称的空字符串，它连接到了可执行回调和动态解析的函数地址。**

**Unknown：最终目标在游戏中的准确函数名、完整语义，以及它是否同时触发网络事件。**这需要对应源码，或游戏本体与运行时地址映射。

### 4.2 游戏对象与组件线索

找到的游戏对象／组件名称包括：

- `HeroRemote`、`HeroCharacter`
- `HeroMoverManager`
- `AnimControllerComponent`
- `HeroTransitionManager`
- `HeroCameraManager`
- `ActorOutlineManager`
- `CombatChallengeSystem`

这些名称的存在已确认，但不能仅凭名称断言其字段被同步。没有发现可读的 `MissionManager`、`PlayerManager`、`WorldManager` 精确名称；不能据此认定对应对象不存在。

## 5. 网络层、Host／Client 与连接数据流

### 5.1 主机与加入者

**Confirmed — 存在 Host／加入会话的界面及权限分工。**

E3 中包含：

| 标识 | FO |
|---|---:|
| `SMT_Host` | `0x7F4C8` |
| `SMT_Join` | `0x7F2C8` |
| `SMT_KickPlayer` | `0x7E3E0` |
| `SMT_TeleportPlayerToMe` | `0x7E3C0` |

另有主机专用提示、服务器已满、版本不符、连接超时等分支文案。

这支持存在主机与加入者的角色设计，**但网络实体权限、敌人权威端和任务权威端尚未确认**。

### 5.2 端口及网络依赖

**Confirmed — UPnP 实际配置 TCP 7637 与 UDP 7638。**

不是仅从错误提示推断：

- `RVA 0x1BF80` 使用端口 `0x1DD5 = 7637`。
- `RVA 0x1C0D0` 调用 `UPNP_AddPortMapping`，参数包含 `TCP`。
- `RVA 0x1C139` 使用端口 `0x1DD6 = 7638`。
- `RVA 0x1C267` 再次映射，参数包含 `UDP`。

**这证明端口映射逻辑，不等于已经证明 TCP／UDP 各自承载哪些数据。**

| 项目 | 判断 |
|---|---|
| WinSock | **Confirmed**：直接导入初始化／清理和地址转换相关接口 |
| MiniUPnPc | **Confirmed**：实际调用发现网关、添加／删除端口映射 |
| Steam | **Confirmed**：导入 Steam API，并含 Lobby 回调类型、Friends／Matchmaking 接口 |
| Steam 是否承载实时游戏数据 | **Unknown** |
| ENet／RakNet／其他传输库 | **Unknown**：未发现可读名称，不能排除静态链接或游戏内部实现 |
| 独立服务器或主机中转细节 | **Unknown** |

### 5.3 连接阶段与消息边界

E3 的连接界面在 `RVA 0x49773` 等位置根据状态选择以下提示：

```text
Connecting to server
→ Syncing initial state
→ Syncing clients
→ Creating clients
→ Syncing game state
→ Creating game state
→ Syncing load state
→ Requesting game entry
```

**Confirmed：这是代码使用的阶段提示。**  
**Unknown：每阶段对应的消息结构、真实执行顺序、失败恢复及载荷内容。**

当前没有恢复出可信的完整 packet／message 清单、消息 ID、序列化结构或收发分发表。`SMT_StartMission` 等是 UI 命令标识，不能直接列为网络包名称。

## 6. 玩家、战斗与世界状态同步范围

两名玩家能进入同一联机会话是用户提供的运行事实；本轮没有独立复现。对于具体字段，目前证据如下：

| 数据 | 现有证据 | 同步结论 |
|---|---|---|
| 玩家实体 | `HeroRemote`、`ClientInfo`、远程玩家分组、加入／离开处理线索 | **Suspected**：有远程实体体系；实体创建与网络身份映射未闭环 |
| 位置 | 传送命令、移动组件及远程移动状态 | **Unknown**：字段、频率、插值和权威端未恢复 |
| 朝向 | 未恢复明确网络结构 | **Unknown** |
| 动画／移动状态 | `AnimControllerComponent`、远程跳跃／ZipToPoint 状态、Emote 系统 | **Suspected**：涉及远程动作处理；不确定同步动画、输入还是状态机 |
| 战斗 | 近战／远程目标组件、伤害统计、敌人击败统计 | **Unknown**：不能证明命中判定或伤害事件跨端复制 |
| 血量 | `Health` 标识及敌人血量配置 | **Unknown**：玩家／敌人血量权威和复制均未确认 |
| 敌人 | 生成、难度、基地和犯罪相关入口 | **Unknown**：没有恢复敌人网络 ID、生成／死亡消息 |
| 外观与显示 | 玩家缩放、名称、距离、描边配置 | **Confirmed**：有配置和菜单；是否全员同步 **Unknown** |
| 世界状态 | 时间设置、犯罪开关、基地启动、任务启动入口 | **Confirmed**：存在相关功能入口；跨端同步 **Unknown** |
| 剧情进度 | 未恢复进度消息或一致性处理 | **Unknown** |

E5 中敌人血量和生成倍率当前均为 `0.0`。**不能直接解释为零血量或不生成敌人**：它们可能是归一化滑块值，必须追踪参数换算。

## 7. 存档相关逻辑

### 7.1 独立存档目录及路径介入

**Confirmed — 存在独立存档目录及目录字符串写入代码。**

E3：

- `SMT/Save/`：`FO 0x73EC0`。
- `RVA 0x1ADB0`：先调用一个全局函数指针，随后通过 `memcpy` 把该路径写入传入缓冲区。

这是存档路径介入的实质线索，强于仅发现字符串。

**Suspected：用于把某个游戏存档路径查询结果重定向至 Mod 目录。**但本轮尚未闭合该函数的 Hook 注册及调用方，不能把运行时重定向范围当作已证实事实。

### 7.2 存档选择／有效性检查

**Confirmed — 有实际的存档选择／有效性检查。**

E3 `RVA 0x5E130` 分支中：

- 读取对象 `+0x150` 的索引。
- 检查该索引及两个按索引访问的值。
- 不满足条件时进入 `NO SAVE SELECTED` 提示。
- 满足条件时走后续 Steam 接口间接调用。

准确字段名未恢复，不能把这几个数值擅自解释为“剧情完成度”。

另有：

- `LoadSave`、`OpenMpLoadSaveMenu`：E3 `FO 0x7F3C0`、`0x7F3E0`。
- `Title.gfx` 中 `OpenMpLoadSaveMenu`：`FO 0x761A8`。

### 7.3 是否必须使用指定存档

**Unknown — 尚未证明“必须使用某一个指定存档”。**

没有找到已确认的：

- 指定存档哈希／文件内容白名单。
- 强制通关百分比。
- 强制角色等级。
- 特定剧情节点作为入场条件。
- 把所有玩家进度强制写成固定值的调用链。

### 7.4 存档中的任务与进度字段

**Confirmed — 现有存档确实包含任务／进度字段名称。**

以 `SMT/Save/slot0-s.save` 为例：

| 字段名称 | FO |
|---|---:|
| `CurrentCheckpointId` | `0x476` |
| `PlayerLevel` | `0x5FD` |
| `ActiveMissionHash` | `0x613` |
| `LevelUnlockedFlags` | `0x87C` |
| `LevelCompletedFlags` | `0x88F` |
| `MissionStartRollbackIndex` | `0x1387` |
| `ObjectiveStartRollbackIndex` | `0x13A1` |
| `ActiveProgress` | `0x2AC0` |
| `Objectives` | `0x2AD7` |

这里确认的是字段名称，没有完整解析其类型和值。**游戏存档包含 Objective 字段，不代表 Mod 同步了 Objective。**

对“为什么指定存档似乎必需”的解释，目前只能保留为：

- **Suspected**：Mod 使用独立存档目录，导致普通游戏已有存档没有自然出现在联机流程中。
- **Suspected**：发布者提供的存档用于满足自由探索、角色能力或内容解锁前提。
- **Unknown**：是否有真正硬性的剧情兼容门槛，还是分发／使用说明造成的限制。

## 8. Mission／Objective／Progression 搜索与追踪结果

### 8.1 关键词检查

| 关键词 | 结果与边界 |
|---|---|
| `mission` | E3 有任务菜单、任务参数、启动回调、进行中检查及主线顺序配置路径 |
| `objective` | E3 未发现可读匹配；存档和 HUD／POI 资源有大量相关字段 |
| `quest` | E3 的子串命中主要来自 `request` 等，不作为任务证据；UI 中有 `TYPE_QUEST` |
| `story` | E3 未发现可读匹配；不代表不存在哈希或无符号实现 |
| `progression` | E3 未发现可读匹配；存档另有 `ActiveProgress` 等字段 |
| `checkpoint` | E3 未发现可读匹配；存档及 UI 存在检查点相关内容 |
| `activity` | E3 用于任务／基地正在进行时的限制提示 |
| `save` | 存档目录、选择菜单、检查分支；Launcher 中还有独立的配置保存逻辑 |
| `world state` | E3 未发现对应可读文本 |
| `game state` | E3 有连接阶段提示及实际引用；未确定内容 |

### 8.2 任务相关关键发现

1. `SMT::UI2::MissionsMenu` 及其 `OnInit` lambda 出现在 RTTI 中，位置包括 E3 `FO 0xBB5E8`、`0xB9610`。
2. 任务启动命令注册代码位于 `RVA 0x61890`，引用 `SMT_StartMission`。
3. 关联回调 `RVA 0x61910` 读取 `"mission"` 参数，并进入前述动态函数指针调用。
4. 菜单代码有“任务正在进行”的检查／提示分支，涉及 `RVA 0x613C3`、`0x6140D`。
5. 二进制含主线配置路径 `configs/missionorderconfig/missionorderconfig_goldenpathlinear.config`，位置为 E3 `FO 0x82A90`。完整资源加载链尚未恢复。
6. 存在 `GP_A1`、`GP_A2`、`GP_A3` 和三个 Act 标签，以及多个 `OM_BASE_*` 基地标识。

这能支持“**有主动选择／启动任务与基地的功能设计和实现入口**”，不能支持以下结论：

- 每个 Objective 会同步。
- 任务完成后两端进度共同保存。
- 过场、失败、检查点回滚会一致。
- 新游戏序章可完整合作游玩。

UI 中还保留 `ShowNewObjective`、`POIMissionObjective`、新游戏与检查点菜单标识。它们可能包含游戏原有资源，不能当作 Mod 已实现相应联机功能的证明。

## 9. 架构 A／B／C 判断

| 候选 | 当前判断 |
|---|---|
| **A：只同步玩家实体** | **不能确认。**功能范围明显不止玩家菜单，但没有恢复完整同步边界 |
| **B：已经同步部分世界状态** | **Suspected，暂时最接近的调查假设。**依据是世界活动入口、多阶段会话状态及游戏状态创建提示；缺少网络载荷证明 |
| **C：已有任务同步框架，但不完整** | **Unknown。**已经确认的是任务启动／管理入口，尚不是任务网络同步框架 |

**严格结论：目前不能用 Confirmed 等级把它归入 B 或 C。**特别是，不能把“能启动任务”与“能共同推进任务”合并为同一个能力。

## 10. 已确认事实、高概率推测与未确认问题

### Confirmed

- 当前提供的是发布包，完整源码审计所需材料缺失。
- Launcher 使用 `-mp` 启动联机路径。
- WinMM 代理包含系统 DLL 加载和 Mod DLL 加载逻辑。
- 核心模块大量使用签名和动态函数地址。
- 存在 Host／加入者界面、Steam Lobby 集成与 UPnP 端口映射。
- 存在存档选择检查和存档路径介入代码。
- 存在有实际调用链的任务启动入口。
- 未恢复出完整消息协议或任务进度复制链。

### Suspected

- 实际加载架构为游戏目录中的 WinMM 代理加载核心 Mod。
- Mod 对游戏存档路径进行了重定向。
- 联机流程更偏向加载已有世界后进行多人活动，而不是已验证的全剧情合作。
- 某些世界状态可能参与同步，但范围未知。

### Unknown

- 指定存档究竟是硬性要求、兼容要求，还是发布者的推荐用法。
- 高等级／高进度是否完全来自附带存档。
- 任务不显示发生在资源、菜单、解锁条件、任务管理器还是同步层。
- Host 启动任务后 Client 是否收到任何任务消息。
- 敌人、伤害、Objective、检查点由谁裁决。
- 两端是否各自保存、仅主机保存，或限制联机保存。
- 核心模块的网络协议、消息结构和完整 Hook 清单。

## 11. 后续最值得做的 5 个调查步骤

### 1. 取得与这份 DLL 对应的源码、提交号及符号

Launcher 内嵌了仓库链接 [hbgda/SMT](https://github.com/hbgda/SMT)，但本轮未访问，也未验证它与 HeiHeiSMT 分发包一致。必须先确认版本对应，避免审计错误分支。

当前核心 DLL SHA-256：

```text
b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7
```

### 2. 闭合存档路径与入场校验调用链

从 E3 `RVA 0x1ADB0` 和 `0x5E130` 追踪 Hook 注册、索引对象及字段含义；再比较附带存档与正常新游戏存档。目标是区分“目录不同”“必须选有效存档”和“必须达到指定剧情”。

### 3. 恢复网络发送／接收与消息分发表

以 Host／Join 初始化、TCP 7637／UDP 7638 和连接阶段状态为入口，确认传输实现、消息 ID、序列化字段及实体权限。必要时运行两端并抓包；抓包只能辅助，不能自动解释字段语义。

### 4. 追踪任务启动到完成的整条链

从 `SMT_StartMission → RVA 0x61910 → 0x2D920 → 全局函数指针` 出发，识别真实游戏函数，再寻找 Objective 更新、任务完成、失败和检查点回滚是否进入网络层。这一步可能需要游戏本体反汇编和调试器。

### 5. 设计隔离存档的双端复现实验

在后续明确进入运行调查阶段后，分别测试普通新存档／附带存档、Host／Client、主线／基地／犯罪活动，记录任务出现、开始、目标变化、完成、退出重进及进度落盘。这样才能确定故障发生在哪一环，而不把所有问题归因于“没有任务同步”。
