"""Independent read-only structural audit of the authored AFC MOS source.

Structural audit cannot establish electrical timing/CDC behavior or PLL lock.
No source edits, simulator launches, network or external PDK content copies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(source,manifest,generator):
    source=Path(source).resolve()
    manifest=Path(manifest).resolve()
    generator=Path(generator).resolve()
    meta=json.loads(manifest.read_text(encoding='utf-8'))
    text=source.read_text(encoding='utf-8')
    lines=[line.split('//',1)[0].strip() for line in text.splitlines()]
    active='\n'.join(line for line in lines if line)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    violations=[]
    if digest!=meta.get('source_sha256'):
        violations.append('Current source differs from manifest SHA256.')
    if re.search(r'\bahdl_include\b|\bveriloga\b|\bbsource\b|\bvsource\b|\bisource\b',active,re.I):
        violations.append('AFC source contains a behavioral/ideal active element.')
    mos=[]
    for line in lines:
        if not line.startswith(('MN','MP')):
            continue
        match=re.fullmatch(r'(M[NP]\d+)\s+\((\S+)\s+(\S+)\s+(\S+)\s+(\S+)\)\s+(n12|p12)\s+w=([0-9.]+)u\s+l=([0-9.]+)u',line)
        if not match:
            violations.append('Unexpected MOS line: '+line[:160])
            continue
        name,d,g,s,b,model,w,l=match.groups()
        if b!=('vss' if model=='n12' else 'vdd'):
            violations.append('Body rail differs for '+name)
        if float(w)<=0 or float(l)<=0:
            violations.append('Nonpositive geometry at '+name)
        mos.append({'name':name,'drain':d,'gate':g,'source':s,'bulk':b,'model':model})
    if len(mos)!=meta.get('transistor_count'):
        violations.append('MOS count differs from generator metadata.')
    if len({item['name'] for item in mos})!=len(mos):
        violations.append('Duplicate MOS instance names.')
    header=re.search(r'(?m)^subckt\s+afc2009_mos\s+\(([^)]+)\)',active)
    ports=header.group(1).split() if header else []
    if ports!=meta.get('port_order'):
        violations.append('Subcircuit port order differs from manifest.')
    driving_nodes=set(ports)
    for item in mos:
        driving_nodes.add(item['drain']);driving_nodes.add(item['source'])
    unconnected_gates=sorted({item['gate'] for item in mos if item['gate'] not in driving_nodes})
    if unconnected_gates:
        violations.append('Gate nodes have no MOS terminal or external-port connection.')
    generator_text=generator.read_text(encoding='utf-8')
    watchdog_present=('measure_watchdog' in active and 'measure_watchdog' in generator_text)
    if not watchdog_present:
        violations.append('Independent MEASURE watchdog not found in generated source.')
    return {'structural_checks_pass':not violations,'violations':violations,
        'source':str(source),'source_sha256':digest,'manifest':str(manifest),
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'generator':str(generator),'generator_sha256':hashlib.sha256(generator.read_bytes()).hexdigest(),
        'transistor_count':len(mos),'DFF_count_declared':meta.get('DFF_count'),
        'port_order':ports,'all_active_devices_are_n12_p12_MOS':True,
        'all_body_rails_checked':True,'unconnected_gate_nodes':unconnected_gates,
        'independent_measure_watchdog_present':watchdog_present,
        'source_equivalence_or_synthesis_verified':False,'electrical_timing_verified':False,
        'CDC_metastability_verified':False,'physical_PLL_lock_verified':False,
        'physical_noise_jitter_verified':False,'simulator_started':False,
        'scope':'Structural source/manifest integrity only. MOS device presence does not '
            'prove counter, phase-bracket, binary search, handoff or timing correctness.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent.parent
    parser.add_argument('--source',type=Path,default=root/'mos/afc2009_mos.scs')
    parser.add_argument('--manifest',type=Path,default=root/'mos/port_manifest.json')
    parser.add_argument('--generator',type=Path,default=root/'mos/build_afc2009_mos.py')
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('source_structural_audit.json'))
    args=parser.parse_args()
    result=audit(args.source,args.manifest,args.generator)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ['structural_checks_pass','source_sha256','transistor_count','violations']}))
    return 0 if result['structural_checks_pass'] else 2


if __name__=='__main__':
    raise SystemExit(main())
