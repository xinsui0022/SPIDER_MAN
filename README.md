# Spider-Man 双人合作联机开发项目

目标是让《Marvel's Spider-Man Remastered》两名玩家共同推进剧情、战斗和存档，场景、门、敌人与检查点以主机为准。

**目前是开发项目，尚没有可玩的完整双人合作补丁。** 已实现自主 C++ TCP 协调器和实际加载验证过的只读原生 DLL；真实过场控制、门/碰撞复制、敌人主机结算仍未接通。

这是完整开发目录的交接仓库，保留源码、工具、静态研究、原始实录、存档对照、历史安装包和原有文件路径。大型 EXE 与 ZIP 使用 Git LFS。游戏本体不在仓库中。

## 从这里接手

1. [另一台电脑的启动步骤](交接资料/START_HERE.md)
2. [给 AI 的完整交接](交接资料/AI_HANDOFF.md)
3. [需求和验收标准](交接资料/REQUIREMENTS.md)
4. [已完成、未完成与最新证据](交接资料/STATUS.md)
5. [下一阶段任务](交接资料/NEXT_STEPS.md)
6. [文件地图与历史材料](交接资料/DIRECTORY_MAP.md)

```powershell
git lfs install
git clone https://github.com/xinsui0022/SPIDER_MAN.git
cd SPIDER_MAN
git lfs pull
```

开发主目录是 [CoopSync](CoopSync/README.md)。旧 SMT 是参考材料；缺少其源码不会限定自研方案。DoorStep 是独立的本地移动研究，不能代替门和碰撞同步。

[AGENTS.md](AGENTS.md) 是仓库内的 AI 工作说明；[AI 接手提示词](交接资料/AI接手提示词.md) 可直接发给另一台电脑上的 AI。原始文件完整性见 [文件清单](交接资料/FILES_MANIFEST.json)。历史日志中的盘符、账号、PID、指针是原机实测信息，不是另一台电脑的配置。

大型文件的克隆方式见 [GitHub 的 Git LFS 说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)。
