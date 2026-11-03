"""Synthetic reader-wrapper and literal source checks; no physical claims."""
from __future__ import print_function
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile


def module(path,name):
    spec = importlib.util.spec_from_file_location(name,str(path))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def fixture(path,frequency=3.2e9,enable=True,reset=True,code=16):
    # Small synthetic vectors exercise the monitor; they are not transistor
    # waveforms, simulator results, or evidence of real acquisition.
    with path.open('w',encoding='utf-8',newline='\n') as handle:
        handle.write('VALUE\n')
        for i in range(30001):
            t = i*40e-12
            carrier = 0.1*math.sin(2*math.pi*frequency*t)
            clock = 0.6+0.6*math.sin(2*math.pi*100e6*(t-10e-9))
            enabled = enable and t>=300e-9
            values = {'time':t,'out0':0.9+carrier,'out180':0.9-carrier,
                'ref':clock,'fb':clock,'ctrl':0.6,'filter_mid':0.6,
                'vdd':1.2,'VDD:p':-1/300.0,'VDDIG:p':-0.0005,
                'VDDCP:p':-0.0003,'enable':1.2 if enabled else 0,
                'rst':0 if reset and t>=300e-9 else 1.2,
                'up':0,'dn':0,'div_rst':0}
            active_code = code if t>=700e-9 else 16
            for bit in range(5):
                values['s'+str(bit)] = 1.2 if active_code&(1<<bit) else 0
            for name,value in values.items():
                handle.write('"{}" {:.17g}\n'.format(name,value))
        handle.write('END\n')


def main():
    here = Path(__file__).resolve().parent
    prepare = module(here/'prepare_counterfactual_v1.py','prepare_counterfactual')
    measure = module(here/'measure_counterfactual_v1.py','measure_counterfactual')
    record = json.loads((here/'benches/control_manifest_v1.json').read_text(encoding='utf-8'))[0]
    bench = here/'benches'/(record['name']+'.scs')
    base = here.parents[2]/prepare.BASE_RELATIVE
    assert prepare.sha(base) == prepare.BASE_SHA
    text = bench.read_text(encoding='utf-8')
    original = base.read_bytes().decode('utf-8').replace('\r\n','\n')
    # Reverse only the declared edits and remove the prepended provenance header.
    for change in reversed(record['literal_replacements']):
        assert text.count(change['after']) == 1
        text = text.replace(change['after'],change['before'])
    assert text.endswith(original), 'Unexpected undeclared physical-source change.'
    assert text.count(original) == 1
    config = json.loads((here/'signal_map_v1.json').read_text(encoding='utf-8'))
    assert not {'done','fail','hold','afc_enable'}&set(config['digitals'])
    trials = []
    with tempfile.TemporaryDirectory(prefix='off_monitor_fixture_',dir=str(here)) as temporary:
        temp = Path(temporary)
        for label,frequency,enable,reset,code,locked,valid in [
            ('ideal_locked',3.2e9,True,True,16,True,True),
            ('off_frequency',3.0e9,True,True,16,False,True),
            ('missing_enable',3.2e9,False,True,16,False,False),
            ('missing_reset_release',3.2e9,True,False,16,True,False),
            ('changed_fixed_code',3.2e9,True,True,17,True,False),
        ]:
            raw = temp/(label+'.tran')
            fixture(raw,frequency,enable,reset,code)
            result = measure.measure(raw,bench,record,config,128,here)
            assert result['loop']['locked'] == locked, label
            assert (not result['violations']) == valid, label
            assert result['scope']['afc_success_evaluated'] is False
            power = result['power']['enable_to_observation_end']
            if enable:
                total = power['branches']['total_current']
                assert abs(total['average_power_W']-.004) < 1e-12
                assert abs(total['energy_J']-.004*power['duration_s']) < 1e-18
                assert 'afc_current' not in power['branches']
                assert 'total_already_includes_AFC' not in power
            if not locked:
                assert result['power']['enable_to_lock'] is None
                assert result['power']['locked_tail'] is None
            trials.append({'fixture':label,'expected_lock':locked,
                'expected_valid_measurement':valid,'pass':True})
        bad = dict(record,bench_sha256='0'*64)
        try:
            measure.measure(raw,bench,bad,config,128,here)
            raise AssertionError('Bench SHA rejection did not fire.')
        except ValueError as error:
            assert 'SHA mismatch' in str(error)
        trials.append({'fixture':'bench_SHA_mismatch_rejected','pass':True})
    result = {'status':'all_authoring_and_synthetic_wrapper_checks_pass',
        'physical_simulator_launched':False,'physical_electrical_pass':None,
        'bench_sha256':prepare.sha(bench), 'baseline_sha256':prepare.sha(base),
        'frozen_reader_sha256':prepare.sha(here/'frozen_reader_v1.py'),
        'literal_source_reverse_check':True,
        'no_manufactured_afc_signals':True,'synthetic_fixtures':trials,
        'scope':'Only source-preservation and read-only-wrapper behavior. These '
                'synthetic waves are not physical AFC-off acquisition evidence.'}
    path = here/'authoring_checks_v1.json'
    encoded = (json.dumps(result,indent=2)+'\n').encode('utf-8')
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError('Different prior authoring check exists; use a new version.')
    path.write_bytes(encoded)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
