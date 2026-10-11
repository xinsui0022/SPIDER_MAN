"""Create a new offline candidate bundle only; never modify deployment/saves."""
from pathlib import Path
import hashlib
import json
import math
import re
import zipfile

ROOT = Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod")
SOURCE = ROOT/'HeiheiSMT0.5.1'/'HeiheiSMT'
GAME = Path(r"D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered")
NAME = '哥哥安装候选包_20261006'
DEST = ROOT/NAME
ZIP = ROOT/(NAME+'.zip')
AUDIT = ROOT/'序章修复调查'/'可移植性静态核验_20261006.json'
RESULT = ROOT/'序章修复调查'/'哥哥候选包构建核验_20261006.json'
RUNTIME = ['winmm.dll','miniupnpc.dll','discord-rpc.dll','cache','SMT/Scripts/smt.dll','SMT/Assets/UI','SMT/UI/Title.gfx','SMT/UI/SystemOverlay_UIv2.gfx','SMT/UI/POIs.gfx','SMT/UI/Overlay.gfx','SMT/UI/HUD.gfx']
CONFIGS = ['SMT/Preferences.json','SMT/Multiplayer.json']

def sha(data):
    return hashlib.sha256(data).hexdigest()

def validate_config(v):
    if isinstance(v,dict):
        assert all(isinstance(k,str) for k in v)
        for x in v.values(): validate_config(x)
    else:
        assert isinstance(v,(bool,int,float)) and (not isinstance(v,float) or math.isfinite(v))

assert SOURCE.is_dir() and not SOURCE.is_symlink()
assert not DEST.exists() and not ZIP.exists(), 'Candidate destination already exists; do not overwrite.'
expected = {x['relative_path']:x for x in json.loads(AUDIT.read_text(encoding='utf-8'))['files']}
payload = {}
entries = []
for rel in RUNTIME+CONFIGS:
    source_path = SOURCE/rel
    assert source_path.is_file() and not source_path.is_symlink()
    data = source_path.read_bytes()
    if rel in RUNTIME:
        assert len(data)==expected[rel]['bytes'] and sha(data)==expected[rel]['sha256'], f'Source mismatch: {rel}'
    else:
        validate_config(json.loads(data.decode('utf-8-sig')))
    payload['安装文件/'+rel] = data
    entries.append({'path':'安装文件/'+rel,'install_relative_path':rel,'bytes':len(data),'sha256':sha(data),'source':'unchanged release file'})
connections = (json.dumps({'Connections':[],'ShowIp':False},ensure_ascii=False,indent=2)+'\n').encode('utf-8')
assert set(json.loads(connections)) == {'Connections','ShowIp'}
assert json.loads(connections)['Connections'] == []
payload['安装文件/SMT/Connections.json'] = connections
entries.append({'path':'安装文件/SMT/Connections.json','install_relative_path':'SMT/Connections.json','bytes':len(connections),'sha256':sha(connections),'source':'generated empty connection template'})

readme = '''# 哥哥安装候选包

这是为另一台 Windows x64 电脑准备的离线候选安装包，基于现有 SMT 0.5.1 文件。没有在接收方电脑实测；目前确认的本机游戏版本为 4.630.0.0，不能保证其他版本兼容。

**本包没有修复序章第二次加载后任务消失，也不承诺合作剧情、敌人血量、存档、经验或资源同步。** 它不附带任何玩家存档，不能用复制主机存档代替剧情同步。

## 包内内容

`安装文件` 内包含 11 个原发布包运行/资源文件、2 份原配置及 1 份空连接配置。原运行文件与两份原配置保持字节不变；代理、核心和 UI 未打补丁。

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

接收方需要自己的完整游戏安装和 Steam 环境。核心直接依赖游戏的 `steam_api64.dll` 并使用 Steam 用户、好友和 Lobby 接口；不要把另一台电脑的 Steam/账户文件或游戏 API 文件复制过来替代安装。两个人的身份应由各自正常运行的游戏/Steam 环境提供。

核心还依赖 x64 Visual C++ 运行库的 `MSVCP140.dll`、`VCRUNTIME140.dll`、`VCRUNTIME140_1.dll` 与 Universal CRT；本包不捆绑系统运行库，也不安装任何软件。

静态代码会尝试 UPnP 映射 TCP 7637、UDP 7638。不同电脑的防火墙和不同路由器/NAT 可能影响连接，需要在接收方实际验证。本包不修改防火墙、路由器或 Steam 设置。

## 安装前备份与安装

1. 正常退出游戏。确认自己的游戏版本；先使两端使用相同 MOD 核心和 UI 文件。本机核验范围为游戏 4.630.0.0 + SMT 0.5.1。
2. 在自己电脑上备份原版存档，以及游戏目录现有的 `winmm.dll`、`miniupnpc.dll`、`discord-rpc.dll`、`cache` 和整个 `SMT` 目录（如存在）。保存本次安装前原有文件的清单，备份放到安装目录之外。
3. 解压 ZIP，把 `安装文件` 里面的内容按原结构放入 `Spider-Man.exe` 所在目录。若已有同名 MOD 或代理 DLL，先做好备份；不要覆盖或混用其他 MOD 的文件来进行对照。
4. `SMT-Launcher.exe` 没有放入本包。继续使用已知的文件式启动方法，启动参数包含 `-mp`，工作目录为游戏目录。通过 Steam 启动时可在游戏启动选项填写 `-mp`；路径无需与主机盘符相同。

## 第一次测试

1. 先独立启动接收方游戏，确认出现 SMT 菜单且没有依赖 DLL 缺失提示。
2. 使用接收方自己的有效存档/槽位。MOD 使用 `SMT/Save` 独立目录，本包没有提供存档；若提示未选择存档，需先备份并准备自己的有效存档副本，不能覆盖原档。MOD 的新建 NG+ 流程和序章二次加载尚未证实可靠。
3. 接收方选择 JOIN 加入主机，确认两端看到远程玩家并能活动；必要连接地址仅在自己的电脑上重新填写。
4. 分别记录进入时、退出重进后和任务推进时是否仍有目标。能连接和能看到玩家不能替代剧情、敌人或奖励同步验收。

## 回退

正常退出游戏后，按安装前清单恢复被覆盖的原文件；本次新加入的文件只针对上面的 14 项移出游戏目录，放到保留目录以便检查。恢复安装前 SMT 备份时先保留测试期间新产生的存档，不要直接删除整个 SMT 或自己的存档目录。移除启动选项中的 `-mp`，再按原启动方式运行。原版存档不应被候选包覆盖。

## cache 的范围

随包 `cache` 为原发布包的 6,833 字节文件。只读检查发现它恰为 8 字节头与 273 条各 25 字节记录；记录含与本机游戏 PE 时间戳相同的字段，位置值都在游戏映像范围内，符合按游戏构建区分的相对偏移缓存。它没有发现本机个人路径、IP 或 Steam ID 文本，不是本机 ASLR 的绝对进程地址表。

核心存在该文件读取和写回入口；完整缓存再生成流程尚未实机验证，因此本包保留原文件，不能承诺删除缓存就能适配另一版本。若游戏版本不同，应重新核验兼容性。
'''
payload['README.md'] = readme.encode('utf-8')
manifest = {'name':NAME,'date':'2026-10-06','status':'offline portability candidate; receiver not tested','verified_local_game_version':'4.630.0.0','mod_label':'0.5.1','launcher_included':False,'original_payload_files':13,'empty_connection_template_files':1,'save_included':False,'entries':entries,'known_limitation':'Prologue objectives can disappear after the second load. Co-op story/combat/save/XP/resource synchronization is not established.'}
payload['manifest.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
payload['SHA256SUMS.txt'] = ''.join(sha(data)+'  '+rel+'\n' for rel,data in sorted(payload.items())).encode('utf-8')

privacy_terms = [('path','xinsui'),('path','STEAM__')]
for config_source in [SOURCE/'SMT/Connections.json', GAME/'SMT/Connections.json']:
    if config_source.is_file():
        v=json.loads(config_source.read_text(encoding='utf-8-sig'))
        for c in v.get('Connections',[]):
            for field in ['ip','name']:
                value=c.get(field)
                if isinstance(value,str) and len(value)>=3: privacy_terms.append((field,value))
for rel,data in payload.items():
    assert not any(segment.casefold() in {'save','logs','3dmgame','序章修复调查'} for segment in Path(rel).parts)
    assert not Path(rel).is_absolute() and '..' not in Path(rel).parts
    assert not rel.lower().endswith(('.save','.log','.dmp','.exe'))
    for kind,term in privacy_terms:
        needle=term.casefold().encode('utf-8')
        if kind=='name' and term.isascii():
            # A short display name can occur inside an unrelated built-in UI identifier.
            hit=re.search(rb'(?<![a-z0-9_])'+re.escape(needle)+rb'(?![a-z0-9_])',data.lower())
        else:
            hit=needle in data.lower()
        assert not hit, f'Private text detected in {rel}'
        assert term.casefold().encode('utf-16-le') not in data.lower(), f'Private UTF16 text detected in {rel}'

DEST.mkdir()
for rel,data in payload.items():
    target=DEST/rel
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    assert target.read_bytes()==data
with zipfile.ZipFile(ZIP,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for rel in sorted(payload): z.write(DEST/rel,NAME+'/'+rel)
with zipfile.ZipFile(ZIP) as z:
    assert z.testzip() is None
    assert set(z.namelist())=={NAME+'/'+rel for rel in payload}
    for rel,data in payload.items(): assert z.read(NAME+'/'+rel)==data
assert len(entries)==14 and len(payload)==17
result={'candidate_directory_name':NAME,'zip_name':ZIP.name,'zip_bytes':ZIP.stat().st_size,'zip_sha256':sha(ZIP.read_bytes()),'archive_files':len(payload),'install_files':len(entries),'runtime_unchanged_files':len(RUNTIME),'unchanged_config_files':len(CONFIGS),'connections_empty':True,'source_hash_checks_passed':True,'zip_roundtrip_hash_checks_passed':True,'personal_address_name_path_terms_checked_without_emitting_values':True,'short_ascii_display_names_checked_as_whole_identifiers':True,'forbidden_items_absent':True,'deployment_modified':False,'sent_externally':False}
RESULT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2))
