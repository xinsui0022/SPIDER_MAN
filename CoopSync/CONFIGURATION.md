# 跨电脑配置

所有自主入口在本目录运行，源码与离线测试不需要复制游戏本体。Python 3.11+ x64，MSVC 2022 x64和Windows SDK；静态研究用GNU objdump，Python依赖见requirements.txt。

`tools/find_python.cmd` 自动查Python launcher、用户安装及PATH，可用 `COOPSYNC_PYTHON` 指定完整exe路径。`tools/find_msvc.cmd` 支持现成x64开发者终端或vswhere发现，可用 `COOPSYNC_VCVARS` 指向vcvars64.bat，`COOPSYNC_VSWHERE`指定vswhere.exe。

`research/runtime_config.py` 按 `COOPSYNC_GAME_EXE` 或Steam注册表/libraryfolders.vdf发现Spider-Man.exe。有多个安装时需要显式配置；没有发现时返回当前目录不存在的候选，实际读取会安全失败。`COOPSYNC_OBJDUMP` 或PATH指定objdump。部分静态探针另有 `--game` / `--objdump` 参数；所有runtime探针继承同一环境配置，运行前设置变量。

```powershell
$env:COOPSYNC_GAME_EXE = 'E:\SteamLibrary\steamapps\common\Marvel''s Spider-Man Remastered\Spider-Man.exe'
$env:COOPSYNC_OBJDUMP = 'C:\Tools\bin\objdump.exe'
# 仅自动发现失败时设置：
$env:COOPSYNC_PYTHON = 'C:\Python311\python.exe'
$env:COOPSYNC_VCVARS = 'C:\VS2022\VC\Auxiliary\Build\vcvars64.bat'
cmd /d /c setup.cmd
```

控制器仍严格匹配配置的完整进程路径与游戏hash。DLL不依赖安装盘符，但必须宿主文件名Spider-Man.exe、AMD64、固定hash和已核验映像边界，任何固定RVA读取前都拒绝错误宿主/构建。改盘符不会取消安全门禁。

`tools/observe_game.py` 使用仓库相邻目录 `../序章修复调查/observe_missions.py` 的已审计只读实现，通过实际进程模块路径核验游戏hash；需要完整克隆父仓库。

历史调查脚本、存档恢复脚本及报告中可能保留原机绝对路径。它们不是日常入口，执行前逐项改为本机配置并核对作用；历史日志不用改写。原生加载工具写的只是新分配参数和自有Status缓冲，不调用引擎状态接口。
