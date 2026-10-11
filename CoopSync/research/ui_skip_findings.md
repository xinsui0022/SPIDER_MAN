# UI 原生跳过链：固定构建的只读证据

游戏 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。地址均为 RVA。此脚本只读 EXE；不打开进程，不注入，不写游戏内存，不执行游戏函数。完整指令与原始 unwind 字节见同名 JSON。

## 已确认的对象与输入链

RTTI 确认类型为 `GUI::OverlayUI`。直接静态对象位于 `ImageBase+0x7B84580`，并非指针槽。主虚表为 `0x4F44980`，次级虚表为 `0x4F449E0`（对象偏移 `+0x158`）。构造函数 `0x1CF9B0` 的 `0x1CF9CE`、`0x1CF9ED` 将上述虚表分别写入这两个位置；getter `0x1D20D50` 用 LEA 返回对象地址。

`UI_SKIP_MOVIE` 字符串 `0x4F44C48` 在 `0x1D21B79` 被输入注册函数 `0x1D21B70..0x1D21BB7` 引用；它调用 `0x1749A20` 解析输入标识，再以 `RCX=this+0x158`、`EDX=6`、`R8=输入标识` 调用 `0x1D1FE90`。直接调用点 `0xC5AFBB` 在调用 getter 后把返回对象交给此注册函数。这是输入注册链。

主虚表 slot `+0x18` 指向 `0x1D1F9F0`；其 `0x1D1FC93` 尾跳到完整长按处理入口 `0x1D22BE0`。从原回调片段 `0x1D22C02` 读取 `UNW_FLAG_CHAININFO`，依次指向 `0x1D22BF6`、`0x1D22BE0`。完整处理区间含其 epilogue，为 `0x1D22BE0..0x1D22E01`。

长按处理在 `this+0x214` 累积时间，与 `+0x218` 阈值比较；达到阈值后 `0x1D22C7B` 读取 `+0x220`，`0x1D22C94` 把 `+0x228` 放入 RCX，`0x1D22C9B` 间接调用回调。仅静态确认这个参数传递，不把它作为可调用接口。

## Setter 与尚未找到的回调

`0x1D20A10..0x1D20A7C` 将 RDX 写入 `+0x220`，R8 写入 `+0x228`，栈第 5 个 float 参数写入 `+0x218`，`+0x210` 设 1、计时清零；R9 标签复制到 `+0x230`，上限 128。`0x1D20970` 清理字段。RTTI slot `+0x10` 的 leaf 初始化函数 `0x1D1F850` 也清零回调与上下文；旧 slots 扫描因它无 `.pdata` 而漏报该位置，不能忽略无 `.pdata` 的字节候选。

固定 EXE 的 setter E8/E9 调用或尾跳、覆盖的 RIP 取址、绝对地址指针检索均为空；其 RVA32 唯一命中为 `.pdata` 表项。覆盖的直接全局字段 RIP 编码检索亦为空。这不是“无调用者”或“不支持原生跳过”的证明；别名、不同指令形式、内联及其他模块等仍未穷尽。

同偏移扫描可碰到无关类。`0x5B2BB0` 安装 `VultureEngagedBehavior` 虚表 `0x3870710`，不是 OverlayUI。`0x16B0F00` 的 RBP 从 RSP 生成栈帧，向 `RBP+0x220` 的代码地址写入也不能当作 UI 回调赋值。

## 定点只读运行时路径

先核验固定 EXE 路径、SHA-256、模块边界以及对象的双虚表；然后才可读取对象 `+0x210` 原始标志、`+0x214` 原始 float 字节、`+0x220` 回调指针、`+0x228` 上下文。绝对地址由运行时模块基址加 RVA 得到。定点字段 RVA 依次是 `0x7B84790`、`0x7B84794`、`0x7B847A0`、`0x7B847A8`。读取前后复核双虚表与指针槽；不扫描、解引用上下文，不调用 getter 或回调。

尚需在自然播放的可跳过过场中只读观察非零回调，并继续静态确认其目标与原生清理副作用。当前已核验可调用接口数量仍为 **0**。

## Overlay 图标方法与复现

原始 `Overlay.gfx` SHA-256：`401deb23e629567dc539de9029cdc55fb79ced7c4a48029121c34e312f231808`。ABC method 1150/1151/1152 的 `ShowSkipCineIcon`、`UpdateSkipCineIcon`、`HideSkipCineIcon` 只负责图标与进度；不能作为执行跳过接口。`SkipCinematic` UI 配置枚举和 `EndCinematic` 命令的 `TimedOut` 分支也未证明等于用户原生跳过。

在 CoopSync 目录运行（Python 3.11、pefile、已有 GNU objdump）：

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_probe.py --report
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_probe.py --unwind 0x1D22C02
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_probe.py --rtti 0x4F44980 0x4F449E0
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_probe.py --range 0x1D22BE0 0x1D22E01
```

## 独立只读基线记录

父任务标注为 paused baseline 的 PID `25612` 已保存到 `ui_skip_runtime_baseline_20261010.jsonl`；3 个采样均完成双虚表与槽前后复核。

- `0x210` 已接受采样的不同原始字节：`00`。
- `0x214` 已接受采样的不同原始字节：`00000000`。
- `0x220` 已接受采样的不同原始字节：`0000000000000000`。
- `0x228` 已接受采样的不同原始字节：`0000000000000000`。

上述当前零值不能证明不存在过场或缺少原生跳过路径。`ui_skip_runtime_probe.py` 每个快照最多 8 次、69 字节定点读取；16 字节读取仅覆盖相邻且静态确立的 callback/context 两槽。复用 Session 的 SHA/path/module/只读 handle 门控，不调用 cinematic snapshot。槽或类型变化时丢弃字段，不调用函数，不解引用 context。

```powershell
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_runtime_probe.py --self-check
& 'C:\Users\xinsui\AppData\Local\Programs\Python\Python311\python.exe' .\research\ui_skip_runtime_probe.py --pid 25612 --samples 201 --interval-ms 100 --output .\research\ui_skip_observer_new.jsonl
```

输出文件必须是新文件；已存在时拒绝覆盖。PID 必须来自重新核验的当前游戏进程。
