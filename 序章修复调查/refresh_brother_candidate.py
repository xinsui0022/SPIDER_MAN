"""Refresh candidate docs and ZIP only, retaining the verified previous ZIP."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT=Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod").resolve()
NAME='哥哥安装候选包_20261006'
DEST=(ROOT/NAME).resolve()
CURRENT=ROOT/(NAME+'.zip')
OLD=ROOT/(NAME+'_旧版_二次载入验证前.zip')
OUTPUT=ROOT/'序章修复调查'/'哥哥候选包构建核验_20261006_重进验证更新.json'
EXPECTED_OLD='556ead7a57eb715f9a2b3680e14432808f4d09874daba3c8a35c1fccf8c90deb'

def sha(d): return hashlib.sha256(d).hexdigest()

assert DEST.parent==ROOT and CURRENT.parent.resolve()==ROOT and OLD.parent.resolve()==ROOT
assert DEST.is_dir() and not DEST.is_symlink()
assert CURRENT.is_file() and not CURRENT.is_symlink() and not OLD.exists()
assert sha(CURRENT.read_bytes())==EXPECTED_OLD
manifest=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'))
assert len(manifest['entries'])==14
payload_names={x['path'] for x in manifest['entries']}
assert len(payload_names)==14
for entry in manifest['entries']:
    p=DEST/entry['path']
    assert p.is_file() and not p.is_symlink()
    d=p.read_bytes()
    assert len(d)==entry['bytes'] and sha(d)==entry['sha256'], entry['path']
original_names={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}
assert original_names==payload_names|{'README.md','manifest.json','SHA256SUMS.txt'}
with zipfile.ZipFile(CURRENT) as z:
    assert z.testzip() is None
    assert set(z.namelist())=={NAME+'/'+x for x in original_names}
    for rel in original_names: assert z.read(NAME+'/'+rel)==(DEST/rel).read_bytes()

readme='''# 哥哥安装候选包

这是为另一台 Windows x64 电脑准备的离线候选安装包，使用原发布包 SMT 0.5.1 文件。接收方电脑尚未实测；本机核验范围为游戏 4.630.0.0 + SMT 0.5.1，不能保证其他版本兼容。

**已验证的范围：本机只有主机、没有客机时，使用原版正确初始化并推进的 NG+ 检查点，进入费斯克任务、打完门厅后更新为电梯目标，正常关闭并重新进入 MOD 后目标仍保留。** 这条存档恢复路线通过了本机测试；原 DLL、代理与 UI 均未修改。

**这不是完整合作剧情或同步补丁。** 哥哥电脑、客机加入、普通 1 级新游戏、全剧情检查点，以及敌人血量、客机存档、经验和资源同步均未通过本次验证。本包没有加入相应同步代码，也不附带测试存档或任何玩家存档，不能用复制主机存档代替剧情同步。

## 包内内容

`安装文件` 内包含 11 个原发布包运行/资源文件、2 份原配置及 1 份空连接配置。11 个运行文件与两份配置均保持原字节；本次只更新说明和验证范围。

```text
安装文件/
├─ winmm.dll
├─ miniupnpc.dll
├─ discord-rpc.dll
├─ cache
└─ SMT/
   ├─ Connections.json
   ├─ Multiplayer.json
   ├─ Preferences.json
   ├─ Scripts/smt.dll
   ├─ Assets/UI
   └─ UI/{Title,SystemOverlay_UIv2,POIs,Overlay,HUD}.gfx
```

清单与 SHA-256 见 `manifest.json`、`SHA256SUMS.txt`。包内不含 Launcher、游戏 EXE、游戏的 Steam API 文件、Save、Logs、存档备份或诊断材料。`Connections.json` 的列表为空、`ShowIp` 为 false，没有带入原地址或连接名称。

原配置保留 `ShowConsole`、`ShowImGui`、Discord Presence 与加入请求开关，方便对照现有环境；接收方可在 MOD 设置中按需调整。敌人参数存在不代表敌人同步已经实现。

## 接收方条件

接收方需要自己的完整游戏安装和 Steam 环境。核心直接依赖游戏的 `steam_api64.dll` 并使用 Steam 用户、好友和 Lobby 接口；使用自己游戏安装提供的 API 与账户环境。

核心还依赖 x64 Visual C++ 运行库的 `MSVCP140.dll`、`VCRUNTIME140.dll`、`VCRUNTIME140_1.dll` 与 Universal CRT；本包不捆绑系统运行库，也不安装任何软件。

静态代码会尝试 UPnP 映射 TCP 7637、UDP 7638。接收方的防火墙、路由器或 NAT 能否允许连接，需要在接收方实际验证。本包不修改防火墙、路由器或 Steam 设置。

## 安装前备份与安装

1. 正常退出游戏，记录安装前的 Steam 启动选项。确认自己的游戏版本，使两端使用相同 MOD 核心和 UI 文件；本机核验范围为游戏 4.630.0.0 + SMT 0.5.1。
2. 备份自己的原版存档，以及游戏目录现有的 `winmm.dll`、`miniupnpc.dll`、`discord-rpc.dll`、`cache` 和整个 `SMT` 目录（如存在）。保存安装前原有文件清单，把备份放到安装目录之外。
3. 解压 ZIP，把 `安装文件` 里面的内容按原结构放入 `Spider-Man.exe` 所在目录。已有同名 MOD 或代理 DLL 时先备份，按同一套版本做对照。
4. 从自己的 Steam 库启动游戏。**本机实际成功的启动选项原样为 `nolauncher -mp`，其中 `nolauncher` 前没有连字符。** 此处记录实际通过的 Steam 路径；接收方仍需验证。路径无需与主机盘符相同，`SMT-Launcher.exe` 没有放入本包。
5. 进入后确认看到 Spider-Man Multiplayer / SMT v0.5.1 菜单，再选择自己的存档与 HOST/JOIN。仅存在进程或加载 DLL，不能代替进入正常游戏的验证。

## 开始新档与首次测试

本机通过的恢复路线使用 **NG+**，普通 1 级新游戏尚未验证。原版需要先满足其正常的新游戏+条件；本包不会提供通关档或替人解锁 NG+。

1. 剧情主机先以原版单人方式正常创建 NG+，按游戏完整流程初始化并推进到有效检查点。原版单人启动时应使用无联机 `-mp` 参数的设置，并记录原选项以便切换回来。
2. 推进到任务可以显示、操作并正常更新的检查点后，正常退出并备份。此次本机通过的是费斯克门厅推进到电梯目标的检查点；不能把所有序章位置都视为已验证。
3. 再用 MOD 加载这个角色自己的存档副本继续。MOD 使用 `SMT/Save` 独立目录，本包没有存档；准备副本时使用空槽并保留原档。**不要用 MOD 的“选任务/重放序章”代替完整新档初始化，也不要把 MOD 新建 NG+ 菜单视为本轮已验证的建档路线。**
4. 接收方先独立启动并确认 SMT 菜单，没有依赖 DLL 缺失提示。客机也使用自己的有效存档与槽位，所需连接地址仅在自己的电脑上重新填写。
5. 双方分别选择 HOST/JOIN，确认能看到远程玩家并活动。再记录客机加入、任务推进、正常退出后重新进入的目标表现，以及敌人和奖励是否一致。

本机的无客机检查点重载通过，仍不能替代上面的双机验证。能连接、能看到玩家和某一个检查点能重载，各自证明的范围不同。

## 回退

正常退出游戏后，按安装前清单恢复被覆盖的原文件；本次新加入的文件只针对上面的 14 项移出游戏目录，放到保留目录以便检查。恢复安装前 SMT 备份时先保留测试期间新产生的存档，不要直接删除整个 SMT 或自己的存档目录。

**把 Steam 启动选项恢复到安装前记录的原值**；原来为空则清空，原有其他参数按原记录保留。再按原启动方式运行。原版存档不应被候选包覆盖。

## cache 的范围

随包 `cache` 为原发布包的 6,833 字节文件。只读检查发现它恰为 8 字节头与 273 条各 25 字节记录；记录含与本机游戏 PE 时间戳相同的字段，位置值都在游戏映像范围内，符合按游戏构建区分的相对偏移缓存。它没有发现本机个人路径、IP 或 Steam ID 文本，不是本机 ASLR 的绝对进程地址表。

核心存在该文件读取和写回入口；完整缓存再生成流程尚未实机验证，因此本包保留原文件，不能承诺删除缓存就能适配另一版本。若游戏版本不同，应重新核验兼容性。
'''

manifest.update({
    'revision':'local_NGplus_solo_host_checkpoint_reload_verified',
    'status':'offline portability candidate; local solo-host NG+ checkpoint reload verified; receiver not tested',
    'verified_launch_route':'Steam Library',
    'verified_launch_options_literal':'nolauncher -mp',
    'verified_launch_options_note':'The word nolauncher has no leading hyphen in the tested local Steam setting.',
    'verified_story_scope':{
        'local_host_without_client':True,
        'original_game_initialized_NGplus':True,
        'phase':'Fisk ATRIUM combat progressed to ELEVATOR_LOBBY',
        'normal_exit_and_same_save_reload_preserved_target':True,
        'receiver_machine_verified':False,
        'ordinary_level_1_new_game_verified':False,
        'client_join_story_verified':False,
        'full_campaign_verified':False,
        'enemy_health_sync_verified':False,
        'client_save_XP_resource_sync_verified':False,
        'DLL_proxy_UI_modified':False,
    },
    'known_limitation':'Only one correctly original-game-initialized NG+ Fisk checkpoint recovery route was verified on the local host without a client. Receiver machine, ordinary level-1 New Game, full co-op campaign/combat, and client save/XP/resource synchronization remain unverified. No synchronization or DLL/UI patch is included.'
})

# Preserve the previous archive before changing candidate docs or rebuilding.
CURRENT.rename(OLD)
assert sha(OLD.read_bytes())==EXPECTED_OLD
(DEST/'README.md').write_text(readme,encoding='utf-8')
(DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
hash_sources=sorted(payload_names|{'README.md','manifest.json'})
(DEST/'SHA256SUMS.txt').write_text(''.join(sha((DEST/rel).read_bytes())+'  '+rel+'\n' for rel in hash_sources),encoding='utf-8')
updated_names={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}
assert updated_names==original_names
assert not any(any(x.casefold() in {'save','logs','3dmgame','序章修复调查'} for x in Path(rel).parts) or rel.lower().endswith(('.exe','.save','.log','.dmp')) for rel in updated_names)
for entry in manifest['entries']:
    d=(DEST/entry['path']).read_bytes()
    assert len(d)==entry['bytes'] and sha(d)==entry['sha256']
for rel in updated_names:
    d=(DEST/rel).read_bytes().lower()
    for word in ['xinsui','steam__']:
        assert word.encode('utf-8') not in d and word.encode('utf-16-le') not in d
assert json.loads((DEST/'安装文件/SMT/Connections.json').read_text())=={'Connections':[],'ShowIp':False}
with zipfile.ZipFile(CURRENT,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for rel in sorted(updated_names): z.write(DEST/rel,NAME+'/'+rel)
with zipfile.ZipFile(CURRENT) as z:
    assert z.testzip() is None
    assert set(z.namelist())=={NAME+'/'+rel for rel in updated_names}
    for rel in updated_names: assert z.read(NAME+'/'+rel)==(DEST/rel).read_bytes()
for line in (DEST/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    expected_hash,rel=line.split('  ',1)
    assert sha((DEST/rel).read_bytes())==expected_hash

result={
    'current_zip_name':CURRENT.name,'current_zip_bytes':CURRENT.stat().st_size,
    'current_zip_sha256':sha(CURRENT.read_bytes()),
    'old_zip_backup_name':OLD.name,'old_zip_backup_sha256':sha(OLD.read_bytes()),
    'files':len(updated_names),'install_files':len(payload_names),
    'all_14_install_file_hashes_unchanged':True,
    'SHA256SUMS_all_entries_verified':True,'zip_CRC_and_all_bytes_verified':True,
    'empty_connections_verified':True,'forbidden_items_absent':True,
    'game_deployment_changed':False,'sent_externally':False,
    'verified_local_route':'Steam nolauncher -mp; original-game-initialized NG+; local host without client; Fisk ELEVATOR_LOBBY survived normal exit/reload',
    'receiver_machine_and_ordinary_level1_and_coop_sync_unverified':True,
}
OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2))
