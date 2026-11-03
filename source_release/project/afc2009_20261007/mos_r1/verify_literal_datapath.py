"""Exhaustive actual generated gate graphs for8bit subtract and Graynext."""
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path


def compile_gates(c):
    names=list(dict.fromkeys(['vdd','vss']+[name for row in c.logic_ops for name in row[1:]]+[r['q'] for r in c.flop_records]+[r['d'] for r in c.flop_records]))
    index={n:i for i,n in enumerate(names)};lines=['def evaluate(v):']
    for op,out,*inputs in c.logic_ops:
        terms=['v[{}]'.format(index[n]) for n in inputs]
        expr=terms[0] if op=='INV' else '('+(' and ' if op=='NAND' else ' or ').join(terms)+')'
        lines.append(' v[{}]=int(not {})'.format(index[out],expr))
    scope={};exec(compile('\n'.join(lines),'literal_generated_gate_graph','exec'),scope)
    values=[0]*len(names);values[index['vdd']]=1
    return index,values,scope['evaluate']


def main():
    root=Path(__file__).resolve().parent;spec=importlib.util.spec_from_file_location('source',str(root/'build_afc2009_mos.py'))
    source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
    c=source.Circuit();a=['a'+str(i) for i in range(8)];b=['b'+str(i) for i in range(8)];output=c.ge_difference2(a,b)
    idx,v,ev=compile_gates(c)
    for av,bv in itertools.product(range(256),repeat=2):
        for i in range(8):v[idx[a[i]]]=(av>>i)&1;v[idx[b[i]]]=(bv>>i)&1
        ev(v);assert bool(v[idx[output]])==(av-bv>=2),(av,bv,v[idx[output]])
    c=source.Circuit();word=c.gray_counter('ref','rst','test_',initial=0)
    idx,v,ev=compile_gates(c)
    for binary in range(256):
        gray=binary^(binary>>1)
        for i,q in enumerate(word):v[idx[q]]=(gray>>i)&1
        # clock-control Boolean interlock is allowed to reach its fixed point;
        # timing and analog metastability are intentionally outside this test.
        for _ in range(4):ev(v)
        nextgray=sum(v[idx[r['d']]]<<i for i,r in enumerate(c.flop_records))
        expected=(binary+1)%256;expected^=expected>>1
        assert nextgray==expected,(binary,nextgray,expected)
    source_sha=hashlib.sha256((root/'afc2009_mos.scs').read_bytes()).hexdigest()
    result={'status':'all_passed','source_sha256':source_sha,'literal_gate_subtractor_pairs':65536,'literal_gate_native_Gray_transitions':256,'limits':'Actual source-generator gate graph in Boolean ideal logic. Does not prove physical MOS timing/native-counter propagation, CDC or metastability.'}
    (root/'literal_datapath_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
