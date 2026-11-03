"""Read-only R1 saved master/slave clock overlap/deadband audit.

Only the primary controller clock group saved in this bench is measured.
No claim for other clock/reset groups, PVT, setup/hold, or metastability.
"""
import argparse
import bisect
import copy
import json
from pathlib import Path
import measure_afc2009 as m


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True,type=Path)
    ap.add_argument('--measurement-json',type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--begin-ns',type=float,default=110)
    args=ap.parse_args()
    cfg=copy.deepcopy(m.DEFAULT_CONFIG)
    cfg['analogs']={'ref':'ref'}
    cfg['digitals']={'master':'XAFC.clk_low108','master_b':'XAFC.clk_lowb109',
        'slave':'XAFC.clk_high110','slave_b':'XAFC.clk_highb111',
        'control':'XAFC.control_clock','reset':'rst'}
    cfg['words']={}
    data,digital,words,evidence=m.read_saved_vectors(args.raw,cfg)
    if args.measurement_json:
        previous=json.loads(args.measurement_json.read_text(encoding='utf8'))
        if previous['source_evidence']['raw_sha256']!=evidence['raw_sha256']:
            raise ValueError('Saved clock and unit measurement refer to different raw hashes.')
    needed=['master','slave','master_b','slave_b','control','reset']
    missing=[key for key in needed if not digital[key]['levels']]
    begin=args.begin_ns*1e-9
    end=data['time'][-1]
    overlaps=[]
    all_bounds=sorted({begin,end}|{t for key in ['master','slave']
        for t,_ in digital[key]['levels'] if begin<t<end})
    for a,b in zip(all_bounds,all_bounds[1:]):
        master=m.event_value(digital['master']['levels'],a)
        slave=m.event_value(digital['slave']['levels'],a)
        if master==1 and slave==1:
            overlaps.append({'begin_s':a,'end_s':b,'duration_s':b-a})
    gap={}
    for source,destination in [('master','slave'),('slave','master')]:
        values=[]
        for fall in digital[source]['falling']:
            if fall<begin:
                continue
            rises=digital[destination]['rising']
            index=bisect.bisect_left(rises,fall)
            if index<len(rises) and rises[index]<=end:
                values.append({'from_falling_s':fall,'to_rising_s':rises[index],
                    'deadtime_s':rises[index]-fall})
        gap[source+'_close_to_'+destination+'_open']={
            'count':len(values),'minimum_deadtime_s':min((x['deadtime_s'] for x in values),default=None),
            'maximum_deadtime_s':max((x['deadtime_s'] for x in values),default=None),
            'cases':values}
    maximum_step=max(b-a for a,b in zip(data['time'],data['time'][1:]))
    out={'version':'afc2009-R1-primary-clock-deadband-v1',
        'source_evidence':evidence,'source_measurement_sha256':m.sha(args.measurement_json) if args.measurement_json else None,
        'analysis_interval_s':[begin,end],'missing_saved_ports':missing,
        'primary_clock_saved_overlap_present':bool(overlaps),'overlap_intervals':overlaps,
        'deadband':gap,'digital_transition_ledgers':digital,
        'maximum_saved_sample_spacing_s':maximum_step,'threshold_V':.6,
        'clock_group':'R1 controller CLK=n19 / reset=rst; clk_low108 and clk_high110.',
        'simulator_started':False,
        'scope':'Actual saved threshold crossing times for one clock group. With100psstrobe, '
            'interpolation cannot exclude unsaved sub-strobe excursions, and this is not '
            'all-clock, all-PVT, setup/hold, metastability or timing signoff.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.output),'missing':missing,'observed_overlap':bool(overlaps),
        'minimum_deadtime_s':{key:item['minimum_deadtime_s'] for key,item in gap.items()}}))


if __name__=='__main__':
    main()
