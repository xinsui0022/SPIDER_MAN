# 原生模块接入记录（2026-10-11，香港时间）

已将自主 C++ DLL 加载到真实游戏进程，并完成启动、只读采样、状态查询和停止验证。模块能观察过场、任务及门/血量组件；尚未执行游戏过场控制或世界复制。

## 成果及构建

- `src/runtime/runtime_lifecycle.*`：40 字节版本化 ABI，显式 Start/GetStatus/Stop。
- `src/runtime/runtime_sampler.*`：游戏路径与 SHA-256 校验，过场、跳过 UI 和任务子集只读观察。
- `src/runtime/runtime_world.*`：Door、DoorAnimated、DoorSlide、Health、BotHealth 白名单实例观察。
- `build/CoopSyncRuntime.dll`：自主原生诊断 DLL，与 SMT 无依赖。
- `tools/runtime_control.py`：加载并调用自有 DLL 的三个导出；拒绝旧版本地址不一致。
- `build_runtime.cmd`：构建原生 DLL 并执行对应检查。

本机 C++17/MSVC x64 使用 `/W4 /WX /MT`。41 项生命周期假后端检查、37 项世界模拟内存检查、38 项控制工具合成检查通过。另用生产 DLL 在独立测试宿主验证：不会自动启动，错误宿主在固定地址采样前被拒绝，零游戏操作，停止成功。离线检查均没有附加游戏。

## 已完成的真实加载验证

游戏 PID `17652`，游戏 SHA-256：

`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`

本轮 DLL SHA-256：

`b92dda455a79b86d5f50c5173744aa5d17cf9d409c56ffac79bc151eb7a2360e`

菜单基线：`logs/native_runtime_20261011_menu_verified/`。加载模块地址 `0x7ffb7ee60000`，实际 session 为 `pinned_game_verified`。Start 返回 0 后，再次查询达到 `Observing`；停止返回 0，最终 `Stopped`、错误码 0、350 样本。已取得 Health 和门组件原始记录；菜单中任务管理器未初始化。菜单资源对象不能证明玩家已经进入关卡，Health 也不能直接等同于某只可见敌人。

第一次沙箱内尝试在 OpenProcess 权限处收到 WinError 5，未加载模块、没有保留参数；在用户已授权的沙箱外测试环境重试后成功。失败记录单独保存在 `logs/native_runtime_20261011_menu/`。

随后再次 Start，同一个 DLL 开始关卡观察，目录 `logs/native_runtime_20261011_level/`。用户进入“救助平民”，并报告此前剧情自然播放结束、没有跳过选项。任务原始目标 `GP_A1_FISK_HELP_CIVS` 与报告相符。完成 4432 样本/447.094 秒记录，再次 Stop=0/Stopped/错误码0，游戏进程仍响应。

关卡记录共 2989 次白名单观察：600 个 Health、2 个 DoorSlide、3 个 DoorAnimated 局部实例，同一实例重复观察没有发现白名单字段变化。本轮不能证明伤害或开关门已捕获；有 242 个世界读取缺口（187 次 map 容量超限、55 次记录数上限），全部明确记录，读取预算没有耗尽。

关卡捕获 70 个过场组件样本，A0/A8 候选为 `0x9a05b474457c6ab3`（36次）与 `0xa396986e277e19c6`（34次）。菜单中也有第一个候选及 EC/F0 时间变化，构成“仅用选取槽/时间字段判播放”的反例。不能直接把某个资源对应到用户剧情，也未验证过场边界。完整分析见两目录中的 `analysis.json`。

`tools/analyze_native_runtime.py` 与 16 个测试方法验证上述记录分析；截断、非法/重复 JSON、非有限数值、实例混合、越界、误声明已验证能力均拒绝。未结束或读取中变化的记录明确保留 incomplete 标记。分析不会赋予门开/死亡/剧情阶段语义。

## 加载与停止方法

先启动正确构建的游戏，再使用本机 Python 3.11：

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' -X utf8 -B tools\runtime_control.py attach --output-dir logs\native_runtime_unique --interval-ms 100
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' -X utf8 -B tools\runtime_control.py status
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' -X utf8 -B tools\runtime_control.py stop
```

输出目录必须是新目录。仅有一个正确游戏进程时可省略 PID。Start 返回 0 只表示线程已创建；必须再查状态并读实际 session/snapshot。Stop 停止采样，首次 LoadLibrary 引用保留到游戏退出；它不会恢复 SMT 或自动运行旧脚本。DLL 更新后必须退出游戏再加载新版本；控制工具在调用前比较已加载模块的 PE 文件头、导出表和重定位后的全部执行代码，版本不符即拒绝。

## 能力与证据边界

加载器调用 Windows LoadLibraryW/CreateRemoteThread，并只为自身 DLL 与参数分配内存。写入限于新参数缓冲区及自身 Status ABI 回包。采样器对游戏对象只有有界 ReadProcessMemory，没有引擎函数调用、Hook、门命令、血量修改或存档写入。游戏安装文件及旧插件加载配置没有改变；模块是临时加载到内存。

世界采样每次滚动最多 128 实体，最多 128 map slot/实体、32 个白名单记录、16384 次读取/1MiB。92160 个表槽在 100ms 间隔下完整扫描约 72 秒；短事件可能漏采，因此不用于实时复制。对象在读取期间变化、短读、预算耗尽都保留缺口，不能拿缺口当销毁或死亡。实例身份是本进程 handle/pointer，不是两台电脑共享的实体编号。

尚缺：跨电脑稳定对象映射、游戏线程调度、门动画与碰撞应用、敌人生成/攻击结算/死亡、过场合法开始/跳过/收尾、场景和检查点恢复。现有 TCP 协调器与原生观察器尚未连接为可玩游戏后端。

门命令和血量原生状态注册的静态证据见 `research/world_native_findings.md`。过场资源与事件路径见 `research/cinematic_native_next.md`。完整目标仍是普通新档的双人合作剧情。

Windows 加载/线程实现遵循 [DLL 最佳实践](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-best-practices)及 [CreateRemoteThread 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createremotethread)；DllMain 不执行启动、文件 I/O 或等待。
