# 迁移构建验证（2026-10-12，香港时间）

本轮在原开发电脑自动发现 Python 3.11 x64、MSVC x64、Steam 游戏路径和 GNU objdump；`setup.cmd` 返回0。未启动或附加游戏。跨电脑仍需在接手机器执行同样检查。

## 完成的可移植性改造

- 构建、验证与录制脚本改为 `find_msvc.cmd` / `find_python.cmd`，支持发现及环境覆盖。
- `runtime_config.py` 发现Steam库，支持 `COOPSYNC_GAME_EXE` / `COOPSYNC_OBJDUMP`；主运行时、静态探针及其导入工具共用该配置。
- 原生DLL以宿主文件名和固定SHA-256验证游戏，去掉固定安装盘符；AMD64、映像边界、实例校验与能力false仍保留。
- requirements固定 `pefile==2024.8.26`；根仓库保留任务helper的相邻路径。
- `.gitattributes` 保留原文件字节，不自动换行归一化；EXE/ZIP/RAR/DMP使用Git LFS。

## 测试结果

`validate.cmd` 返回0：16协调器、186协议/TCP、14假游戏适配桥、5双进程真实TCP、10异常会话、任务只读自检、15过场与9跳过UI自检、11原分析与31UI分析检查通过。末尾实际查询为waiting_for_game，没有游戏进程。

`build_runtime.cmd` 返回0：41生命周期假后端、生产DLL错误宿主拒绝/零自动启动/正常Stop、37世界假内存、38控制工具合成ABI/旧构建拒绝、16日志分析测试方法通过。

独立世界身份探针22项mock检查通过。6个配置文件发现情形通过，包括自定义Steam库、重复路径、多个安装拒绝、env优先、显式path优先和错误文件名拒绝。没有读取游戏内存或调用引擎。

新构建DLL SHA-256：

`ef4558457b63f026f7380e932708f717173efd5725105b8718ca359cbd6eaa61`

**这个新构建完成了编译和离线检查，未做实际游戏加载验证。** 原来实际加载成功的构建 `b92dda455a79b86d5f50c5173744aa5d17cf9d409c56ffac79bc151eb7a2360e` 在 `原始验证构建/` 留存，不能混淆两者证据。

最新场景实录PID10516没有ended记录，保留分析为active_or_incomplete；交接时游戏已退出。不会为补齐交接而改写历史生命周期。
