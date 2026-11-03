"""Read-only structural audit of generated MOS source, not electrical proof."""
import collections
import hashlib
import json
from pathlib import Path
import re


def main():
    root=Path(__file__).resolve().parent;path=root/'afc2009_mos.scs'
    manifest=json.loads((root/'port_manifest.json').read_text(encoding='utf-8'))
    text=path.read_text(encoding='utf-8');mos=[];names=[];errors=[]
    pattern=re.compile(r'^(M\w+)\s+\((\S+) (\S+) (\S+) (\S+)\) (n12|p12) w=([0-9.]+)u l=([0-9.]+)u$')
    allowed_prefix=('//','simulator lang=','subckt afc2009_mos','ends afc2009_mos')
    for lineno,line in enumerate(text.splitlines(),1):
        if not line.strip() or line.startswith(allowed_prefix):continue
        match=pattern.match(line)
        if not match:errors.append('Unsupported line {}'.format(lineno));continue
        name,d,g,s,b,model,w,l=match.groups();mos.append((name,d,g,s,b,model,float(w),float(l)));names.append(name)
        if b!=('vss' if model=='n12' else 'vdd'):errors.append('Body rail mismatch '+name)
        if float(l)!=.13:errors.append('Unexpected minimum-length choice '+name)
        if not .1<=float(w)<=24:errors.append('Unexpected width '+name)
    if len(names)!=len(set(names)):errors.append('Duplicate device name')
    if len(mos)!=manifest['transistor_count']:errors.append('Transistor count mismatch')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=manifest['source_sha256']:errors.append('Source digest mismatch')
    state=json.loads((root/'state_nodes.json').read_text(encoding='utf-8'))
    if len(state)!=manifest['DFF_count'] or len(state)!=len(set(state)):errors.append('State-node count or uniqueness mismatch')
    terminal_nodes={node for row in mos for node in row[1:5]}
    channel_nodes={node for row in mos for node in (row[1],row[3])}
    for q in state:
        if q not in channel_nodes:errors.append('Undriven state node '+q)
    for port in manifest['port_order'][6:]:
        if port not in channel_nodes:errors.append('Undriven output port '+port)
    never_ideal=['vsource','bsource','ahdl_include','isource','pll130_','verilog']
    # Comment text is irrelevant to this check; only executable lines.
    executable='\n'.join(line for line in text.splitlines() if not line.startswith('//'))
    for token in never_ideal:
        if token in executable.lower():errors.append('Non-MOS executable token '+token)
    gatefanout=collections.Counter(row[2] for row in mos)
    result={'status':'structural_pass' if not errors else 'structural_fail','source_sha256':sha,
            'MOS_count':len(mos),'DFF_count':len(state),'all_devices_body_rails_checked':True,
            'physical_output_ports_checked':manifest['port_order'][6:],'duplicate_device_names':False,
            'transistor_only':True,'all_lengths_um':sorted({row[7] for row in mos}),
            'largest_gate_terminal_fanout':gatefanout.most_common(10),
            'limits':'Counts, syntax class, output-drive presence and source digest only; not Spectre parsing, functional, timing, CDC, PVT or noise proof.',
            'errors':errors}
    (root/'structural_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
