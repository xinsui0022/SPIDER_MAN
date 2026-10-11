"""Read-only three-way audit of native initialized / advanced and MOD advanced saves."""
from pathlib import Path
import datetime
import json
import struct
import diff_reload_save as decoder
from read_save_metadata import select

ROOT = Path(__file__).resolve().parent
PATHS = {
    'native_initialized': ROOT/'NG初始化测试档_20261006'/'slot3-s.save',
    'native_fisk_atrium': ROOT/'同档对照_20261006_153117_66d1c1ab'/'原版推进后_退出前'/'slot3-s.save',
    'MOD_second_stop_finish': ROOT/'NG_reload_reload_20261006.dat1',
}
decoder.EXPECTED = {
    PATHS['native_initialized']: 'ae64678c0e02ccba5b2721770af3d08cdbc0810866421232349e09e97835e7d5',
    PATHS['native_fisk_atrium']: 'a8364131cb6cc9d8aa35301e043431aefc160f688c883b721d9bfe842edd64c3',
    PATHS['MOD_second_stop_finish']: 'de29a47bfd6d4925069523e9f940eb1ecac0ebb6c9adac9962e9c0f364b7a0b7',
}
RUNTIME_LOG = ROOT/'记录'/'20261006T073309_889296Z.jsonl'

def runtime_labels():
    labels = {}
    for line in RUNTIME_LOG.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        for mission in record.get('data', {}).get('missions', []):
            if mission.get('objectives'):
                labels[int(mission['mission_id_raw'],16)] = {
                    'name': mission['mission_name_raw'], 'index': mission['index'],
                    'objectives': [row['name_raw'] for row in mission['objectives']]}
    return labels

def metadata(decoded):
    output = []
    for tag, section in decoded['sections'].items():
        for root in section['objects']:
            fields = select(root['object'])
            if fields:
                output.append({'section_tag': tag, 'relative_offset': root['relative_offset'], 'fields': fields})
    return output

def MSFX(decoded, data, labels):
    section = decoded['sections']['0xeb364589']
    raw = data[section['start']:section['start']+section['size']]
    assert raw[:4] == b'XFSM'  # Little-endian magic printed as MSFX by a u32 viewer.
    count = struct.unpack_from('<I',raw,9)[0]
    assert count == 251
    mission_states = []
    for i in range(count):
        at = 13+i*14
        h, state, word, byte0, byte1 = struct.unpack_from('<3I2B',raw,at)
        row = {'index':i,'mission_hash':hex(h),'state_raw':state,'word_raw':word,'bytes_raw':[byte0,byte1]}
        if h in labels:
            row['runtime_name'] = labels[h]['name']
            assert labels[h]['index'] == i
        mission_states.append(row)
    target_count_offset = 13+count*14
    tables = []
    for h,label in labels.items():
        signature=struct.pack('<2I',h,len(label['objectives']))
        at=0
        while True:
            at=raw.find(signature,at)
            if at<0:break
            for stride in (20,24):
                if at+8+len(label['objectives'])*stride>len(raw):continue
                words=[list(struct.unpack_from('<'+'I'*(stride//4),raw,at+8+i*stride)) for i in range(len(label['objectives']))]
                if any(not (0<=row[1]<=3 and 0<=row[2]<=3) or row[0]==0 for row in words):continue
                tables.append({'mission_hash':hex(h),'runtime_name':label['name'],'header_offset':hex(at),'stride':stride,
                    'rows':[{'runtime_name':name,'objective_hash':hex(row[0]),'words_raw':row} for name,row in zip(label['objectives'],words)]})
            at+=1
    return {'section_size':len(raw),'header_hex':raw[:13].hex(),'global_mission_states':mission_states,
            'first_objective_table_count_offset':hex(target_count_offset),
            'first_objective_table_count':struct.unpack_from('<I',raw,target_count_offset)[0],
            'objective_tables':tables,'raw_hex':raw.hex()}

def comparison(a,b):
    output=[]
    for tag in a['sections']:
        x,y=a['sections'][tag],b['sections'][tag]
        output.append({'tag':tag,'before_size':x['size'],'after_size':y['size'],
                       'bytes_equal':x['sha256']==y['sha256'],
                       'object_changes':decoder.diff(x['objects'],y['objects'])})
    return output

if __name__ == '__main__':
    labels=runtime_labels()
    items={}
    for key,path in PATHS.items():
        decoded,data=decoder.decode(path)
        items[key]={'decoded':decoded,'metadata':metadata(decoded),'MSFX':MSFX(decoded,data,labels)}
    payload={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runtime_label_source':str(RUNTIME_LOG),
             'stage_difference_note':'native_fisk_atrium is later than MOD_second_stop_finish; not a same-stage causal comparison',
             'files':items,
             'native_initialized_to_native_fisk':comparison(items['native_initialized']['decoded'],items['native_fisk_atrium']['decoded']),
             'MOD_second_stop_finish_to_native_fisk':comparison(items['MOD_second_stop_finish']['decoded'],items['native_fisk_atrium']['decoded'])}
    out=ROOT/'原版正常推进至Fisk三档差异_20261006_153117.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,item in items.items():
        print(name,item['decoded']['size'],item['decoded']['sha256'])
        for row in item['metadata']:print(json.dumps(row,ensure_ascii=False))
        print('known global mission states',[row for row in item['MSFX']['global_mission_states'] if 'runtime_name' in row])
        for table in item['MSFX']['objective_tables']:
            print('table',table['runtime_name'],table['header_offset'],'stride',table['stride'],'states',[row['words_raw'][1] for row in table['rows']])
        seg=item['decoded']['sections']['0x1cea6ceb']['objects'][0]['object']
        print('Segments',json.dumps(seg,ensure_ascii=False)[:3500])
    print('Output',out)
