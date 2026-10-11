"""Pinned read-only audit: native Fisk starting save vs MOD progression to elevator lobby."""
from pathlib import Path
import datetime
import json
import struct
import diff_native_progress_153117 as parser

ROOT=Path(__file__).resolve().parent
SESSION=ROOT/'联机NG对照_20261006_155424_9e9669ed'
BEFORE=SESSION/'frozen_slot3-s.save'
AFTER=SESSION/'MOD推进后_退出前'/'slot3-s.save'
parser.decoder.EXPECTED={
    BEFORE:'a8364131cb6cc9d8aa35301e043431aefc160f688c883b721d9bfe842edd64c3',
    AFTER:'e80e50fd9758604584be33fd22c7c08e1eff82e9b9ae4f84c3f26aab8f8eee3d',
}

def raw_summary(a,ad,b,bd):
    result={}
    for tag in ('0xd0a9df','0xa806f448','0xc0174d02','0xeb364589'):
        x,y=a['sections'][tag],b['sections'][tag]
        sx=ad[x['start']:x['start']+x['size']];sy=bd[y['start']:y['start']+y['size']]
        row={'before_size':len(sx),'after_size':len(sy),'bytes_equal':sx==sy,
             'before_header_hex':sx[:32].hex(),'after_header_hex':sy[:32].hex()}
        if len(sx)==len(sy):
            ranges=[]
            for i,(v,w) in enumerate(zip(sx,sy)):
                if v!=w:
                    if ranges and ranges[-1][1]==i:ranges[-1][1]=i+1
                    else:ranges.append([i,i+1])
            row['changed_bytes']=sum(end-start for start,end in ranges)
            row['ranges']=[{'relative_start':hex(start),'relative_end':hex(end),
                           'before_hex':sx[start:end].hex(),'after_hex':sy[start:end].hex()} for start,end in ranges]
        result[tag]=row
    return result

if __name__=='__main__':
    a,ad=parser.decoder.decode(BEFORE);b,bd=parser.decoder.decode(AFTER)
    labels=parser.runtime_labels()
    am,bm=parser.MSFX(a,ad,labels),parser.MSFX(b,bd,labels)
    for item in (am,bm):
        assert len(item['objective_tables'])==2
        t=item['objective_tables']
        assert [row['words_raw'][:5] for row in t[0]['rows']]==[row['words_raw'][:5] for row in t[1]['rows']]
    payload={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'input_evidence_note':'Actual starting input is frozen_slot3-s.save/a836. The separately named MOD首次载入后_推进前 file was already e80 and is not treated as a before-progression snapshot.',
             'before':a,'after':b,'before_metadata':parser.metadata(a),'after_metadata':parser.metadata(b),
             'before_MSFX':am,'after_MSFX':bm,'section_comparison':parser.comparison(a,b),
             'raw_comparison':raw_summary(a,ad,b,bd)}
    out=ROOT/'MOD推进Fisk门厅完整差异_20261006_155424.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for label,item,md,m in [('before',a,payload['before_metadata'],am),('after',b,payload['after_metadata'],bm)]:
        print(label,item['size'],item['sha256'])
        for node in md:print(json.dumps(node,ensure_ascii=False))
        for table in m['objective_tables']:
            print('table',table['header_offset'],'stride',table['stride'],'states',[row['words_raw'][1] for row in table['rows']])
        print('Segments',[root['object'] for root in item['sections']['0x1cea6ceb']['objects'][:1]])
    print('changed sections')
    for row in payload['section_comparison']:
        if not row['bytes_equal']:print(row['tag'],row['before_size'],'->',row['after_size'],'field_changes',len(row['object_changes']))
    print('raw sections',{tag:{k:v for k,v in row.items() if k!='ranges'} for tag,row in payload['raw_comparison'].items()})
    print('Output',out)
