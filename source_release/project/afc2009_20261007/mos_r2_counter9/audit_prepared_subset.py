"""Read-only source inventory for the unrun counter subset, not circuit proof."""
import hashlib
import json
from pathlib import Path
import re


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    here=Path(__file__).resolve().parent;manifest=json.loads((here/'counter9_manifest.json').read_text(encoding='utf-8'))
    source=here/'counter9_gray_cdc_mos.scs';bench=here/'counter9_gray_cdc_tb.scs'
    records=json.loads((here/'subset_logical_records.json').read_text(encoding='utf-8'))
    errors=[];devices=[]
    rx=re.compile(r'^(M\w+) \((\S+) (\S+) (\S+) (\S+)\) (n12|p12) w=([0-9.]+)u l=([0-9.]+)u$')
    for lineno,line in enumerate(source.read_text(encoding='utf-8').splitlines(),1):
        if not line or line.startswith(('//','simulator lang=','subckt ','ends ')):continue
        match=rx.match(line)
        if not match:errors.append('Not a MOS line '+str(lineno));continue
        name,d,g,s,body,model,w,l=match.groups();devices.append(name)
        if body!=('vss' if model=='n12' else 'vdd'):errors.append('Wrong body rail '+name)
        if float(l)!=.13:errors.append('Wrong length '+name)
    if len(devices)!=manifest['MOS_count'] or len(devices)!=len(set(devices)):errors.append('MOS inventory/uniqueness mismatch')
    if len(records['flops'])!=manifest['DFF_count']:errors.append('FF count mismatch')
    qnames={row['q'] for row in records['flops']}
    for prefix in ('zero_g','one_g','zero_sync1_','zero_sync2_','one_sync1_','one_sync2_'):
        if not all(prefix+str(i) in qnames for i in range(9)):errors.append('Missing9bit actual storage '+prefix)
    if sha(source)!=manifest['subset_source_sha256']:errors.append('Source hash mismatch')
    if sha(bench)!=manifest['bench_sha256']:errors.append('Bench hash mismatch')
    result={'status':'prepared_structural_checks_passed' if not errors else 'prepared_structural_checks_failed','source_sha256':sha(source),'bench_sha256':sha(bench),'MOS_count':len(devices),'DFF_count':len(records['flops']),'all_native_and_CDC_words_9bits':True,'simulation_started':False,'limits':'Source MOS syntax class, body rails, storage width, inventory and digests only. No Spectre parsing, electrical, waveform, timing or CDC validation.','errors':errors}
    (here/'prepared_subset_structural_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
