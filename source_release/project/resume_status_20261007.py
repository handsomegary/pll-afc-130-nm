"""Read/export only this PLL continuation's JSON evidence, never launch jobs."""
import hashlib
import json
import os
from pathlib import Path
import time
import run_background_phase3 as helper

project=Path('@PROJECT_ROOT@')
assert Path.cwd().resolve()==project
dest=project/'results/resume_snapshot_20261007'
dest.mkdir(exist_ok=True)
files={
 'biasopt_status.json':'biasopt_status.json',
 'biasopt_selected.json':'biasopt_selected.json',
 'biasopt/biasopt_v3_cases.json':'biasopt_v3_cases.json',
 'biasopt/biasopt_candidates.json':'biasopt_candidates.json',
 'biasopt/biasopt_completion_summary.json':'biasopt_completion_summary.json',
 'biasopt/biasopt_pn60_confirmations.json':'biasopt_pn60_confirmations.json',
 'rfvalidation_status.json':'rfvalidation_status.json',
 'rfvalidation/all_cases.json':'rfvalidation_all_cases.json',
 'rfvalidation/local_gain_summary.json':'local_gain_summary.json',
 'rfvalidation/tt_bands_summary.json':'tt_bands_summary.json',
 'rfvalidation/pvt_summary.json':'pvt_summary.json',
 'receiverload_status.json':'receiverload_status.json',
 'receiverload_selected.json':'receiverload_selected.json',
 'receiverload/receiverload_progress.json':'receiverload_progress.json',
 'receiverload/receiverload_completion_summary.json':'receiverload_completion_summary.json',
 'selectedstartup_status.json':'selectedstartup_status.json',
 'selectedstartup/selectedstartup_all_cases.json':'selectedstartup_all_cases.json',
 'selectedstartup/selectedstartup_completion_summary.json':'selectedstartup_completion_summary.json',
 'resume_launch_20261007.json':'resume_launch_20261007.json',
 'resume_preflight_20261007.json':'resume_preflight_20261007.json',
 'resume_rf_two_workers_20261007.json':'resume_rf_two_workers_20261007.json',
 'final_owned_jobs_20261007.json':'final_owned_jobs_20261007.json',
 'resume_dc_probe_20261007.json':'resume_dc_probe_20261007.json',
 'loaded_pn30_check_status_20261007.json':'loaded_pn30_check_status_20261007.json',
 'loaded_pn30_check_20261007/loaded_pn30_comparison.json':'loaded_pn30_comparison.json',
 'fullpll/fullpll_measurements.json':'fullpll_measurements.json',
 'fullpll/lock_trace_series.json':'lock_trace_series.json',
 'fullpll/lock_energy_measurements.json':'lock_energy_measurements.json',
 'fullpll/units/digital_electrical_measurements.json':'digital_electrical_measurements.json',
 'fullpll/units/cp_measurements.json':'cp_measurements.json',
 'fullpll/receiver/receiver_sweep_measurements.json':'receiver_sweep_measurements.json',
 'fullpll/receiverac/receiver_ac_measurements.json':'receiver_ac_measurements.json',
 'fullpll/loaded/loaded_interface_measurements.json':'loaded_interface_measurements.json',
 'fullpll/loaded/aps_loaded_comparison_case.json':'aps_loaded_comparison_case.json',
 'fullpll/loaded/aps_accuracy_step2p_measurement.json':'aps_accuracy_step2p_measurement.json',
 'fullpll/loaded/aps_accuracy_step1p_measurement.json':'aps_accuracy_step1p_measurement.json',
 'fullpll/stage3/physical_tail_measurements.json':'physical_tail_measurements.json',
 'fullpll/stage3/physical_tail_step2p_measurements.json':'physical_tail_step2p_measurements.json',
 'driven_pll_noise_status_20261007.json':'driven_pll_noise_status_20261007.json',
 'fullpll/noise/driven_noise_summary.json':'driven_noise_summary.json',
 'fullpll/noise/retry_summary_boundary201n.json':'retry_summary_boundary201n.json',
 'fullpll/noise/fullpll_driven_pss_sb128_boundary201n_measurement.json':'fullpll_driven_pss_sb128_boundary201n_measurement.json',
 'fullpll/noise/fullpll_driven_pss_sb128_measurement.json':'fullpll_driven_pss_sb128_measurement.json',
 'fullpll/noise/fullpll_driven_local_sb128_measurement.json':'fullpll_driven_local_sb128_measurement.json',
 'fullpll/noise/fullpll_driven_band_sb128_measurement.json':'fullpll_driven_band_sb128_measurement.json',
 'fullpll/noise/fullpll_driven_band_sb192_measurement.json':'fullpll_driven_band_sb192_measurement.json',
 'fullpll/pfd/pfd_electrical_measurements.json':'pfd_electrical_measurements.json',
 'fullpll/cpphase/phase_measurements.json':'phase_measurements.json',
 'fullpll/cpphase/phase_extended_measurements.json':'phase_extended_measurements.json',
 'fullpll/cpfast/gate4_measurement.json':'gate4_measurement.json',
 'fullpll/cpfast/gate8_measurement.json':'gate8_measurement.json',
 'fullpll/cpfast/drain_measurement.json':'drain_measurement.json',
 'stage1_compute_revision_20261007.json':'stage1_compute_revision_20261007.json',
 'afc_compute_revision_20261007.json':'afc_compute_revision_20261007.json',
}
data={}
for src,name in files.items():
    p=project/'results'/src
    if p.is_file():
        data[name]=json.loads(p.read_text())
        helper.atomic_json(dest/name,data[name])
choice=data.get('biasopt_selected.json',{})
bias_state=data.get('biasopt_status.json',{})
if bias_state.get('stage')=='complete' and choice.get('verified') is True:
    source=helper.contained(project,Path(choice['netlist_path']))
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    rx_records=[]
    for p in (project/'results/receiverload').glob('rx*.json'):
        if p.name.endswith('.manifest.json'):continue
        r=json.loads(p.read_text())
        if r.get('source_sha256')==source_hash:rx_records.append(r)
    data['receiverload_all_cases.json']=sorted(rx_records,key=lambda r:r.get('case_id',''))
    helper.atomic_json(dest/'receiverload_all_cases.json',data['receiverload_all_cases.json'])
summary={'time_unix':time.time(),'project':str(project),'jobs':{},'cadence_processes':[]}
for name in ['biasopt','receiverload','rfvalidation','selectedstartup']:
    state=data.get(name+'_status.json',{})
    keys=['version','pid','stage','cases_recorded','cases_completed_or_resumed','current_case',
          'stage_completed','scheduled_cases','selected_name','final_screen_passed','error']
    summary['jobs'][name]={k:state[k] for k in keys if k in state}
    pid=state.get('pid')
    proc=Path('/proc/{}'.format(pid))
    try:
        argv=(proc/'cmdline').read_bytes().decode(errors='replace').split('\0')
        cwd=os.readlink(str(proc/'cwd'))
        summary['jobs'][name]['live_own_driver']=cwd==str(project) and any('run_background_' in a for a in argv)
    except OSError: summary['jobs'][name]['live_own_driver']=False
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        comm=(proc/'comm').read_text().strip()
        cwd=os.readlink(str(proc/'cwd'))
    except OSError: continue
    if comm in ['spectre','virtuoso','ocean','cdsMsgServer']:
        summary['cadence_processes'].append({'pid':int(proc.name),'comm':comm,'cwd':cwd,
            'own_project':cwd==str(project) or cwd.startswith(str(project)+'/pll_full/')})
for name in ['biasopt_v3_cases.json','rfvalidation_all_cases.json','receiverload_all_cases.json','selectedstartup_all_cases.json']:
    records=data.get(name,[])
    summary[name]={'total':len(records),'states':{state:sum(r.get('state')==state for r in records)
                    for state in ['completed','failed','running','interrupted']}}
summary['recent_bias_cases']=[{'id':r['case_id'],'state':r['state'],'failure':r.get('failure')}
                            for r in data.get('biasopt_v3_cases.json',[])[-2:]]
helper.atomic_json(dest/'resume_live_status_20261007.json',summary)
print(json.dumps(summary))
