"""File-only hook triage: no process access, no game/save mutation."""
import json, struct, bisect, re
from pathlib import Path
import pefile

ROOT=Path(__file__).resolve().parent
GAME=Path("D:/STEAM__/steamapps/common/Marvel's Spider-Man Remastered/Spider-Man.exe")
CORE=GAME.parent/'SMT/Scripts/smt.dll'

def image(path):
    pe=pefile.PE(str(path), fast_load=True)
    sections=[]
    with path.open('rb') as f:
        for s in pe.sections:
            f.seek(s.PointerToRawData)
            sections.append((s.VirtualAddress, f.read(s.SizeOfRawData), s.Name.decode('ascii').rstrip('\0')))
    def data(rva,n=128):
        for start,blob,_ in sections:
            if start<=rva<start+len(blob): return blob[rva-start:rva-start+n]
        return b''
    pd=next(blob for start,blob,name in sections if name=='.pdata')
    rows=[struct.unpack_from('<III',pd,i)[:2] for i in range(0,len(pd)-11,12)]
    rows=sorted((a,b) for a,b in rows if a and b>a)
    starts=[a for a,b in rows]
    def fn(rva):
        i=bisect.bisect_right(starts,rva)-1
        if i>=0 and rows[i][0]<=rva<rows[i][1]: return rows[i]
        return rva,rva+0x60
    def refs(a,b):
        blob=data(a,b-a); out=[]
        for i in range(len(blob)-7):
            # Common 64-bit RIP-relative lea/mov forms; candidates, not a decoder.
            if blob[i] in range(0x48,0x50) and blob[i+1] in (0x8D,0x8B) and (blob[i+2]&0xC7)==5:
                t=a+i+7+struct.unpack_from('<i',blob,i+3)[0]
                val=data(t,128).split(b'\0')[0]
                if len(val)>=5 and all(32<=c<127 for c in val):
                    out.append({'rva':hex(a+i),'target':hex(t),'text':val.decode('ascii')})
        return out
    return data,fn,refs,sections

def main():
    gd,gf,gr,gs=image(GAME)
    cd,cf,cr,cs=image(CORE)
    hooks=json.loads((ROOT/'已加载Hook映射.json').read_text(encoding='utf8'))
    out=[]
    for h in hooks:
        ga=int(h['game_rva'],16); a,b=gf(ga)
        item={**h,'game_function':[hex(a),hex(b)],'game_string_candidates':gr(a,b)}
        if h.get('target_module')=='smt.dll':
            ca=int(h['target_rva'],16); x,y=cf(ca)
            item['core_function']=[hex(x),hex(y)]
            item['core_string_candidates']=cr(x,y)
            item['core_first_bytes']=cd(ca,32).hex(' ')
        out.append(item)
    (ROOT/'检查点Hook文件审计_20261006.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    for row in out:
        if row['game_string_candidates'] or row.get('core_string_candidates'):
            print(json.dumps(row,ensure_ascii=False))
    names=[b'CHK: Autocheckpointing ON',b'CHK: Autocheckpointing OFF',b'CHK: Autocheckpoint %s for %s',b'CHK: Checkpoint %s for objectives with no checkpoint.',b'CheckpointManager',b'AutoCheckpoint',b'LastPosition',b'CurrentCheckpoint',b'AutoSaveOn',b'AutoSaveOff',b'OnAutoSaveOn',b'OnAutoSaveOff']
    targets={}
    for start,blob,name in gs:
        if name=='.text': continue
        for target in names:
            for match in re.finditer(re.escape(target)+b'\0',blob):
                targets[start+match.start()]=target.decode('ascii')
    xrefs=[]
    for start,blob,name in gs:
        if name!='.text': continue
        for match in re.finditer(rb'[\x48-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....',blob,re.DOTALL):
            loc=start+match.start()
            target=loc+7+struct.unpack_from('<i',match.group(),3)[0]
            if target in targets:
                a,b=gf(loc)
                matched=[h['game_rva'] for h in hooks if a<=int(h['game_rva'],16)<b]
                xrefs.append({'ref':hex(loc),'target':hex(target),'text':targets[target],'function':[hex(a),hex(b)],'known_hook_sites':matched,'other_strings':gr(a,b)})
    (ROOT/'检查点字符串引用_20261006.json').write_text(json.dumps(xrefs,ensure_ascii=False,indent=2),encoding='utf8')
    print('CHECKPOINT_STRING_XREFS')
    for row in xrefs: print(json.dumps(row,ensure_ascii=False))
    rtti=[]
    hookmap={int(h['game_rva'],16):h for h in hooks}
    text_ranges=[(s,s+len(blob)) for s,blob,name in gs if name=='.text']
    for start,blob,name in gs:
        for typename in (b'.?AVAutoCheckpoint@@',b'.?AVAutoCheckpointAction@@',b'.?AVCheckpointAction@@',b'.?AVCheckpointQueryAction@@'):
            pos=blob.find(typename+b'\0')
            if pos<0: continue
            desc=start+pos-16
            for rs,rd,rn in gs:
                for match in re.finditer(re.escape(struct.pack('<I',desc)),rd):
                    col=rs+match.start()-12
                    fields=gd(col,24)
                    if len(fields)!=24: continue
                    sig,offset,cdOffset,pType,pClass,pSelf=struct.unpack('<IIIIII',fields)
                    if sig!=1 or pType!=desc or pSelf!=col: continue
                    for vs,vd,vn in gs:
                        for vm in re.finditer(re.escape(struct.pack('<Q',0x140000000+col)),vd):
                            vtable=vs+vm.start()+8; entries=[]
                            for k in range(120):
                                p=struct.unpack('<Q',gd(vtable+k*8,8))[0]-0x140000000
                                if not any(a<=p<b for a,b in text_ranges): break
                                entries.append({'offset':hex(k*8),'function':hex(p),'hook':hookmap.get(p)})
                            rtti.append({'class':typename.decode(),'descriptor':hex(desc),'col':hex(col),'object_offset':offset,'vtable':hex(vtable),'entries':entries})
    (ROOT/'检查点RTTI函数表_20261006.json').write_text(json.dumps(rtti,ensure_ascii=False,indent=2),encoding='utf8')
    print('CHECKPOINT_RTTI')
    for row in rtti:
        print(json.dumps({k:v for k,v in row.items() if k!='entries'},ensure_ascii=False),'methods',len(row['entries']),'hooks',[(v['function'],v['hook']) for v in row['entries'] if v['hook']])

if __name__=='__main__': main()
