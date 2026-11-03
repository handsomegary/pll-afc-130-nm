"""One-worker bounded physical-PLL PSS/noise suite; no GUI or foreign jobs."""
import argparse,fcntl,hashlib,json,os,signal,sys,time
from pathlib import Path
project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
sys.path.insert(0,str(project))
import run_background_phase3 as helper
sys.path.insert(0,str(project/'pll_full/analog'))
from prepare_driven_pll_noise import ocean_script
from measure_driven_pll_noise import sideband_comparison

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',required=True)
    ap.add_argument('--total-seconds',type=int,default=1800)
    args=ap.parse_args()
    assert 60<=args.total_seconds<=1800
    manifest_path=Path(args.manifest).resolve();manifest=json.loads(manifest_path.read_text())
    manifest_path.relative_to(project/'pll_full/analog/benches')
    folder=project/'results/fullpll/noise';folder.mkdir(parents=True,exist_ok=True)
    handle=(folder/'suite.lock').open('a+')
    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    handle.seek(0);handle.truncate();handle.write(str(os.getpid())+'\n');handle.flush()
    started=time.time();deadline=time.monotonic()+args.total_seconds
    results=[];measured={}
    status_path=project/'results/driven_pll_noise_status_20261007.json'
    summary_path=folder/'driven_noise_summary.json'
    def save(stage,**kwargs):
        data=dict(stage=stage,pid=os.getpid(),started_unix=started,updated_unix=time.time(),
           total_walltime_limit_s=args.total_seconds,cases=results,manifest=str(manifest_path),
           scope=manifest['scope'],own_only=True)
        data.update(kwargs);helper.atomic_json(status_path,data);helper.atomic_json(summary_path,data)
        print(json.dumps({'stage':stage,'case':kwargs.get('current_case'),'recorded':len(results)}),flush=True)
    def interrupted(signum,frame):raise KeyboardInterrupt('Requested signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    save('starting')
    try:
        for case in manifest['cases']:
            remaining=deadline-time.monotonic()
            if remaining<100:
                save('complete_bounded_evaluation',remaining_unmeasured=case['name'],reason='Total walltime budget exhausted; unmeasured values remain unknown')
                return 0
            name=case['name'];kind=case['kind'];bench=Path(case['path'])
            assert hashlib.sha256(bench.read_bytes()).hexdigest()==case['bench_sha256']
            item=dict(name=name,kind=kind,maxsideband=case['maxsideband'],state='running')
            results.append(item);save('running',current_case=name)
            limit=max(60,min(case['walltime_limit_s'],int(remaining)-15))
            command=[sys.executable,str(project/'run_pll_full_units_20261007.py'),
              '--group','noise','--only',name,'--engine','aps','--timeout-seconds',str(limit)]
            rc=helper.run_process(command,folder/(name+'_runner.stdout'),project,deadline)
            execution_path=folder/('all_cases_'+name+'_aps2.json')
            records=json.loads(execution_path.read_text())
            matches=[r for r in records if r['name']==name]
            assert len(matches)==1
            record=matches[0]
            item.update(execution_record_path=str(execution_path),execution=record,runner_rc=rc)
            if rc or record['state']!='completed' or record.get('spectre_rc')!=0:
                raise RuntimeError('Bounded Spectre analysis unavailable: '+str(record.get('error',rc)))
            raw=[Path(p) for p in record['artifacts'] if p.endswith('.raw')][0]
            log=[Path(p) for p in record['artifacts'] if p.endswith('.log')][0]
            out=folder/(name+'_measurement.json')
            measure_cmd=[sys.executable,str(project/'pll_full/analog/measure_driven_pll_noise.py'),
              '--raw',str(raw),'--out',str(out),'--kind',kind,'--spectre-log',str(log),'--spectre-rc','0',
              '--manifest',str(manifest_path),'--case-name',name,'--bench',str(bench),
              '--execution-record-json',str(execution_path)]
            if kind!='pss':
                prefix=folder/name;ocn=folder/(name+'_extract.ocn')
                ocn.write_text(ocean_script(raw,prefix,integrated=kind=='band'))
                ocean_rc=helper.run_process(['@IC_ROOT@/tools/dfII/bin/ocean','-nograph','-restore',str(ocn)],
                     folder/(name+'_ocean.stdout'),project,min(deadline,time.monotonic()+90))
                item.update(ocean_rc=ocean_rc,ocean_script=str(ocn))
                measure_cmd+=['--ocean-rc',str(ocean_rc),'--curve',str(prefix)+'_pn_ssb.txt',
                              '--fd-curve',str(prefix)+'_pss_fd_magnitude.txt','--scalars',str(prefix)+'_noise_scalars.txt']
            measurement_rc=helper.run_process(measure_cmd,folder/(name+'_measure.stdout'),project,min(deadline,time.monotonic()+90))
            if measurement_rc or not out.is_file():
                raise RuntimeError('Actual periodic/noise evidence failed read-only measurement; see '+str(folder/(name+'_measure.stdout')))
            measurement=json.loads(out.read_text())
            periodic=measurement if kind=='pss' else measurement.get('periodic',{})
            if periodic.get('periodic_screen_pass') is not True:
                raise RuntimeError('Periodic cycle/closure/rail screen failed; no PLL noise claim')
            item.update(state='measured',measurement_path=str(out),measurement=measurement)
            measured[name]=measurement;save('running',current_case=name)
        comparison=None
        if 'fullpll_driven_band_sb128' in measured and 'fullpll_driven_band_sb192' in measured:
            try:comparison=sideband_comparison(measured['fullpll_driven_band_sb128'],measured['fullpll_driven_band_sb192'])
            except Exception as error:comparison=dict(sideband_comparison_completed=False,reason=repr(error))
        save('complete_bounded_evaluation',sideband_comparison=comparison)
        return 0
    except KeyboardInterrupt:
        helper.STOP.set()
        with helper.ACTIVE_LOCK:owned=list(helper.ACTIVE.values())
        for process in owned:helper.stop_process_group(process)
        if results and results[-1]['state']=='running':results[-1]['state']='interrupted'
        save('stopped',completed_results_retained=True);return 130
    except Exception as error:
        if results and results[-1]['state']=='running':results[-1].update(state='unavailable',error=repr(error))
        save('complete_bounded_evaluation',reason=repr(error),unmeasured_values='unknown')
        return 0

if __name__=='__main__':sys.exit(main())
