"""Five bounded directed checks of generated literal FSM before MOS diagnostic."""
import importlib.util
import json
from pathlib import Path


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    root=Path(__file__).resolve().parent;source=load(root/'build_afc2009_mos.py','source');model=load(root/'verify_literal_gate_fsm.py','model')
    circuit=source.build();rows=[]
    for name,options in [('near',{'pattern':'SSSSS','near_round':0}),('fast_endpoint',{'pattern':'FFFFF'}),('slow_endpoint',{'pattern':'SSSSS'}),('no_FB',{'pattern':'SSSSS','nofb':True}),('stuck_lag_watchdog',{'pattern':'SSSSS','stucklag':True})]:
        result=model.run_fixture(circuit,**options);result['name']=name;rows.append(result);print(name+' PASS',flush=True)
    manifest=json.loads((root/'port_manifest.json').read_text(encoding='utf-8'))
    result={'status':'all_5_passed','source_sha256':manifest['source_sha256'],'source_MOS':circuit.transistors,'source_DFF':circuit.dffs,'fixtures':rows,'limits':'Generated literal gates + ideal edge FF; integer count frontend injected. No physical timing/CDC/counter/PLL proof.'}
    (root/'directed_fsm_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
