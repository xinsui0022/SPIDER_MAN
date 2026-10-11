"""Clarify candidate native setup docs; retain both prior candidate archives."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(r"C:\Users\xinsui\Desktop\游戏\蜘蛛侠联机mod").resolve()
NAME='哥哥安装候选包_20261006'
DEST=(ROOT/NAME).resolve()
CURRENT=ROOT/(NAME+'.zip')
INTERMEDIATE=ROOT/(NAME+'_中间版_原版初始化说明修正前.zip')
EARLIER=ROOT/(NAME+'_旧版_二次载入验证前.zip')
EXPECTED='d7ce70d4aa9986fdebbf0869827b7487e60f7dca8f3b85034347a652d085c06c'
EARLIER_HASH='556ead7a57eb715f9a2b3680e14432808f4d09874daba3c8a35c1fccf8c90deb'
OUTPUT=ROOT/'序章修复调查'/'哥哥候选包最终核验_20261006.json'

def sha(data): return hashlib.sha256(data).hexdigest()

assert DEST.parent==ROOT and CURRENT.parent.resolve()==ROOT and INTERMEDIATE.parent.resolve()==ROOT
assert not DEST.is_symlink() and CURRENT.is_file() and not CURRENT.is_symlink()
assert not INTERMEDIATE.exists() and sha(CURRENT.read_bytes())==EXPECTED
assert EARLIER.is_file() and sha(EARLIER.read_bytes())==EARLIER_HASH
manifest=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'))
install_names={x['path'] for x in manifest['entries']}
assert len(install_names)==14
all_names={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}
assert all_names==install_names|{'README.md','manifest.json','SHA256SUMS.txt'}
for entry in manifest['entries']:
    p=DEST/entry['path']
    assert p.is_file() and not p.is_symlink()
    d=p.read_bytes()
    assert len(d)==entry['bytes'] and sha(d)==entry['sha256']
with zipfile.ZipFile(CURRENT) as z:
    assert z.testzip() is None and set(z.namelist())=={NAME+'/'+x for x in all_names}
    for rel in all_names: assert z.read(NAME+'/'+rel)==(DEST/rel).read_bytes()

readme=(DEST/'README.md').read_text(encoding='utf-8')
before='1. 剧情主机先以原版单人方式正常创建 NG+，按游戏完整流程初始化并推进到有效检查点。原版单人启动时应使用无联机 `-mp` 参数的设置，并记录原选项以便切换回来。'
after='1. 最简单是在安装 MOD 之前，先用原版单人正常创建 NG+，按完整流程初始化并推进到有效检查点。若已经安装，先正常退出游戏，记录原有 Steam 启动参数并保留代理备份；将 **`Spider-Man.exe` 所在游戏目录中本 MOD 提供的 `winmm.dll`** 临时移到保留目录，暂用无联机 `-mp` 参数的设置，再启动原版完成创建和下述推进步骤。原版完成并正常退出后，恢复该游戏目录的代理与原启动参数，再按第 3 步用 MOD 继续。仅删掉 `-mp` 不能作为完全停用 MOD 的证据；**不要移动或修改 Windows 系统目录中的同名 DLL**。'
assert readme.count(before)==1
readme=readme.replace(before,after)
manifest['revision']='local_NGplus_solo_host_reload_verified_native_setup_clarified'
manifest['original_game_setup_note']='Prefer creating and advancing NG+ before installing the MOD. If already installed, close the game, preserve backups and Steam launch options, temporarily move only this MOD-provided winmm.dll out of the Spider-Man.exe directory, initialize and advance in the original game, close normally, then restore that proxy and prior launch settings. Removing only -mp is not proof of a fully unmodified run. Never change Windows system DLLs.'

CURRENT.rename(INTERMEDIATE)
assert sha(INTERMEDIATE.read_bytes())==EXPECTED
(DEST/'README.md').write_text(readme,encoding='utf-8')
(DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
hash_names=sorted(all_names-{'SHA256SUMS.txt'})
(DEST/'SHA256SUMS.txt').write_text(''.join(sha((DEST/rel).read_bytes())+'  '+rel+'\n' for rel in hash_names),encoding='utf-8')
for entry in manifest['entries']:
    d=(DEST/entry['path']).read_bytes()
    assert len(d)==entry['bytes'] and sha(d)==entry['sha256']
for rel in all_names:
    assert not any(x.casefold() in {'save','logs','3dmgame','序章修复调查'} for x in Path(rel).parts)
    assert not rel.lower().endswith(('.exe','.save','.log','.dmp'))
    d=(DEST/rel).read_bytes().lower()
    for word in ['xinsui','steam__']:
        assert word.encode() not in d and word.encode('utf-16-le') not in d
assert json.loads((DEST/'安装文件/SMT/Connections.json').read_text())=={'Connections':[],'ShowIp':False}
with zipfile.ZipFile(CURRENT,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for rel in sorted(all_names): z.write(DEST/rel,NAME+'/'+rel)
with zipfile.ZipFile(CURRENT) as z:
    assert z.testzip() is None and set(z.namelist())=={NAME+'/'+x for x in all_names}
    for rel in all_names: assert z.read(NAME+'/'+rel)==(DEST/rel).read_bytes()
for line in (DEST/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    digest,rel=line.split('  ',1)
    assert sha((DEST/rel).read_bytes())==digest
assert sha(INTERMEDIATE.read_bytes())==EXPECTED and sha(EARLIER.read_bytes())==EARLIER_HASH
result={
    'current_zip_name':CURRENT.name,'current_zip_bytes':CURRENT.stat().st_size,
    'current_zip_sha256':sha(CURRENT.read_bytes()),
    'intermediate_zip_name':INTERMEDIATE.name,'intermediate_zip_sha256':EXPECTED,
    'earlier_zip_name':EARLIER.name,'earlier_zip_sha256':EARLIER_HASH,
    'files':len(all_names),'install_files':len(install_names),
    'all_install_bytes_and_hashes_unchanged':True,
    'SHA256SUMS_and_zip_CRC_and_all_bytes_verified':True,
    'personal_path_and_forbidden_file_checks_passed':True,
    'empty_connection_template_verified':True,
    'game_directory_or_system_DLL_modified':False,
    'investigation_main_report_modified':False,
    'sent_externally':False,
    'scope_only_native_initialization_instructions_clarified':True,
}
OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2))
