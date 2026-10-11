# 在另一台 Windows 电脑接手

## 1. 克隆完整项目

安装 Git for Windows（包含 Git LFS），然后：

```powershell
git lfs install
git clone https://github.com/xinsui0022/SPIDER_MAN.git
cd SPIDER_MAN
git lfs pull
git lfs fsck
python 交接资料\verify_files.py
```

这是一个根目录仓库；保留 `CoopSync` 与 `序章修复调查` 的相邻目录关系。`CoopSync/tools/observe_game.py` 使用父目录的 `observe_missions.py`，单独拷贝 CoopSync 会丢失依赖。

清单校验用于首次克隆后核对交接快照；自行构建和修改源码后与初始快照不同是预期结果。

## 2. 开发环境

- Windows x64。
- Visual Studio 2022 或 Build Tools，安装 Desktop development with C++ 与 Windows SDK。
- Python 3.11 或兼容的64位 Python，依赖见 `CoopSync/requirements.txt`（交接改造后以该文件为准）。
- 静态反汇编需要 objdump；实际游戏读取需要本地合法安装的 Spider-Man Remastered。
- 游戏已审计构建 SHA-256：`e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1`。历史显示版本4.630.0.0；必须以实际哈希校验为准。

配置实际安装文件路径，例如（也可由Steam自动发现）：

```powershell
$env:COOPSYNC_GAME_EXE = 'E:\SteamLibrary\steamapps\common\Marvel''s Spider-Man Remastered\Spider-Man.exe'
# 如发现工具链失败，设置对应 override。
# $env:COOPSYNC_OBJDUMP = 'C:\path\to\objdump.exe'
# $env:COOPSYNC_PYTHON = 'C:\Python311\python.exe'
# $env:COOPSYNC_VCVARS = 'C:\VS2022\VC\Auxiliary\Build\vcvars64.bat'
```

设置后先在 `CoopSync` 执行依赖安装及离线验证。Python/VS发现与可覆盖变量见该目录 README、配置说明和脚本。

## 3. 先验证源码，后测试游戏

```powershell
cd CoopSync
python -m pip install -r requirements.txt
cmd /d /c setup.cmd
cmd /d /c validate.cmd
cmd /d /c build_runtime.cmd
```

运行日志必须分清模拟和真实进程。`CoopSync.exe host/guest --simulate` 验证独立进程的网络协调；它不会让游戏开始联机。

## 4. 当前可实际运行的游戏功能

可用自主诊断 DLL 只读观察真实游戏：

```powershell
python tools\runtime_control.py attach --output-dir logs\my_unique_capture
python tools\runtime_control.py status
python tools\runtime_control.py stop
```

需要有正确版本的游戏进程与访问权限。Start=0只表示线程已创建，要再确认 Observing 和真实 session/snapshot。Stop 停止观察，DLL引用保留到游戏退出；更新 DLL 后需要退出游戏再加载新构建。

仓库没有恢复/自动启用旧 SMT，也没有把旧安装包当成新联机成品。原机旧 winmm.dll 在此前对照中被禁用；另一台电脑要重新查明自己的加载状态，不沿用原机状态结论。

## 5. 让 AI 继续

把 [AI接手提示词.md](AI接手提示词.md) 发给 AI，要求先阅读本仓库 AGENTS 与交接资料、检查本机环境并核对当前状态。下一阶段首先改善实例采样、验证真实过场入口和主机世界应用，再做双机游戏验收。
