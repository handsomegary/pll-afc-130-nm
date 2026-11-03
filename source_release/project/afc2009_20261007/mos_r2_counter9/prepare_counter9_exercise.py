"""Prepare an unrun, light-load MOS subset for R2 9-bit Gray/CDC boundaries.

Imports the fixed R2 builder's actual Circuit.gray_counter/sync_gray primitives.
No simulator invocation, no behavioral counter, no edits to R2 AFC sources.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

FIXED_AFC_SHA='45654975e7b53873559fd157955c1d8a922f40550fea81687dfd675fe9de4cc0'
FIXED_BUILDER_SHA='f0d34ba7dcedfe0ea01ac41daef9c746787962e795dda7bf2ed1cfa8c77e3cb1'
GUEST_ROOT='@PROJECT_ROOT@/afc2009_20261007/mos_r2_counter9'
PDK='@TECH_ROOT@/models/spectre/ms013_io33_v2p6_7p_spe.lib'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    here=Path(__file__).resolve().parent
    ap.add_argument('--out-dir',type=Path,default=here)
    ap.add_argument('--guest-dir',default=GUEST_ROOT)
    ap.add_argument('--builder',type=Path,default=here.parent/'mos_r2'/'build_afc2009_mos.py')
    args=ap.parse_args();builder=args.builder.resolve();afc_source=builder.parent/'afc2009_mos.scs'
    if sha(afc_source)!=FIXED_AFC_SHA:raise ValueError('Selected fixed R2 source SHA changed.')
    before_builder=sha(builder);before_afc=sha(afc_source)
    if before_builder!=FIXED_BUILDER_SHA:raise ValueError('Fixed R2 MOS builder SHA changed.')
    spec=importlib.util.spec_from_file_location('fixed_r2_primitives',str(builder))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    circuit=module.Circuit();words={}
    for initial,prefix in [(0,'zero_'),(1,'one_')]:
        native=circuit.gray_counter('clk','rst',prefix,initial=initial,bits=9)
        synchronized=circuit.sync_gray(native,'ref','rst',prefix)
        binary=circuit.decode_gray(native,prefix+'native_b')
        decoded=circuit.decode_gray(synchronized,prefix+'sync_b')
        words[prefix[:-1]]={'initial_native':initial,
            'native_gray':native,'native_binary':binary,
            'sync1_gray':[prefix+'sync1_'+str(i) for i in range(9)],
            'sync2_gray':synchronized,'sync2_binary':decoded}
    output=args.out_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    mos=output/'counter9_gray_cdc_mos.scs'
    header=('// Prepared-only light-load subset, actual R2 MOS primitives.\n'
            '// Native9-bit registeredGray initial0/1, matched2-stage9-bitCDC.\n'
            '// No behavioral counter; this is not complete-AFC CDC signoff.\n'
            'simulator lang=spectre\nsubckt counter9_gray_cdc_mos (vdd vss clk ref rst)\n')
    mos.write_text(header+'\n'.join(circuit.lines)+'\nends counter9_gray_cdc_mos\n',encoding='utf-8')
    clockgroups=[{'clock':clock,'reset':reset,'master_open':values[0],'master_openb':values[1],'slave_open':values[2],'slave_openb':values[3]} for (clock,reset),values in circuit.clock_groups.items()]
    diagnostics=list(dict.fromkeys([node for item in words.values() for key,value in item.items() if isinstance(value,list) for node in value]+[node for group in clockgroups for key,node in group.items() if key not in ('clock','reset')]))
    bench=output/'counter9_gray_cdc_tb.scs'
    benchtext=('// Prepared-only transistor counter/CDC exercise. No simulation has been launched.\n'
        'simulator lang=spectre\nglobal 0\n'
        'include "{}" section=tt\n'
        'include "{}/counter9_gray_cdc_mos.scs"\n'
        'simulatorOptions options temp=25 reltol=1e-4 vabstol=1e-6 iabstol=1e-12\n'
        'VDD (vdd 0) vsource dc=1.2\n'
        'VCLK (clk 0) vsource type=pulse val0=0 val1=1.2 delay=10n rise=20p fall=20p width=4.98n period=10n\n'
        'VREF (ref 0) vsource type=pulse val0=0 val1=1.2 delay=15n rise=20p fall=20p width=4.98n period=10n\n'
        '// Reset transitions are 2ns away from native rising edges and 3ns from REF rising edges.\n'
        'VRST (rst 0) vsource type=pwl wave=[0 1.2 102n 1.2 102.02n 0 5.402u 0 5.40202u 1.2 5.422u 1.2 5.42202u 0]\n'
        'XCNT (vdd 0 clk ref rst) counter9_gray_cdc_mos\n'
        'saveOptions options save=selected\n'
        'save clk ref rst vdd VDD:p\n'
        'save {}\n'
        'tran tran stop=5.7u maxstep=100p errpreset=moderate skipdc=no strobeperiod=100p strobeoutput=strobeonly\n').format(PDK,args.guest_dir,' '.join('XCNT.'+node for node in diagnostics))
    bench.write_text(benchtext,encoding='utf-8')
    record={'status':'prepared_not_simulated','simulation_started':False,'scope':'Two lightly loaded native Gray counters plus matched two-stage CDC; not the complete AFC clock fanout, epoch or CDC proof.',
        'fixed_R2_AFC_source_sha256':before_afc,'R2_builder_path':str(builder),'R2_builder_sha256':before_builder,
        'subset_source':str(mos),'subset_source_sha256':sha(mos),'bench':str(bench),'bench_sha256':sha(bench),
        'subset_module':'counter9_gray_cdc_mos','instance':'XCNT','models':['n12','p12'],'PDK_model_files_distributed':False,
        'MOS_count':circuit.transistors,'DFF_count':circuit.dffs,'counter_bits':9,'modulus':512,
        'native_clock_Hz':100e6,'reference_Hz':100e6,'REF_rising_after_CLK_rising_s':5e-9,
        'stop_s':5.7e-6,'maxstep_s':100e-12,'strobeperiod_s':100e-12,
        'planned_engine':'Spectre ++APS','planned_wall_deadline_s':1800,
        'nominal_active_CLK_edges_first_reset_epoch':530,'reset_preset_values':[0,1],
        'sampling_contract':'Use actual saved CLK/REF/reset threshold crossing times, event ordinal modulo512, REF+2.5ns stable samples. Sync1 captures native Gray; sync2 captures previous sync1.',
        'sample_delay_after_REF_s':2.5e-9,'threshold_V':.6,
        'words':{label:{key:('XCNT.'+value if isinstance(value,str) else ['XCNT.'+name for name in value] if isinstance(value,list) else value) for key,value in item.items()} for label,item in words.items()},
        'clock_nonoverlap_groups':clockgroups,'saved_internal_nodes':len(diagnostics),
        'required_observed_boundaries':['255_to_256','511_to_0','initial_reset_preset0','initial_reset_preset1','second_reset_preset0','second_reset_preset1'],
        'limits':['No electrical simulation performed by this preparer.','Lightly loaded subset does not reproduce full AFC reset/CDC fanout.','100ps strobe cannot exclude narrow excursions or metastability.','Ideal external CLK/REF/reset test stimuli; actual state and logic are MOS.']}
    (output/'counter9_manifest.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    (output/'subset_logical_records.json').write_text(json.dumps({'gates':circuit.logic_ops,'flops':circuit.flop_records,'models':'Ideal Boolean records are inspection only, not physical evidence.'},indent=2)+'\n',encoding='utf-8')
    assert sha(builder)==before_builder and sha(afc_source)==before_afc,'Source changed during preparation'
    print(json.dumps({key:record[key] for key in ('status','fixed_R2_AFC_source_sha256','R2_builder_sha256','subset_source_sha256','bench_sha256','MOS_count','DFF_count','saved_internal_nodes','stop_s')},indent=2))


if __name__=='__main__':main()
