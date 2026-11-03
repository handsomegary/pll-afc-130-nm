"""Author one immutable AFC-off acquisition control; Python 3.6+, local only.

This script never starts Spectre or manages a Cadence/VM session. The guarded
physical fine-loop source remains unchanged. Generated include paths and the
runner manifest refer to the owned guest project, so the directory can be
uploaded without rewriting the generated bench.
"""
from __future__ import print_function
import argparse
import hashlib
import json
from pathlib import Path
import re

BASE_SHA = 'cc44e0bb56a8de35ff75d1780b99bc790311ec097f33556fa9046eb4bb0e8f44'
READER_SHA = 'b2898c42d28918f00b095e763427f4bacae7cb08e2b6c4ac4d551b328c214d10'
GUEST_PROJECT = '@PROJECT_ROOT@'
BASE_RELATIVE = 'pll_full/digital/benches/pll_stage3_physical_code28_ctrl835938_cpdrain_bounded2p.scs'
OWN_RELATIVE = 'afc2009_20261007/integration/counterfactual_off'
NAME = 'pll_afc_off_code16_ctrl600_ref10000_4p_6500n_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_immutable(path, data):
    path = Path(path)
    if isinstance(data, str):
        data = data.encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Refuse to replace a different existing version: '+str(path))
    else:
        path.write_bytes(data)


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=here.parents[2]/BASE_RELATIVE)
    parser.add_argument('--reader', type=Path,
                        default=here.parents[1]/'verification/measure_afc2009.py')
    args = parser.parse_args()
    if sha(args.baseline) != BASE_SHA:
        raise ValueError('Preserved physical fine-loop baseline SHA mismatch.')
    if sha(args.reader) != READER_SHA:
        raise ValueError('Shared saved-vector reader changed; author a new control version.')
    original = args.baseline.read_bytes().decode('utf-8')
    source = original.replace('\r\n', '\n')
    changes = [
        ('parameters CODE0=0 CODE1=0 CODE2=1 CODE3=1 CODE4=1',
         'parameters CODE0=0 CODE1=0 CODE2=0 CODE3=0 CODE4=1'),
        ('VRSTP (rst 0) vsource type=pwl wave=[0 1.2 300n 1.2 300.1n 0]',
         'VRSTP (rst 0) vsource type=pwl wave=[0 1.2 300n 1.2 300.02n 0]'),
        ('VEN (enable 0) vsource type=pwl wave=[0 0 300n 0 300.1n 1.2]',
         'VEN (enable 0) vsource type=pwl wave=[0 0 300n 0 300.02n 1.2]'),
        ('ic ctrl=0.8359375 filter_mid=0.8359375 out0=0.935 out180=0.933 out90=0.934 out270=0.934',
         'ic ctrl=0.6 filter_mid=0.6 out0=0.935 out180=0.933 out90=0.934 out270=0.934'),
        ('tran tran stop=2e-06 maxstep=2p errpreset=moderate skipdc=no strobeperiod=10p strobeoutput=strobeonly',
         'save s0 s1 s2 s3 s4\n'
         'tran tran stop=6.5e-06 maxstep=4p errpreset=moderate skipdc=no strobeperiod=40p strobeoutput=strobeonly'),
    ]
    for before, after in changes:
        if source.count(before) != 1:
            raise ValueError('Expected exactly one guarded replacement: '+before)
        source = source.replace(before, after)
    header = (
        '// AFC-off fixed-code acquisition counterfactual, version 1.\n'
        '// Same preserved physical fine-loop active devices as the guarded base.\n'
        '// Coarse code16, LPF IC=.6V, PFD release300ns, REF100MHz/delay10ns.\n'
        '// No AFC/clamp/CP enable gates. LPF .6V is an IC, not a held voltage.\n'
        '// Ideal CODE sources differ from actual MOS AFC bank-output impedance.\n'
        '// A 6.5us observation cannot prove eventual capture impossible.\n\n')
    source = header+source
    if 'ahdl_include' in source or re.search(r'(?m)^XAFC\s|^VCTRL\s', source):
        raise ValueError('Unexpected behavioral/AFC/ideal-control-voltage source.')
    if len(re.findall(r'(?m)^VS[0-4]\s', source)) != 5:
        raise ValueError('All five original ideal coarse-code sources must remain.')
    # Apart from the listed parameter/stimulus/IC/observation edits, the original
    # active-device instances, subcircuit definitions, and includes are literal.
    bench = here/'benches'/(NAME+'.scs')
    write_immutable(bench, source)
    write_immutable(here/'frozen_reader_v1.py', args.reader.read_bytes())
    record = {
        'name':NAME,
        'path':GUEST_PROJECT+'/'+OWN_RELATIVE+'/benches/'+NAME+'.scs',
        'bench_sha256':sha(bench),
        'physical_baseline_sha256':BASE_SHA,
        'baseline_path':GUEST_PROJECT+'/'+BASE_RELATIVE,
        'frozen_reader_sha256':READER_SHA,
        'target_Hz':3.2e9, 'reference_Hz':100e6,
        'temperature_C':25, 'vdd_V':1.2, 'fixed_code':16,
        'initial_ctrl_V':0.6, 'initial_filter_mid_V':0.6,
        'duration_s':6.5e-6, 'maxstep_s':4e-12, 'strobeperiod_s':40e-12,
        'enable_midpoint_s':300.01e-9, 'ref_delay_s':10e-9,
        'physical_active_blocks':['VCO','AC/self-bias RX','5TG divider','PFD','drain CP'],
        'behavior_control_blocks':[],
        'external_ideal_elements':['100MHz REF','13.5594uA IREF','five DC CODE drivers',
                                   'R/C elements','LPF ICs','oscillator IC startup seed'],
        'status':'prepared_unverified',
        'interpretation':'Direct physical fine-loop capture from fixed code16. No AFC '
            'Done/Fail/success is manufactured. No lock in this window means only '
            'not captured within the measured6.5us.',
        'comparison_differences':['AFC-on drives CODE using MOS outputs; this control uses '
            'the five original ideal DC voltage sources.',
            'AFC-on adds AFC logic, two-node MOS clamp, clamp reference and CP enable gates; '
            'this control retains the guarded original fine-loop topology.',
            'AFC-on physically holds both LPF nodes near half-supply before handoff; this '
            'control only specifies the same nominal initial IC. Actual enable-time '
            'LPF voltages must be measured.',
            'This control consumes no AFC supply power. Power is a bounded whole-PLL '
            'observation, not an exact matched loading or FoM improvement claim.'],
        'scope':'TT1.2V25C, pre-layout, no stochastic noise; numerical maximum step '
                'and saved strobe require appropriate convergence checks.',
        'literal_replacements':[{'before':a,'after':b} for a,b in changes],
    }
    encoded = json.dumps(record, ensure_ascii=False, indent=2)+'\n'
    write_immutable(here/'benches'/(NAME+'_manifest.json'), encoded)
    write_immutable(here/'benches/control_manifest_v1.json',
                    json.dumps([record], ensure_ascii=False, indent=2)+'\n')
    config = {
        'vdd_V':1.2, 'target_Hz':3.2e9, 'reference_Hz':100e6,
        'analogs':{'out0':'out0','out180':'out180','ref':'ref','fb':'fb',
            'ctrl':'ctrl','filter_mid':'filter_mid','vdd':'vdd',
            'total_current':'VDD:p','digital_current':'VDDIG:p','cp_current':'VDDCP:p'},
        'digitals':{'fine_enable':'enable','pfd_reset':'rst','up':'up','dn':'dn',
                    'divider_reset':'div_rst'},
        'words':{'code':['s0','s1','s2','s3','s4']},
    }
    write_immutable(here/'signal_map_v1.json', json.dumps(config,indent=2)+'\n')
    print(json.dumps({'name':NAME,'bench_sha256':sha(bench),
        'manifest':str(here/'benches/control_manifest_v1.json'),
        'source_baseline_unchanged':sha(args.baseline)==BASE_SHA,
        'status':'prepared_unverified_no_simulator_launch'}))


if __name__ == '__main__':
    main()
