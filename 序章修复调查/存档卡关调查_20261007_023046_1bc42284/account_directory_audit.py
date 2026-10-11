"""Read-only Steam UID/save directory audit; redact login names and all other VDF fields."""
from pathlib import Path
import sys, re, json, datetime, hashlib, winreg
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from read_save_metadata import snapshot
STEAM=Path('D:/STEAM__/config/loginusers.vdf')
DOCS=Path("C:/Users/xinsui/Documents/Marvel's Spider-Man Remastered")
ACCOUNTS=['76561199191371037','76561199372553531']
raw=STEAM.read_text(encoding='utf-8-sig')
mostrecent=[]
for sid,body in re.findall(r'"(765\d{14})"\s*\{([^}]+)\}',raw):
    m=re.search(r'"MostRecent"\s*"([01])"',body,re.I)
    if sid in ACCOUNTS:
        mostrecent.append({'SteamID64':sid,'MostRecent':int(m[1]) if m else None})
active=None
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam\ActiveProcess') as key:
        user,_=winreg.QueryValueEx(key,'ActiveUser')
        active={'ActiveUser32':int(user),'SteamID64':str(76561197960265728+int(user))}
except OSError: pass
accounts=[]
for sid in ACCOUNTS:
    folder=DOCS/sid
    files=[]
    for f in sorted(folder.iterdir()):
        if f.is_file():
            files.append({'name':f.name,'size':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),
                          'mtime_utc':datetime.datetime.fromtimestamp(f.stat().st_mtime,datetime.timezone.utc).isoformat()})
    row={'SteamID64':sid,'path':str(folder),'files':files}
    if (folder/'slot0-s.save').exists(): row['slot0_metadata']=snapshot(folder/'slot0-s.save')
    cloud=folder/'steam_autocloud.vdf'
    if cloud.exists():
        cloudraw=cloud.read_text(encoding='utf-8-sig')
        account=re.search(r'"accountid"\s*"(\d+)"',cloudraw,re.I)
        if account:
            row['SteamAutoCloud']={'AccountID32':int(account[1]),'SteamID64':str(76561197960265728+int(account[1]))}
    accounts.append(row)
payload={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'mode':'Read-only; writes diagnostic JSON only. Login/account names, tokens and unrelated registry values are never emitted.',
    'loginusers_path':str(STEAM),'SteamID_MostRecent_only':mostrecent,'ActiveProcess':active,'account_directories':accounts,
    'evidence_limit':'ActiveProcess and MostRecent identify the Steam active account. Documents log redacts username and omits account subdirectory, so it does not by itself prove which account path this game process opened.'}
out=HERE/'Steam账户存档目录_只读审计.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('SteamID/MostRecent',json.dumps(mostrecent))
print('ActiveProcess',json.dumps(active))
for a in accounts:
    print('Account',a['SteamID64'],'FileCount',len(a['files']))
    print('SteamAutoCloud',json.dumps(a.get('SteamAutoCloud')))
    if 'slot0_metadata' in a:
        print('slot0',a['slot0_metadata']['sha256'],a['slot0_metadata']['size'])
        for obj in a['slot0_metadata']['matching_objects']: print(json.dumps(obj['fields'],ensure_ascii=False))
print('Diagnostic JSON',out)
