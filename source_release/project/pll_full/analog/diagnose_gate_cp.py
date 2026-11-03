"""Inspect actual gate/bias disturbance during short CP pulses. No simulation."""
import argparse
import json
from pathlib import Path
from measure_cp_units import segment, interpolate, integrate
from measure_pll import read_psf, integral_mean


def inspect(path):
    d=read_psf(path); t=d['time']
    result={}
    for state,begin,end,prefix,current in [
            ('up',20e-9,22.02e-9,['XCP.gp','XCP.bpcp'],'XCP.MPUP:d'),
            ('dn',30e-9,32.02e-9,['XCP.gn','XCP.bncp'],'XCP.MNDN:d')]:
        row={}
        for name in prefix:
            x,y=segment(t,d[name],begin,end)
            row[name]=dict(before_V=interpolate(t,d[name],begin-0.5e-9),
                           min_V=min(y),max_V=max(y),
                           at_0p1ns_V=interpolate(t,d[name],begin+0.1e-9),
                           at_0p5ns_V=interpolate(t,d[name],begin+0.5e-9),
                           at_1ns_V=interpolate(t,d[name],begin+1e-9),
                           at_1p8ns_V=interpolate(t,d[name],begin+1.8e-9),
                           at_2p5ns_V=interpolate(t,d[name],begin+2.5e-9))
        signed=[(-q if state=='up' else q) for q in d[current]]
        x,y=segment(t,signed,begin,end)
        row['output_terminal_current']=dict(min_A=min(y),max_A=max(y),
                                            mean_2p02ns_A=integral_mean(x,y),
                                            at_1ns_A=interpolate(t,signed,begin+1e-9),
                                            at_1p8ns_A=interpolate(t,signed,begin+1.8e-9))
        # Wider window detects whether ending the charge integration too early
        # omitted a substantial slow switch-off tail.
        row['terminal_charge_10ns_C']=integrate(t,signed,begin-0.5e-9,begin+9.5e-9)
        result[state]=row
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('waveform');ap.add_argument('--out')
    args=ap.parse_args();result=inspect(args.waveform)
    txt=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    if args.out:Path(args.out).write_text(txt,encoding='utf-8')
    print(txt)
