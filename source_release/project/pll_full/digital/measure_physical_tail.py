"""Read-only physical fine-loop tail interface and branch-power measurement.

This supplements the analog lock measurement; it does not establish lock on
its own and deterministic edge variation is not physical noise jitter.
"""
import argparse
import json
from pathlib import Path

import measure_digital_units as unit
from measure_receiver_sweep import clock_margin
from measure_loaded_interface import frequency


def measure(data,begin,end):
    if 'fb' not in data:raise ValueError('Expected physical divider feedback fb')
    data=dict(data);data['q5']=data['fb']
    t=data['time']
    if not t or t[-1]-t[0]<.9*(end-begin):raise ValueError('Tail waveform window incomplete')
    diff=[a-b for a,b in zip(data['out0'],data['out180'])]
    carrier=frequency(t,diff)
    if not carrier:raise ValueError('No sustained actual VCO differential carrier')
    result=unit.measure(data,'receiver',begin,end,fin=carrier)
    result.update(clock_margin(data,begin,end))
    result['actual_vco_frequency_Hz']=carrier
    result['actual_vco_differential_vpp_V']=max(diff)-min(diff)
    result['target_Hz']=3.2e9
    result['target_relative_error']=carrier/3.2e9-1
    result['target_frequency_ok']=abs(result['target_relative_error'])<=.001
    result['interface_valid']=bool(result['valid'] and result['clk_rail_dwell_valid'] and result['clk_rail_margin_V']>=0)
    result['valid']=result['interface_valid']
    if 'VDDIG:p' in data:
        result['receiver_divider_pfd_supply_power_W']=unit.mean(t,[-v*i for v,i in zip(data['vdddig'],data['VDDIG:p'])])
    if 'VDDCP:p' in data:
        result['cp_supply_power_W']=unit.mean(t,[-v*i for v,i in zip(data['vddcp'],data['VDDCP:p'])])
    if 'cp_supply_power_W' in result and 'receiver_divider_pfd_supply_power_W' in result:
        result['vco_and_bias_supply_power_W']=(result['total_supply_power_W']-
              result['cp_supply_power_W']-result['receiver_divider_pfd_supply_power_W'])
    result['ctrl_mean_V']=unit.mean(t,data['ctrl'])
    result['ctrl_min_V']=min(data['ctrl']);result['ctrl_max_V']=max(data['ctrl'])
    result['filter_mid_mean_V']=unit.mean(t,data['filter_mid'])
    # Voltage-area equivalent duty matches the unit PFD convention and
    # includes finite slew; it is not a count of samples above a threshold.
    result['up_voltage_area_equivalent_duty']=unit.mean(t,data['up'])/1.2
    result['dn_voltage_area_equivalent_duty']=unit.mean(t,data['dn'])/1.2
    result['net_up_minus_dn_duty']=(result['up_voltage_area_equivalent_duty']-
                                   result['dn_voltage_area_equivalent_duty'])
    result['scope']='Physical MOS VCO/receiver/divider/PFD/CP tail screen with ideal bias/reference/passives; no standalone lock/noise/PEX/PVT signoff'
    result['physical_noise_jitter_s']=None
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--start',type=float,default=1.5e-6)
    ap.add_argument('--end',type=float,default=2e-6)
    args=ap.parse_args()
    if args.end<=args.start:raise ValueError('Invalid measurement window')
    waveform=Path(args.raw)
    result=measure(unit.read_psf(waveform,args.start,args.end),args.start,args.end)
    result['raw_file']=str(waveform);result['raw_sha256']=unit.file_sha256(waveform)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['interface_valid','actual_vco_frequency_Hz','ctrl_mean_V','total_supply_power_W','clk_rail_margin_V']}))
    return 0 if result['interface_valid'] else 2


if __name__=='__main__':raise SystemExit(main())
