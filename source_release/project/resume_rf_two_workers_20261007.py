"""Replace ONE identity-verified RF driver with the same reviewed2-worker driver.

Linux guest only, Python3.6+. No SSH/UI/PDK/netlist edits. A background
supervisor retains its own-driver lock until the RF batch exits. Signal ONLY
the verified old/new driver PID, allowing its existing helper to stop children.
Abort on any unexpected process, source change or incomplete graceful stop.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

PROJECT=Path('@PROJECT_ROOT@')
SCRIPT='run_background_rf_validation.py'
PYTHON='/opt/eda/mentor/calibre2019/aoj_cal_2019.3_15.11/pkgs/icv_python/asp/bin/python3'
SPECTRE_WRAPPER='@SPECTRE_ROOT@/bin/spectre'
SPECTRE_BINARY='@SPECTRE_ROOT@/tools.lnx86/spectre/bin/64bit/spectre'
REVIEWED={SCRIPT:'7317f7fd1c833ad5d1542d64dcceac044c0d7fe51ca9bf52b850df31d8d778eb',
          'run_background_phase3.py':'240edb11708d2856c1318ad3689e8a4d6c19daca495ec1ae736433ed564a242a'}
MIN_MEMORY=4*1024**3
TERMINAL_PSS={'complete_PSS_screen_pass','complete_bounded_evaluation_unknown','interrupted_owned_diagnostic'}


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(pid,procroot=Path('/proc')):
    path=procroot/str(pid)
    try:
        stat=(path/'stat').read_text().rsplit(')',1)[1].split()
        uids=re.search(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',
                       (path/'status').read_text(),re.M)
        if not uids:raise ValueError('Missing /proc UID tuple.')
        return dict(pid=int(pid),uid=int(uids.group(1)),uids=[int(x) for x in uids.groups()],
                    start_ticks=stat[19],ppid=int(stat[1]),state=stat[0],
                    argv=[x.decode('utf8') for x in (path/'cmdline').read_bytes().split(b'\0') if x],
                    cwd=os.readlink(str(path/'cwd')),
                    comm=(path/'comm').read_text().strip())
    except (OSError,ValueError,IndexError,UnicodeDecodeError):return None


def inventory():
    return [row for path in Path('/proc').iterdir() if path.name.isdigit()
            for row in [inspect(path.name)] if row and row['state']!='Z']


def identical(a,b):
    return b is not None and all(a.get(key)==b.get(key) for key in
                                ['pid','uid','uids','start_ticks','argv','cwd'])


def expected_driver(pid,ticks,uid,workers):
    return dict(pid=pid,uid=uid,uids=[uid]*4,start_ticks=str(ticks),cwd=str(PROJECT),
                argv=[PYTHON,'-u',SCRIPT,'--wait-bias-opt','--max-workers',str(workers)])


def is_rf_driver(row):
    return row['cwd']==str(PROJECT) and any(Path(arg).name==SCRIPT for arg in row['argv'])


def own_process(row,uid):
    return row['uid']==uid and (row['cwd']==str(PROJECT) or row['cwd'].startswith(str(PROJECT)+'/'))


def is_noise_process(row,uid):
    if not own_process(row,uid):return False
    names={Path(arg).name for arg in row['argv']}
    if names & {'run_pss_boundary_retry_20261007.py','run_driven_pll_noise_20261007.py'}:return True
    if 'run_pll_full_units_20261007.py' in names:
        args=row['argv']
        if '--group' in args and args[args.index('--group')+1]=='noise':return True
    return any(Path(arg).name.startswith('fullpll_driven_') and arg.endswith('.scs') for arg in row['argv'])


def rf_case_id(row):
    names=[Path(arg).name for arg in row['argv'] if Path(arg).name.startswith('rfvalidation_') and arg.endswith('.scs')]
    if len(names)!=1:return None
    match=re.fullmatch(r'rfvalidation_(.+)_a\d+\.scs',names[0])
    return match.group(1) if match else None


def memory_available():
    match=re.search(r'^MemAvailable:\s+(\d+)\s+kB$',Path('/proc/meminfo').read_text(),re.M)
    if not match:raise RuntimeError('MemAvailable unavailable; no resource assumption.')
    return int(match.group(1))*1024


def descendants(rows,pid):
    included={pid};found=[]
    while True:
        children=[row for row in rows if row['ppid'] in included and row['pid'] not in included]
        if not children:return found
        found.extend(children);included.update(row['pid'] for row in children)


def check_no_noise(uid):
    retry=PROJECT/'results/fullpll/noise/retry_summary_boundary201n.json'
    data=json.loads(retry.read_text())
    if data.get('stage') not in TERMINAL_PSS or not isinstance(data.get('finished_unix'),(int,float)):
        raise RuntimeError('PSS retry has not reached its recorded terminal state.')
    running=[row for row in inventory() if is_noise_process(row,uid)]
    if running:raise RuntimeError('Own noise driver/child still live; RF replacement refused: '+str([r['pid'] for r in running]))
    return dict(path=str(retry),sha256=digest(retry),stage=data['stage'],finished_unix=data['finished_unix'])


def reviewed_files():
    pre=json.loads((PROJECT/'results/resume_preflight_20261007.json').read_text())
    launch=json.loads((PROJECT/'results/resume_launch_20261007.json').read_text())
    if pre.get('project')!=str(PROJECT) or launch.get('project')!=str(PROJECT):
        raise RuntimeError('Resume review belongs to a different project.')
    expected=dict(pre['scripts']);expected.update(launch['reviewed_driver_sha256'])
    result={}
    for name,reviewed in REVIEWED.items():
        hashed=digest(PROJECT/name)
        if expected.get(name)!=reviewed or hashed!=reviewed:
            raise RuntimeError('Driver/helper differs from reviewed preflight/launch identity: '+name)
        result[name]=hashed
    result[Path(__file__).name]=digest(Path(__file__))
    return result


def case_schedule(code,ctrl):
    base=dict(corner='tt',vdd_V=1.2,temperature_C=25,condition='tt_1200_25')
    specs=[dict(base,kind='gain',code=code,vctrl_V=ctrl+d) for d in [-.02,-.01,.01,.02]]
    specs.extend(dict(base,kind='band',code=c,vctrl_V=v) for c in range(32) for v in [.3,1.0])
    specs.extend(dict(base,kind='interior',code=c,vctrl_V=.65)
                 for c in sorted(set([7,8,15,16,23,24,code,min(31,code+1)])))
    specs.extend(dict(kind='pvt',corner=k,vdd_V=1.2,temperature_C=25,condition=k+'_1200_25',code=c,vctrl_V=v)
                 for k in ['ss','ff','fnsp','snfp'] for c in sorted(set([0,code,31])) for v in [.3,1.0])
    specs.extend(dict(kind='pvt',corner='tt',vdd_V=voltage,temperature_C=temp,
                 condition='tt_{}_{}'.format(round(voltage*1000),temp),code=c,vctrl_V=v)
                 for voltage,temp in [(1.08,25),(1.2,-40),(1.2,85)] for c in [7,8,15,16,23,24] for v in [.3,1.0])
    return specs


def validate_selection(rf,old_status):
    bias=json.loads((PROJECT/'results/biasopt_status.json').read_text())
    selected=json.loads((PROJECT/'results/biasopt_selected.json').read_text())
    if bias.get('stage')!='complete' or selected.get('verified') is not True:
        raise RuntimeError('Bias selection is not explicitly verified/completed.')
    if any(not selected.get(k) or selected.get(k)!=bias.get(k) for k in ['version','source_sha256']):
        raise RuntimeError('Completed bias status/selection provenance disagree.')
    source,selection=rf.choose_source(PROJECT,True)
    base=rf.prepare_source(source.read_text())
    hashed=hashlib.sha256(base.encode()).hexdigest()
    if old_status.get('source_sha256')!=hashed or old_status.get('source_netlist')!=str(source):
        raise RuntimeError('RF driver current source/path differs from verified source.')
    code=int(selected['code']);ctrl=float(selected['vctrl_V'])
    specs=case_schedule(code,ctrl)
    ids=[]
    for spec in specs:
        text=rf.render(base,spec);h=hashlib.sha256(text.encode()).hexdigest()[:14]
        ids.append('{}_c{}_u{}_{}_{}'.format(spec['kind'],spec['code'],round(spec['vctrl_V']*1e6),spec['condition'],h))
    if len(set(ids))!=len(ids):raise RuntimeError('Two-worker schedule contains duplicate same-case jobs.')
    return dict(netlist=str(source),file_sha256=digest(source),prepared_source_sha256=hashed,
                selection_sha256=digest(PROJECT/'results/biasopt_selected.json'),
                bias_status_sha256=digest(PROJECT/'results/biasopt_status.json'),
                code=code,vctrl_V=ctrl,version=selected['version'],selected_source_sha256=selected['source_sha256'],
                scheduled_unique_case_count=len(ids),scheduled_case_ids=ids)


def cache_snapshot(source_hash):
    result={}
    for path in (PROJECT/'results/rfvalidation').glob('*.json'):
        try:data=json.loads(path.read_text())
        except (ValueError,OSError):continue
        if not isinstance(data,dict) or not data.get('case_id') or data.get('state')!='completed':continue
        if data.get('source_sha256')!=source_hash:raise RuntimeError('Completed RF cache uses another source: '+path.name)
        waveform=Path(data['raw_waveform']);waveform.resolve().relative_to(PROJECT)
        if not waveform.is_file():raise RuntimeError('Completed RF cache lacks raw waveform: '+path.name)
        result[data['case_id']]=dict(cache_path=str(path),sha256=digest(path),raw_waveform=str(waveform))
    return result


def preserve_cache(before):
    for case,row in before.items():
        if digest(row['cache_path'])!=row['sha256'] or not Path(row['raw_waveform']).is_file():
            raise RuntimeError('Previously completed case/raw changed or disappeared: '+case)


def signal_driver_only(identity):
    if not identical(identity,inspect(identity['pid'])):raise RuntimeError('PID identity changed; no signal sent.')
    os.kill(identity['pid'],signal.SIGTERM)


def wait_graceful(identity,tracked,seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        rows=inventory()
        if identical(identity,inspect(identity['pid'])):
            for row in descendants(rows,identity['pid']):tracked[(row['pid'],row['start_ticks'])]=row
        live=[row for row in tracked.values() if identical(row,inspect(row['pid']))]
        rf_live=[row for row in rows if own_process(row,identity['uid']) and rf_case_id(row)]
        if not identical(identity,inspect(identity['pid'])) and not live and not rf_live:return
        time.sleep(.25)
    raise RuntimeError('Verified RF driver/child did not exit within45s; no forced child signals or restart.')


def rf_job_command(row):
    """Canonical single-job tail, identical for native binary and ksh wrapper."""
    if row['argv'][:2]==['/bin/ksh',SPECTRE_WRAPPER]:tail=row['argv'][2:];kind='wrapper'
    elif row['argv'][:1]==[SPECTRE_BINARY]:tail=row['argv'][1:];kind='actual'
    else:raise RuntimeError('Unrecognized own RF Spectre wrapper/binary; refuse ambiguity.')
    if len(tail)!=7 or tail[1:3]!=['-format','psfascii'] or tail[3]!='-raw' or tail[5]!='+log':
        raise RuntimeError('RF Spectre command differs from original helper launch.')
    netlist,raw,log=Path(tail[0]),Path(tail[4]),Path(tail[6])
    tag=netlist.stem
    if netlist!=PROJECT/'netlists'/(tag+'.scs') or raw!=PROJECT/'results/rfvalidation'/(tag+'.raw') or log!=PROJECT/'logs'/(tag+'.log'):
        raise RuntimeError('RF Spectre artifact paths differ from reviewed same-job identity.')
    return kind,tuple(tail)


def analyze_rf_processes(rows,uid,allow_driver,max_rf):
    drivers=[row for row in rows if is_rf_driver(row)]
    allowed=[allow_driver] if allow_driver else []
    if len(drivers)!=len(allowed) or any(not identical(a,b) for a,b in zip(allowed,drivers)):
        raise RuntimeError('Unexpected same-project RF driver; duplicate resume refused.')
    sims=[row for row in rows if own_process(row,uid) and
          (row['comm']=='spectre' or rf_case_id(row) or row['argv'][:2]==['/bin/ksh',SPECTRE_WRAPPER]
           or row['argv'][:1]==[SPECTRE_BINARY])]
    if any(rf_case_id(row) is None for row in sims):
        raise RuntimeError('Other own-project Spectre work still live; two-job cap refuses new RF workers.')
    classified=[(row,)+rf_job_command(row) for row in sims]
    actual=[(row,job) for row,kind,job in classified if kind=='actual']
    wrappers=[(row,job) for row,kind,job in classified if kind=='wrapper']
    # The installed Spectre launcher is /bin/ksh ->native64bit child. Count
    # ONLY native jobs; paired same-case wrapper is not a duplicate worker.
    # Require exact matching argv tails and PPID chain to the trusted driver.
    if classified and allow_driver is None:raise RuntimeError('RF job exists without its verified driver.')
    for row,job in actual:
        parent=[wrapper for wrapper,wjob in wrappers if wjob==job and row['ppid']==wrapper['pid']]
        if len(parent)!=1 or parent[0]['ppid']!=allow_driver['pid']:
            raise RuntimeError('Native RF binary lacks exact same-job wrapper/verified driver ancestry.')
    for wrapper,job in wrappers:
        if wrapper['ppid']!=allow_driver['pid']:
            raise RuntimeError('RF wrapper is not a direct child of the trusted sole RF driver.')
        if sum(wjob==job for other,wjob in wrappers)!=1:
            raise RuntimeError('Duplicate RF wrapper for the same exact job.')
        children=[row for row,ajob in actual if ajob==job and row['ppid']==wrapper['pid']]
        if len(children)!=1:
            raise RuntimeError('RF wrapper/binary pair not yet complete or ambiguous.')
    ids=[rf_case_id(row) for row,job in actual]
    if len(ids)>max_rf or len(set(ids))!=len(ids):
        raise RuntimeError('RF same-case duplication or worker-count guard failed.')
    return rows


def current_guards(uid,allow_driver=None,max_rf=0):
    # Native child birth/exit can fall between /proc rows. Re-read only this
    # incomplete pair for<=1s; unknown argv/ancestry/duplicate jobs fail at once.
    deadline=time.monotonic()+1
    while True:
        rows=inventory()
        try:return analyze_rf_processes(rows,uid,allow_driver,max_rf)
        except RuntimeError as error:
            if str(error)!='RF wrapper/binary pair not yet complete or ambiguous.' or time.monotonic()>=deadline:raise
            time.sleep(.05)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-pid',required=True,type=int)
    parser.add_argument('--expected-start-ticks',required=True)
    parser.add_argument('--expected-uid',required=True,type=int)
    args=parser.parse_args()
    if Path.cwd().resolve()!=PROJECT or os.getuid()!=args.expected_uid:
        raise RuntimeError('Wrong project/calling UID; no process actions.')
    root=PROJECT/'results/rfvalidation';root.mkdir(exist_ok=True)
    lock=(root/'resume_two_workers.lock').open('a+')
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    reportpath=PROJECT/'results/resume_rf_two_workers_20261007.json'
    if reportpath.exists():raise RuntimeError('Unique resume record exists; rerun refused.')
    reviewed=reviewed_files()
    sys.path.insert(0,str(PROJECT))
    import run_background_phase3 as helper
    import run_background_rf_validation as rf
    old=expected_driver(args.expected_pid,args.expected_start_ticks,args.expected_uid,1)
    if not identical(old,inspect(old['pid'])):raise RuntimeError('Live RF identity differs from trusted snapshot.')
    status=json.loads((PROJECT/'results/rfvalidation_status.json').read_text())
    if status.get('pid')!=old['pid'] or status.get('max_workers')!=1 or status.get('stage')=='complete_sampled_checks':
        raise RuntimeError('RF status not the live incomplete one-worker driver.')
    pss=check_no_noise(args.expected_uid)
    mem=memory_available()
    if mem<MIN_MEMORY:raise RuntimeError('Available memory below4GiB; leave old RF driver untouched.')
    source=validate_selection(rf,status)
    completed=cache_snapshot(source['prepared_source_sha256'])
    rows=current_guards(args.expected_uid,old,1)
    children=descendants(rows,old['pid'])
    if any(row['uid']!=args.expected_uid or not own_process(row,args.expected_uid) for row in children):
        raise RuntimeError('Old driver has unexpected descendants; no signal sent.')
    artifacts=[str(path) for directory,pattern in [(PROJECT/'logs','rfvalidation_*'),
               (PROJECT/'netlists','rfvalidation_*'),(root,'*.raw')] for path in directory.glob(pattern)]
    report=dict(stage='preflight_verified',project=str(PROJECT),supervisor_pid=os.getpid(),
                old_driver=old,old_status=status,verified_descendants=children,
                script_helper_sha256=reviewed,verified_bias_source=source,PSS_retry_terminal=pss,
                available_memory_before_bytes=mem,completed_cache_before=completed,
                partial_artifacts_preserved=artifacts,only_signal='identity-verified driver PID SIGTERM',
                worker_change=dict(old=1,new=2),own_simulator_cap=2,
                duplicate_guard='Supervisor flock + exact sole own-driver identity + unique schedule hashes '
                    '+ live RF same-case/worker checks; original driver physics/files unchanged.')
    def save(stage,**extra):
        report.update(stage=stage,updated_unix=time.time(),**extra);helper.atomic_json(reportpath,report)
        print(json.dumps(dict(stage=stage,path=str(reportpath))),flush=True)
    new=None;identity=None
    def interrupt(signum,frame):raise KeyboardInterrupt('Supervisor signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    save('preflight_verified')
    try:
        # Revalidate immutable review/selection and process identity immediately before stop.
        if reviewed_files()!=reviewed or validate_selection(rf,status)!=source:
            raise RuntimeError('Source/helper/selection changed during preflight.')
        check_no_noise(args.expected_uid)
        tracked={(row['pid'],row['start_ticks']):row for row in children}
        signal_driver_only(old);save('old_driver_SIGTERM_sent',signal_time_unix=time.time())
        wait_graceful(old,tracked,45)
        preserve_cache(completed)
        if any(not Path(path).exists() for path in artifacts):raise RuntimeError('A retained partial artifact disappeared.')
        current_guards(args.expected_uid,None,0);check_no_noise(args.expected_uid)
        mem=memory_available()
        if mem<MIN_MEMORY:raise RuntimeError('Available memory below4GiB after old driver stopped; no resume.')
        if reviewed_files()!=reviewed or validate_selection(rf,status)!=source:
            raise RuntimeError('Source/helper/selection changed before resume launch.')
        stamp=str(int(time.time()));logpath=PROJECT/'logs'/('rfvalidation_two_workers_resume_'+stamp+'.log')
        if logpath.exists():raise RuntimeError('New owned log path already exists.')
        command=old['argv'][:-1]+['2']
        with logpath.open('x') as stream:
            new=subprocess.Popen(command,cwd=str(PROJECT),stdin=subprocess.DEVNULL,
                                 stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            identity=inspect(new.pid)
            if identity and identity['argv']==command:break
            if new.poll() is not None:raise RuntimeError('New driver exited before identity verified.')
            time.sleep(.05)
        if not identity or identity['argv']!=command or identity['uid']!=args.expected_uid or identity['cwd']!=str(PROJECT):
            raise RuntimeError('New driver exact identity verification failed.')
        save('resumed_two_workers',new_driver=identity,new_log=str(logpath),
             available_memory_at_launch_bytes=mem,completed_cache_after_stop=cache_snapshot(source['prepared_source_sha256']),
             old_driver_and_children_exited=True,completed_and_partial_artifacts_preserved=True)
        # Keep own-driver flock while child lives; do not change any driver/model file.
        while new.poll() is None:
            current_guards(args.expected_uid,identity,2)
            if reviewed_files()!=reviewed or digest(source['netlist'])!=source['file_sha256']:
                raise RuntimeError('Reviewed source/helper changed while resumed driver runs.')
            live=json.loads((PROJECT/'results/rfvalidation_status.json').read_text())
            if live.get('pid')==new.pid:
                if live.get('source_sha256') and live['source_sha256']!=source['prepared_source_sha256']:
                    raise RuntimeError('Resumed driver reported a different source hash.')
                if live.get('max_workers') and live['max_workers']!=2:raise RuntimeError('New worker count differs.')
            time.sleep(1)
        current_guards(args.expected_uid,None,0);preserve_cache(completed)
        final=json.loads((PROJECT/'results/rfvalidation_status.json').read_text())
        finished=(new.returncode==0 and final.get('pid')==new.pid and final.get('stage')=='complete_sampled_checks')
        save('complete_two_worker_resume' if finished else 'ended_without_complete_sampled_checks',new_driver_rc=new.returncode,final_rf_status=final,
             completed_cache_final=cache_snapshot(source['prepared_source_sha256']),
             RF_full_signoff_claim=False)
    except BaseException as error:
        # Only the newly launched PID is eligible, with its exact recorded identity.
        if new is not None and new.poll() is None:
            current=inspect(new.pid)
            if identity is not None and identical(identity,current):
                signal_driver_only(identity)
                wait_graceful(identity,{},45)
        save('stopped_or_failed_without_foreign_signals',reason=repr(error),no_more_automatic_resume=True)
        if not isinstance(error,KeyboardInterrupt):raise
        return 130
    finally:lock.close()
    return 0


if __name__=='__main__':sys.exit(main())
