"""Read-only mapping of guest crash RVAs onto the pinned local Spider-Man build."""
from pathlib import Path
import datetime
import hashlib
import json
import struct
import subprocess
import pefile

ROOT=Path(__file__).resolve().parent
GAME=Path(r"D:\STEAM__\steamapps\common\Marvel's Spider-Man Remastered\Spider-Man.exe")
CORE=GAME.parent/'SMT'/'Scripts'/'smt.dll'
GAME_SHA='e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1'
CORE_SHA='b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7'
FAULT=0x1cbbd80
STACK=[FAULT,0x1cb8a9a,0x18e27aa,0x188f27f,0x18963bd]

if __name__=='__main__':
    data=GAME.read_bytes()
    assert hashlib.sha256(data).hexdigest()==GAME_SHA
    assert hashlib.sha256(CORE.read_bytes()).hexdigest()==CORE_SHA
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    def at(rva):return pe.get_offset_from_rva(rva)
    fault_bytes=data[at(FAULT):at(FAULT)+12]
    assert fault_bytes==bytes.fromhex('c704250000000006007a88c3')
    strings={}
    for rva in (0x4e58ab0,0x3d0d9e8,0x3d0da0c,0x4f36400,0x4f36418,0x4f36438,0x4f36450,0x4f36478):
        pos=at(rva);strings[hex(rva)]=data[pos:data.find(b'\x00',pos)].decode('utf-8',errors='replace')
    vt=0x4f35e38
    slots={hex(slot):hex(struct.unpack_from('<Q',data,at(vt+slot))[0]-base) for slot in range(0x178,0x1b0,8)}
    assert slots['0x178']=='0x1cb8720' and slots['0x188']==hex(FAULT)
    colptr=struct.unpack_from('<Q',data,at(vt-8))[0]
    col=struct.unpack_from('<6I',data,at(colptr-base));assert col[0]==1 and col[5]==colptr-base
    pos=at(col[3])+16;rtti=data[pos:data.find(b'\x00',pos)].decode()
    assert rtti=='.?AVNxD3DImpl@nx@@'
    old=json.loads((ROOT/'已加载代码差异.json').read_text(encoding='utf-8'))
    assert old['game_sha256']==GAME_SHA
    exact_changed=set()
    for row in old['patch_regions']:
        original=bytes.fromhex(row['original']);loaded=bytes.fromhex(row['loaded']);assert len(original)==len(loaded)
        rva=int(row['context_rva'],16)
        exact_changed.update(rva+i for i,(a,b) in enumerate(zip(original,loaded)) if a!=b)
    contexts={'fault_leaf':(0x1cbbd80,0x1cbbd8c),'HRESULT_handler':(0x1cb8720,0x1cb8aed),
              'upper_GetDeviceRemovedReason_context':(0x18e2500,0x18e27da),
              '188f27f_context':(0x188ee00,0x188f600),'18963bd_context':(0x1895f80,0x1896990)}
    overlaps={name:[hex(x) for x in sorted(exact_changed) if start<=x<end] for name,(start,end) in contexts.items()}
    windows=[('fault_leaf',0x1cbbd80,0x1cbbd8c),('HRESULT_handler',0x1cb8720,0x1cb8aed),
             ('device_reason_caller',0x18e2700,0x18e27da),('188f27f_caller',0x188f1f7,0x188f2bd),
             ('18963bd_caller',0x18962c0,0x1896400)]
    assembly={}
    objdump=r'C:\TDM-GCC-64\bin\objdump.exe'
    for name,start,end in windows:
        completed=subprocess.run([objdump,'-d','-M','intel','--start-address='+hex(base+start),'--stop-address='+hex(base+end),str(GAME)],capture_output=True,text=True,check=True)
        assembly[name]=completed.stdout
    report={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope':'Local pinned static image and prior local text-hook snapshot; guest dump version/register/loaded-byte validation is a separate audit.',
            'game_sha256':GAME_SHA,'smt_sha256':CORE_SHA,'fault_rva':hex(FAULT),'stack_rvas':[hex(x) for x in STACK],
            'fault_bytes':fault_bytes.hex(),'fault_semantics':'Explicit null write of 0x887A0006, then ret',
            'NxD3DImpl_RTTI':rtti,'vtable_rva':hex(vt),'vtable_slots':slots,'literal_strings':strings,
            'prior_hook_snapshot':{'pid':old['pid'],'reported_difference_bytes':old['difference_bytes'],
                'represented_unique_changed_bytes':len(exact_changed),'patch_region_count':len(old['patch_regions']),
                'context_overlaps':overlaps,'exact_stack_rva_changes':{hex(x):x in exact_changed for x in STACK}},
            'disassembly':assembly,
            'official_hresult_reference':'https://learn.microsoft.com/windows/win32/direct3ddxgi/dxgi-error',
            'HRESULT_code':'0x887A0006','HRESULT_name':'DXGI_ERROR_DEVICE_HUNG',
            'separate_run_note':'The 22:31 NIXXES launch and 22:35 GraphicsPipelineState/CreateHeap 0x8007000E messages are later than the 22:27 dump and are not merged into its causal chain.'}
    out=ROOT/'客机崩溃静态路径_20261006_222702.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Pinned local binary hashes PASS')
    print('Fault:',report['fault_semantics'])
    print('RTTI:',rtti,'vtable:',hex(vt),'slots:',slots)
    print('Strings:',strings)
    print('Prior mapped changed bytes:',len(exact_changed),'reported:',old['difference_bytes'],'overlaps:',overlaps)
    print('Output:',out)
