"""Read-only AFC2009 saved-vector audit; Python 3.6+, stdlib only.

No simulator launch, no cadence session management, no source mutations.
PSF ASCII is streamed; only compact lock vectors and digital transitions are
retained. Engineering lock and deterministic residuals never become noise jitter.
Port names and counter/CDC contracts are supplied through --config-json.
"""
from __future__ import print_function
import argparse
from array import array
import bisect
import hashlib
import json
import math
from pathlib import Path
import re
import sys

MAX_RAW_BYTES = 512 * 1024 * 1024
LINE = re.compile(r'^"([^\"]+)"\s+(?:"[^\"]+"\s+)?'
                  r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(?:\s|$)')
DEFAULT_CONFIG = {
    'vdd_V': 1.2,
    'target_Hz': 3.2e9,
    'reference_Hz': 100e6,
    'calibration_Hz': 100e6,
    'clamp_V': 0.6,
    'clamp_tolerance_V': 0.03,
    'handoff_guard_s': 1e-9,
    'decision_settle_s': 1e-9,
    'minimum_done_to_fine_REF_clocks': 2,
    'analogs': {'out0': 'out0', 'out180': 'out180', 'ref': 'ref',
        'fb': 'fb', 'ctrl': 'ctrl', 'filter_mid': 'filter_mid',
        'vdd': 'vdd', 'total_current': 'VDD:p',
        'afc_current': 'VDDAFC:p', 'digital_current': 'VDDIG:p',
        'cp_current': 'VDDCP:p'},
    'digitals': {'enable': 'afc_enable', 'done': 'afc_done',
        'fail': 'afc_fail', 'fine_enable': 'fine_enable', 'hold': 'hold_all',
        'trial_arm': 'trial_arm', 'epoch_ack': 'epoch_ack',
        'ref_lead': 'ref_lead', 'ref_lag': 'ref_lag', 'divcal': 'divcal',
        'decision_valid': 'decision_valid', 'decision_slow': 'decision_slow',
        'decision_fast': 'decision_fast', 'update': 'code_update',
        'up': 'up', 'dn': 'dn', 'pfd_reset': 'rst'},
    'words': {'code': ['s0', 's1', 's2', 's3', 's4']},
    # These are audit parameters only. They never change a circuit decision.
    # Specify exact physical snapshot behavior before declaring sign proof.
    'counter_contract': None,
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def edges(t, values, threshold=0.0):
    return [t[i]+(threshold-values[i])*(t[i+1]-t[i])/(values[i+1]-values[i])
            for i in range(len(t)-1)
            if values[i] <= threshold < values[i+1]]


def frequency(edge, begin, end, minimum=10):
    first, last = bisect.bisect_left(edge, begin), bisect.bisect_right(edge, end)
    if last-first < minimum or edge[last-1] <= edge[first]:
        return None
    return (last-first-1)/(edge[last-1]-edge[first])


def interpolate(t, y, point):
    if point < t[0] or point > t[-1]:
        raise ValueError('Interpolation endpoint outside saved waveform.')
    index = bisect.bisect_left(t, point)
    if index == 0:
        return y[0]
    if index == len(t):
        return y[-1]
    fraction = (point-t[index-1])/(t[index]-t[index-1])
    return y[index-1]+fraction*(y[index]-y[index-1])


def integrate(t, y, begin, end):
    if end <= begin:
        raise ValueError('Integration interval is not positive.')
    a, b = bisect.bisect_right(t, begin), bisect.bisect_left(t, end)
    prior_t, prior_y = begin, interpolate(t, y, begin)
    total = 0.0
    for index in range(a, b):
        total += (t[index]-prior_t)*(y[index]+prior_y)*0.5
        prior_t, prior_y = t[index], y[index]
    total += (end-prior_t)*(interpolate(t, y, end)+prior_y)*0.5
    return total


def event_value(events, time, default=None):
    # Compact rows [time, value], already in time order.
    index = bisect.bisect_right([item[0] for item in events], time)-1
    return events[index][1] if index >= 0 else default


def read_saved_vectors(path, config, memory_mib=256):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > MAX_RAW_BYTES:
        raise ValueError('Missing raw or raw exceeds 512MiB read-only guard.')
    before = sha(path)
    analog_map = {actual: canonical for canonical, actual in config['analogs'].items()}
    digital_map = {actual: canonical for canonical, actual in config['digitals'].items()}
    words = config['words']
    bit_names = set(name for names in words.values() for name in names)
    selected = set(analog_map) | set(digital_map) | bit_names
    data = {'time': array('d')}
    digital = {key: {'levels': [], 'rising': [], 'falling': []}
               for key in config['digitals']}
    word_events = {key: [] for key in words}
    last_digital = {}
    prior_time = None
    prior_words = {}
    block = {}
    reading = False
    threshold = config['vdd_V']*0.5
    retained_budget = memory_mib * 1024 * 1024

    def commit(current):
        nonlocal prior_time
        if 'time' not in current:
            return
        time = current['time']
        if prior_time is not None and time <= prior_time:
            raise ValueError('Saved times must be strictly increasing.')
        data['time'].append(time)
        for actual, canonical in analog_map.items():
            if actual in current:
                if canonical not in data:
                    if len(data['time']) != 1:
                        raise ValueError('Analog signal appeared after first sample: '+actual)
                    data[canonical] = array('d')
                data[canonical].append(current[actual])
            elif canonical in data:
                raise ValueError('Missing saved analog sample: '+actual)
        for actual, canonical in digital_map.items():
            if actual not in current:
                if canonical in last_digital:
                    raise ValueError('Missing saved digital sample: '+actual)
                continue
            value = current[actual]
            state = int(value > threshold)
            event = digital[canonical]
            previous = last_digital.get(canonical)
            if previous is None:
                event['levels'].append([time, state])
            elif state != previous[1]:
                old_voltage, old_state = previous
                crossing = prior_time+(threshold-old_voltage)*(time-prior_time)/(value-old_voltage)
                event['levels'].append([crossing, state])
                event['rising' if state else 'falling'].append(crossing)
            last_digital[canonical] = (value, state)
        for key, names in words.items():
            if all(name in current for name in names):
                value = sum(1 << bit for bit, name in enumerate(names)
                            if current[name] > threshold)
                if prior_words.get(key) != value:
                    word_events[key].append([time, value])
                    prior_words[key] = value
        prior_time = time
        # arrays plus overhead and all digital edge lists remain well below this
        # conservative estimate; reject before retaining an unbounded waveform.
        estimate = len(data['time']) * (len(analog_map)+4) * 8 * 1.4
        estimate += sum(len(v['levels'])*160 for v in digital.values())
        estimate += sum(len(v)*160 for v in word_events.values())
        if estimate > retained_budget:
            raise ValueError('Selected-vector memory estimate exceeds {}MiB guard; '
                             'reduce saved analogs or strobe density.'.format(memory_mib))

    with path.open(encoding='utf-8', errors='replace') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line == 'VALUE':
                reading = True
                continue
            if line == 'END':
                commit(block)
                block = {}
                break
            if not reading:
                continue
            match = LINE.match(line)
            if match is None:
                continue
            name = match.group(1)
            if name != 'time' and name not in selected:
                continue
            number = float(match.group(2))
            if not math.isfinite(number):
                raise ValueError('Nonfinite saved scalar: '+name)
            if name == 'time':
                commit(block)
                block = {'time': number}
            else:
                block[name] = number
    if block:
        commit(block)
    after = sha(path)
    if before != after:
        raise ValueError('Raw changed during read-only extraction.')
    if len(data['time']) < 20:
        raise ValueError('Insufficient transient samples.')
    for key, wave in data.items():
        if len(wave) != len(data['time']):
            raise ValueError('Saved analog vector length mismatch: '+key)
    return data, digital, word_events, {
        'raw_file': str(path), 'raw_sha256': before,
        'raw_bytes': path.stat().st_size, 'saved_samples': len(data['time']),
        'raw_unchanged_during_extraction': True,
        'memory_guard_MiB': memory_mib, 'raw_guard_bytes': MAX_RAW_BYTES,
        'reader': 'Streaming selected-scalar PSF ASCII; digital transition ledgers, '
                  'compact double analog vectors; no unbounded text load.'}


def engineering_lock(data, fine_enable, config):
    t = data['time']
    for name in ['out0', 'out180', 'ref', 'fb', 'ctrl']:
        if name not in data:
            raise ValueError('Engineering lock requires saved analog: '+name)
    diff = array('d', (a-b for a,b in zip(data['out0'],data['out180'])))
    out = edges(t, diff)
    ref, fb = edges(t, data['ref'],config['vdd_V']*.5), edges(t,data['fb'],config['vdd_V']*.5)
    if fine_enable is None:
        return {'locked': False, 'reason': 'No success-gated fine-enable edge.'}
    fbi = bisect.bisect_left(fb, fine_enable)
    if fbi >= len(fb) or not ref:
        return {'locked': False, 'reason': 'No feedback/reference edges after fine-enable.'}
    ri = min(bisect.bisect_left(ref, fb[fbi]),len(ref)-1)
    if ri and abs(ref[ri-1]-fb[fbi]) < abs(ref[ri]-fb[fbi]):
        ri -= 1
    count = min(len(fb)-fbi,len(ref)-ri)
    pair_time = fb[fbi:fbi+count]
    error = [fb[fbi+i]-ref[ri+i] for i in range(count)]
    hold = 500e-9
    phase_limit = 0.01/config['reference_Hz']
    target = config['target_Hz']
    last_bad = None
    good_windows = []
    for begin in pair_time:
        end = begin+hold
        if begin < fine_enable or end > t[-1] or end > pair_time[-1]:
            continue
        a,b = bisect.bisect_left(pair_time,begin),bisect.bisect_right(pair_time,end)
        phase = error[a:b]
        sa,sb = bisect.bisect_left(t,begin),bisect.bisect_right(t,end)
        span = diff[sa:sb]
        local = begin
        estimates = []
        while local+100e-9 <= end+1e-15:
            estimates.append(frequency(out,local,local+100e-9))
            local += 50e-9
        valid = bool(estimates and all(x is not None and abs(x/target-1)<=.001
                     for x in estimates) and len(phase)>=10
                     and max(phase)-min(phase)<=phase_limit
                     and span and max(span)-min(span)>=.05)
        if valid:
            good_windows.append(begin)
        else:
            last_bad = begin
    qualifying = [begin for begin in good_windows if last_bad is None or begin>last_bad]
    lock = qualifying[0] if qualifying else None
    tail = max(fine_enable,t[-1]-hold)
    tail_errors = error[bisect.bisect_left(pair_time,tail):]
    static = None
    if tail_errors:
        mean = sum(tail_errors)/len(tail_errors)
        period = 1/config['reference_Hz']
        static = (mean+.5*period)%period-.5*period
    return {'locked':lock is not None,'lock_time_s':lock,
        'lock_after_fine_enable_s':lock-fine_enable if lock is not None else None,
        'final_frequency_Hz':frequency(out,tail,t[-1]),
        'final_ctrl_mean_V':integrate(t,data['ctrl'],tail,t[-1])/(t[-1]-tail),
        'final_differential_vpp_V':max(diff[bisect.bisect_left(t,tail):])-min(diff[bisect.bisect_left(t,tail):]),
        'feedback_minus_reference_principal_static_offset_s':static,
        'physical_noise_jitter_s':None,
        'definition':{'frequency_tolerance_fraction':.001,'frequency_window_s':100e-9,
            'frequency_stride_s':50e-9,'hold_s':hold,'unwrapped_phase_pp_max_s':phase_limit,
            'differential_vpp_min_V':.05,'all_later_complete_hold_windows_must_pass':True},
        'scope':'No stochastic noise. Engineering acquisition only; static phase offset '
            'and deterministic/numerical ripple are not physical jitter.'}


def digital_intervals(events, begin, end):
    points = [begin]+[item[0] for item in events if begin<item[0]<end]+[end]
    return [(a,b,event_value(events,a)) for a,b in zip(points,points[1:])]


def audit_handoff(data,digital,words,config):
    t = data['time']
    def rises(key):
        return digital.get(key,{}).get('rising',[])
    def levels(key):
        return digital.get(key,{}).get('levels',[])
    def value(key,point):
        return event_value(levels(key),point)
    enable = rises('enable')[0] if rises('enable') else None
    done = next((point for point in rises('done') if enable is not None and point>=enable),None)
    fine = next((point for point in rises('fine_enable') if enable is not None and point>=enable),None)
    fail = next((point for point in rises('fail') if enable is not None and point>=enable),None)
    guard = config['handoff_guard_s']
    violations = []
    required = ['enable','done','fail','fine_enable','hold']
    absent = [key for key in required if not levels(key)]
    if absent:
        violations.append('Missing mandatory observation ports: '+','.join(absent))
    if done is not None and fine is not None:
        minimum = config.get('minimum_done_to_fine_REF_clocks',0)/config['reference_Hz']
        if fine-done < minimum-guard:
            violations.append('Fine-enable precedes required post-Done REF delay.')
    boundary_times = sorted({point for key in required for point,_ in levels(key)})
    for point in boundary_times:
        check = min(point+guard,t[-1])
        en,dn,fl,fi,ho = (value(key,check) for key in required)
        if dn==1 and fl==1:
            violations.append('done and fail both high at {:.12g}s'.format(check))
        if fi==1 and not (en==1 and dn==1 and fl==0):
            violations.append('fine_enable lacks success gate at {:.12g}s'.format(check))
        if fl==1 and (fi!=0 or ho!=1):
            violations.append('Failure did not keep fine loop off and clamp held.')
    code = words.get('code',[])
    if not code:
        violations.append('No saved code word.')
    if fine is not None:
        release_code = event_value(code,fine+guard)
        changes = [item for item in code if item[0]>fine+guard and item[1]!=release_code]
        if changes:
            violations.append('Code changed after fine-enable.')
    else:
        release_code = None
        changes = []
    clamp_points = [i for i,point in enumerate(t)
                    if enable is not None and point>=enable+guard
                    and (fine is None or point<=fine-guard)
                    and value('hold',point)==1]
    clamp_error = max(abs(data['ctrl'][i]-config['clamp_V']) for i in clamp_points) if clamp_points and 'ctrl' in data else None
    clamp_ref_error = max(abs(data['ctrl'][i]-data['vhold'][i]) for i in clamp_points) if clamp_points and 'ctrl' in data and 'vhold' in data else None
    clamp_mid_ref_error = max(abs(data['filter_mid'][i]-data['vhold'][i]) for i in clamp_points) if clamp_points and 'filter_mid' in data and 'vhold' in data else None
    if clamp_error is None:
        violations.append('Clamp waveform or held interval unavailable.')
    elif clamp_error>config['clamp_tolerance_V']:
        violations.append('Held Vctrl exceeds specified clamp tolerance.')
    for pulse_name in ['up','dn']:
        pulse_levels = levels(pulse_name)
        if not pulse_levels or enable is None:
            continue
        held_end = fine-guard if fine is not None else t[-1]
        for begin,end,state in digital_intervals(pulse_levels,enable+guard,held_end):
            if state==1 and end>begin:
                violations.append('CP '+pulse_name+' asserted while AFC held control.')
    success = bool(not violations and enable is not None and done is not None and fine is not None
                   and done>=enable and fine>=done and value('done',t[-1])==1
                   and value('fail',t[-1])==0 and value('fine_enable',t[-1])==1
                   and value('hold',t[-1])==0)
    failure_safe = bool(fail is not None and value('fail',t[-1])==1
        and value('done',t[-1])==0 and value('fine_enable',t[-1])==0
        and value('hold',t[-1])==1 and not violations)
    return {'afc_enable_time_s':enable,'afc_done_time_s':done,'fine_enable_time_s':fine,
        'afc_fail_time_s':fail,'afc_duration_s':done-enable if done is not None and enable is not None else None,
        'done_to_fine_enable_s':fine-done if done is not None and fine is not None else None,
        'selected_code':release_code,'final_code':code[-1][1] if code else None,
        'code_changes_after_fine_enable':changes,'clamp_max_error_V':clamp_error,
        'clamp_ctrl_minus_actual_vhold_max_V':clamp_ref_error,
        'clamp_filter_mid_minus_actual_vhold_max_V':clamp_mid_ref_error,
        'clamp_target_V':config['clamp_V'],'guard_s':guard,
        'success_handoff':success,'failure_safe':failure_safe,
        'violations':sorted(set(violations))}


def power_metrics(data,begin,end):
    if begin is None or end is None or end<=begin:
        return None
    t = data['time']
    if 'vdd' not in data:
        return {'available':False,'reason':'No actual saved supply voltage.'}
    branches = {}
    for canonical in ['total_current','afc_current','digital_current','cp_current']:
        if canonical not in data:
            continue
        power = array('d',(-v*i for v,i in zip(data['vdd'],data[canonical])))
        energy = integrate(t,power,begin,end)
        branches[canonical] = {'energy_J':energy,'average_power_W':energy/(end-begin)}
    return {'available':'total_current' in branches,'interval_s':[begin,end],
        'duration_s':end-begin,'branches':branches,
        'total_already_includes_AFC':True,
        'scope':'Saved instantaneous supply integral with exact-boundary linear interpolation. '
            'AFC branch is diagnostic; never added to total again. External ideal reference '
            'clock generator and unspecified physical bias-generator implementations excluded.'}


def audit_round_edges(digital,words,config):
    arms = digital.get('trial_arm',{}).get('rising',[])
    acknowledgments = digital.get('epoch_ack',{}).get('rising',[])
    decisions = digital.get('decision_valid',{}).get('rising',[])
    decision_falls = digital.get('decision_valid',{}).get('falling',[])
    clk = {key:digital.get(key,{}).get('rising',[])
           for key in ['ref_lead','ref_lag','divcal']}
    contract = config.get('counter_contract')
    rounds = []
    for index, arm in enumerate(arms):
        end = arms[index+1] if index+1<len(arms) else float('inf')
        epoch = next((x for x in acknowledgments if arm<=x<end),None)
        decision = next((x for x in decisions if arm<=x<end),None)
        captured = next((x for x in decision_falls if decision is not None
                         and decision<x<end),None)
        item = {'trial_index':index,'arm_time_s':arm,'epoch_ack_time_s':epoch,
            'decision_time_s':decision,'decision_fall_time_s':captured,
            'raw_edge_counts':{},'sign_proof':None,
            'trial_code':event_value(words.get('code',[]),arm+config['decision_settle_s'])}
        first_div = next((point for point in clk['divcal'] if arm<=point<end),None)
        reference = digital.get('reference',{})
        phase_signal = digital.get('phase_select',{}).get('levels',[])
        phase_point = (epoch if epoch is not None else first_div)
        captured_phase = event_value(phase_signal,phase_point+config['decision_settle_s']) if phase_point is not None else None
        bracket = {'first_div_time_s':first_div,'captured_phase':captured_phase,
                   'bracket_proof':None,'initial_lead_credit_expected':1,
                   'first_div_credit_expected':1}
        if first_div is not None and captured_phase in [0,1] and reference.get('levels'):
            lead_edges = reference.get('rising' if captured_phase else 'falling',[])
            lag_edges = reference.get('falling' if captured_phase else 'rising',[])
            li = bisect.bisect_right(lead_edges,first_div)-1
            gi = bisect.bisect_left(lag_edges,first_div)
            leading = lead_edges[li] if li>=0 else None
            lagging = lag_edges[gi] if gi<len(lag_edges) else None
            bracket['preceding_lead_edge_s']=leading
            bracket['following_lag_edge_s']=lagging
            if leading is not None and lagging is not None:
                bracket['bracket_proof']=leading<=first_div<=lagging
                aperture = min(first_div-leading,lagging-first_div)
                bracket['nearest_REF_aperture_s']=aperture
                bracket['tie_aperture_below_1ps']=aperture<1e-12
                bracket['scope']='Saved edge timing and captured phase only. No '
                bracket['scope']+='metastability or setup/hold signoff from this bracket.'
        item['first_edge_bracket']=bracket
        if epoch is not None and decision is not None:
            for key,edge in clk.items():
                if digital.get(key,{}).get('levels'):
                    a,b = bisect.bisect_left(edge,epoch),bisect.bisect_right(edge,decision)
                    item['raw_edge_counts'][key]=b-a
                else:
                    item['raw_edge_counts'][key]=None
            # Exact CDC/snapshot detail is mandatory. Raw edge ledgers alone
            # cannot justify comparing hardware counters with unequal latency.
            if contract:
                lag_word = contract.get('lag_word','n_lag')
                lead_word = contract.get('lead_word','n_lead')
                div_word = contract.get('div_word','n_div')
                anchor = captured if contract.get('snapshot_anchor')=='decision_falling' else decision
                if anchor is None:
                    item['snapshot_unavailable_reason']='Missing stable latch-capture anchor.'
                    rounds.append(item)
                    continue
                sampling = anchor+contract.get('snapshot_delay_s',config['decision_settle_s'])
                nlag,nlead,ndiv = (event_value(words.get(key,[]),sampling)
                                  for key in [lag_word,lead_word,div_word])
                slow = event_value(digital.get('decision_slow',{}).get('levels',[]),sampling)
                fast = event_value(digital.get('decision_fast',{}).get('levels',[]),sampling)
                margin = contract.get('decision_guard_counts',0)
                item['observed_counter_snapshot']={'n_lag':nlag,'n_lead':nlead,'n_div':ndiv,
                    'sampling_time_s':sampling,'guard_counts':margin,'slow':slow,'fast':fast}
                if all(value is not None for value in [nlag,nlead,ndiv,slow,fast]):
                    item['sign_proof']=bool((slow==1 and fast==0 and nlag-ndiv>=margin)
                        or (slow==0 and fast==1 and ndiv-nlead>=margin)
                        or (slow==0 and fast==0))
                    if slow==0 and fast==0:
                        item['nearband_needs_window_qualification']=True
                    item['sign_proof_scope']='One frozen decision snapshot supports direction. '
                    item['sign_proof_scope']+='Two consecutive CDC observations and metastability '
                    item['sign_proof_scope']+='are not established by one saved snapshot alone.'
        rounds.append(item)
    return {'rounds':rounds,'counter_contract':contract,
        'scope':'Raw independently reconstructed edge counts and saved counter snapshots. '
            'No sign-valid claim when exact CDC/count-epoch contract or saved bits absent.'}


def measure(raw,config,memory_mib):
    data,digital,words,evidence = read_saved_vectors(raw,config,memory_mib)
    handoff = audit_handoff(data,digital,words,config)
    loop = engineering_lock(data,handoff['fine_enable_time_s'],config)
    enable,done,fine = (handoff[key] for key in ['afc_enable_time_s','afc_done_time_s','fine_enable_time_s'])
    lock = loop.get('lock_time_s')
    tail = max(fine if fine is not None else data['time'][0],data['time'][-1]-500e-9)
    result = {'version':'afc2009-saved-vector-audit-v1','simulator_started':False,
        'source_evidence':evidence,'configuration':config,'handoff':handoff,
        'fine_loop':loop,'round_edge_audit':audit_round_edges(digital,words,config),
        'afc_handoff_success':handoff['success_handoff'],
        'afc_candidate_qualified_by_actual_fine_capture':bool(handoff['success_handoff'] and loop.get('locked')),
        'afc_success':bool(handoff['success_handoff'] and loop.get('locked')),
        'locked':bool(handoff['success_handoff'] and loop.get('locked')),
        'overall_lock_after_afc_enable_s':lock-enable if lock is not None and enable is not None else None,
        'power':{'afc_enable_to_done':power_metrics(data,enable,done),
                 'fine_enable_to_lock':power_metrics(data,fine,lock),
                 'afc_enable_to_lock':power_metrics(data,enable,lock),
                 'locked_tail':power_metrics(data,tail,data['time'][-1])},
        'digital_transition_ledgers':digital,'word_transition_ledgers':words,
        'physical_noise_jitter_s':None,
        'scope':'Engineering AFC/PLL acquisition. Circuit implementation scope must be '
            'established by source dependency audit; this waveform reader cannot infer '
            'MOS implementation from node names. No noise jitter, PEX or silicon claim.'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--config-json',type=Path)
    parser.add_argument('--memory-mib',type=int,choices=[256,512],default=256)
    args = parser.parse_args()
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if args.config_json:
        custom = json.loads(args.config_json.read_text(encoding='utf-8-sig'))
        # Mapping objects replace defaults, so disabled debug ports remain absent.
        config.update(custom)
    try:
        result = measure(args.raw,config,args.memory_mib)
    except Exception as error:
        result = {'version':'afc2009-saved-vector-audit-v1','simulator_started':False,
            'measurement_state':'blocked_by_saved_vector_or_resource_guard',
            'measurement_error':repr(error),'circuit_failure_inferred':False,
            'physical_noise_jitter_s':None}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output.resolve()),'locked':result.get('locked'),
        'afc_success':result.get('afc_success'),'measurement_error':result.get('measurement_error')}))
    return 0 if result.get('locked') else 2


if __name__=='__main__':
    sys.exit(main())
