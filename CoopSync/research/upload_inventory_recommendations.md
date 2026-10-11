# 父开发目录上传取舍建议

只读检查目录：`C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod`。以下数字是检查时的文件尺寸；活跃日志可能增长。本检查没有移动、删除、上传文件，也没有改游戏安装或存档。

## 推荐进入源码仓库

- `CoopSync/src/`、`tests/`、`tools/`、各 build/validate/record 脚本与根 Markdown contracts/progress/接手说明。
- `CoopSync/research/` 中自写 probe、selfcheck、正式 findings.md/json 和必要小型真实证据。保留 `cinematic_static_probe.py` 与 `cinematic_runtime_probe.py`，因为 world 脚本会导入它们。
- 身份研究最低证据组：`world_entity_identity_findings.md/json`、`world_entity_identity_handoff.md`、两个 static probe、`world_identity_runtime_probe.py`、`world_identity_probe_selfcheck.py`、成功 `world_entity_identity_runtime_20261011_10516_level.json`。失败/rejected JSON 也可保留以说明 guard 行为。
- 历史自写 DoorStep 源码在 `序章修复调查/穿墙候选开发_20261007/DoorStep/`：保留 `DoorStep.cpp`、`door_logic.h`、`tests.cpp`、build/README/install/stop 脚本；vendor MinHook 的 `.c/.h` 和 LICENSE/README 应随源码保留，排除其中 build 产物。
- 历史 `序章修复调查` 的自写 `.py/.md/.cmd` 是门故障/存档对照研究背景，可整理到 `legacy/`；保留与正式报告对应的关键 JSON，使用目录索引区分已证实/候选/被否定结论。历史 save/install 控制脚本不能作为仓库默认 setup 自动执行。
- `电梯门初始化_GameNet只读复核_20261007.md/json`、`穿墙现有接口只读审计_20261007.md`、相关 DoorStep 审计报告对后续 world 工作有直接参考价值。

## 推荐保留本地或单独证据归档，排除 Git 日常源码历史

| 路径/类型 | 本机尺寸/情况 | 建议 |
|---|---|---|
| `HeiheiSMT0.5.1/` | 42文件，约196.72MB；`SMT-Launcher.exe` 单文件189.35MB | 第三方参考发行包；保留版本/hash/说明，仓库不整包复制 |
| `HeiheiSMT0.5.1.zip` | 95.25MB，重复打包 | 排除；与已解压参考包重复 |
| `哥哥安装候选包_20261006*` | 解压包约3.96MB，另有三个各约1.76MB zip旧/中间/当前版 | README与自写安装逻辑可保留；重复DLL/发行包/zip不进源码仓库 |
| `穿门助手候选_20261007*` | v1/v2解压包和zip重复 | 保留自写脚本/README或版本说明；从源码可构建的DLL和重复zip排除 |
| `CoopSync/build/` | 64文件，约9.26MB | 可重建的 exe/dll/obj/pdb/lib/exp等，不进入源码历史 |
| `CoopSync/runtime_lifecycle.lib/.exp` | 根目录额外 linker 产物 | 与 build 产物同样排除 |
| `CoopSync/logs/` | 110文件，约71.44MB | 跟踪精选 analysis/controller/manual_notes 与少量样本；完整 JSONL 保留本地/独立证据归档，提供 SHA-256与索引 |
| `CoopSync/logs/native_runtime_20261011_cinematic_combat_10516/*.jsonl` | 当前约19.13MB | 原始完整日志重要，但不应每次采样追加进Git；正式 prefix analysis 和identity probe小结果更适合交接 |
| `CoopSync/logs/native_runtime_20261011_level/*.jsonl` | 14.67MB | 同上 |
| `序章修复调查` | 1235文件，约124.36MB；许多存档与重复对照备份 | 按源码/结论/选定证据白名单整理，避免整个树无差别上传 |
| `序章修复调查/原版对照_账户…` 与其他存档快照/账户目录 | 账户标识、存档及多次原始对照 | 本地保留；仅整理必要代码/结论/去标识摘要，不上传完整个人存档树 |
| `序章修复调查/客机加入闪退调查_20261006_224235/客机提供原始材料/*.dmp` | 发现1个约0.95MB dump | raw crash dump留本地；保留静态分析报告与hash，不进源码仓库 |
| `__pycache__`、`.control_sandbox_*`、`.mod_save_check_*`、`.source_check_*` | 缓存/临时验证目录 | 排除 |
| `research/*_working.json` | 中间探索/大范围候选xref | 正式 findings已包含必要证据；可本地保留，源码仓库优先正式报告+可复现probe |

本父目录没有发现 `Spider-Man.exe` 游戏本体。它位于外部 `D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered`，不能为了跨电脑复现而复制安装目录、游戏 exe、资源 archive 或存档到源码仓库；接手者应使用自己安装的同构建游戏。

在不丢源码的前提下，最需要减去的是重复第三方参考包/zip、可重建 build、个人存档树与原始大日志。本建议仅列上传选择，所有历史原件仍留在当前本机。
