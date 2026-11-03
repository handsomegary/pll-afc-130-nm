"""Read-only direct acquisition audit for AFC-off v1; Python 3.6+, stdlib.

Uses a byte-frozen saved-vector reader/engineering-lock/power algorithm shared
with the AFC-on analysis. Only real enable/reset/bank/clock/supply signals are
read. No fake AFC Done, Fail, or success qualification is used.
"""
from __future__ import print_function
import argparse
import bisect
import hashlib
import importlib.util
import json
from pathlib import Path

READER_SHA = 'b2898c42d28918f00b095e763427f4bacae7cb08e2b6c4ac4d551b328c214d10'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_reader(here):
    path = here/'frozen_reader_v1.py'
    if sha(path) != READER_SHA:
        raise ValueError('Frozen read-only algorithm SHA mismatch.')
    spec = importlib.util.spec_from_file_location('afc_off_frozen_reader_v1',str(path))
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def direct_power(reader,data,begin,end):
    result = reader.power_metrics(data,begin,end)
    if result is None:
        return result
    # Shared on-analysis metadata assumes an AFC diagnostic branch. This control
    # has no such branch; numerical VDD integration is exactly the same.
    result.pop('total_already_includes_AFC',None)
    result['AFC_present'] = False
    result['total_already_includes_digital_and_cp'] = True
    result['scope'] = ('Saved instantaneous VDD integral. Digital and CP branch '
        'currents are diagnostic and are not added again. No AFC branch exists. '
        'Ideal external REF and unspecified physical bias-generator implementations '
        'are excluded; this is not an exact matched loading/FoM comparison.')
    return result


def measure(raw,bench,record,config,memory_mib,here):
    before = sha(bench)
    if before != record['bench_sha256']:
        raise ValueError('Exact counterfactual bench SHA mismatch.')
    reader = load_reader(here)
    data,digital,words,provenance = reader.read_saved_vectors(raw,config,memory_mib)
    enable_events = digital.get('fine_enable',{}).get('rising',[])
    fine = enable_events[0] if enable_events else None
    reset_events = digital.get('pfd_reset',{}).get('falling',[])
    reset_release = reset_events[0] if reset_events else None
    code = words.get('code',[])
    violations = []
    if fine is None:
        violations.append('No saved physical fine-loop enable edge.')
        lock = {'locked':False,'lock_time_s':None,
                'reason':'Physical enable edge unavailable; no AFC signal is substituted.'}
    else:
        lock = reader.engineering_lock(data,fine,config)
    if reset_release is None:
        violations.append('No saved physical PFD-reset release.')
    if not code:
        violations.append('No saved bank-code word.')
    elif any(value != 16 for time,value in code):
        violations.append('The saved fixed-code word is not continuously16.')
    if fine is not None and reset_release is not None and abs(fine-reset_release)>1e-9:
        violations.append('PFD reset release and physical enable differ by more than1ns.')
    if sha(bench) != before:
        raise ValueError('Counterfactual bench changed while reading raw.')
    end = data['time'][-1]
    begin = data['time'][0]
    tail = max(fine if fine is not None else begin,end-500e-9)
    control = {}
    for name in ['ctrl','filter_mid']:
        if name not in data:
            violations.append('Missing LPF voltage: '+name)
            continue
        wave = data[name]
        index = bisect.bisect_left(data['time'],tail)
        control[name] = {'first_saved_V':wave[0],
            'at_enable_V':reader.interpolate(data['time'],wave,fine) if fine is not None else None,
            'final_saved_V':wave[-1],
            'observation_min_V':min(wave),'observation_max_V':max(wave),
            'last500ns_min_V':min(wave[index:]),'last500ns_max_V':max(wave[index:])}
    lock_time = lock.get('lock_time_s')
    return {
        'name':record['name'], 'comparison_role':'AFC-off fixed-code16 acquisition control',
        'status':'measured' if not violations else 'measurement_incomplete_or_inconsistent',
        'bench':str(bench.resolve()),'bench_sha256':before,
        'physical_baseline_sha256':record['physical_baseline_sha256'],
        'frozen_reader_sha256':READER_SHA, 'provenance':provenance,
        'observation_interval_s':[begin,end], 'fine_enable_time_s':fine,
        'pfd_reset_release_time_s':reset_release, 'code_word_ledger':code,
        'initial_LPF_IC_V':0.6,'measured_LPF_voltages':control,
        'loop':lock,'violations':violations,
        'power':{'enable_to_observation_end':direct_power(reader,data,fine,end),
            'enable_to_lock':direct_power(reader,data,fine,lock_time),
            'last500ns_observation':direct_power(reader,data,tail,end),
            'locked_tail':direct_power(reader,data,tail,end) if lock.get('locked') else None},
        'scope':{'afc_success_evaluated':False,'afc_present':False,
            'bank_driver':'Five original ideal DC voltage sources',
            'capture_interpretation':'If not locked, only failure to capture in this '
                'saved observation window is supported. No infinite-time claim.',
            'power_comparison':'Active AFC circuitry, clamp and CP enable gates are absent; '
                'bank-output loading is different. No exact matched power/FoM claim.',
            'noise':'No stochastic noise or physical jitter/FoM was evaluated.'},
        'source_unchanged_during_measurement':True,
    }


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--manifest', type=Path, default=here/'benches/control_manifest_v1.json')
    parser.add_argument('--bench', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--memory-mib', type=int, choices=[128,256,512], default=256)
    args = parser.parse_args()
    records = json.loads(args.manifest.read_text(encoding='utf-8'))
    if len(records) != 1 or records[0]['name'] != 'pll_afc_off_code16_ctrl600_ref10000_4p_6500n_v1':
        raise ValueError('Expected the single immutable AFC-off v1 control.')
    record = records[0]
    bench = args.bench if args.bench is not None else Path(record['path'])
    config = json.loads((here/'signal_map_v1.json').read_text(encoding='utf-8'))
    result = measure(args.raw,bench,record,config,args.memory_mib,here)
    encoded = (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists() and args.output.read_bytes() != encoded:
        raise ValueError('Refuse to overwrite a different measurement; use a new output filename.')
    args.output.write_bytes(encoded)
    print(json.dumps({'name':result['name'],'status':result['status'],
        'locked_within_observation':result['loop']['locked'],
        'final_frequency_Hz':result['loop'].get('final_frequency_Hz'),
        'violations':result['violations'],'output':str(args.output)}))
    return 0 if not result['violations'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
