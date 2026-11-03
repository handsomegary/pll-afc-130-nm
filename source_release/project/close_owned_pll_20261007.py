"""Stop only identity-verified processes in our PLL project; retain results."""
import json
import os
from pathlib import Path
import signal
import time

project = Path('@PROJECT_ROOT@')
assert Path.cwd().resolve() == project
root = str(project)
uid = os.getuid()
script_names = set([
    'run_background_bias_opt.py', 'run_background_receiver_load.py',
    'run_background_rf_validation.py', 'run_background_selected_startup.py',
    'run_pll_full_units_20261007.py',
    'run_driven_pll_noise_20261007.py',
    'run_loaded_pn30_check_20261007.py',
])
actions = []

def inspect(pid):
    p = Path('/proc') / str(pid)
    try:
        stat = (p / 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'uid': p.stat().st_uid,
                'start_ticks': stat[19], 'ppid': int(stat[1]),
                'comm': (p / 'comm').read_text().strip(),
                'argv': [a.decode(errors='replace') for a in
                         (p / 'cmdline').read_bytes().split(b'\0') if a],
                'cwd': os.readlink(str(p / 'cwd'))}
    except (OSError, ValueError):
        return None

def inventory():
    return [r for p in Path('/proc').iterdir() if p.name.isdigit()
            for r in [inspect(p.name)] if r]

def own_driver(r):
    return (r['uid'] == uid and r['cwd'] == root and
            any(Path(a).name in script_names for a in r['argv']))

def own_simulator(r):
    return (r['uid'] == uid and (r['cwd'] == root or r['cwd'].startswith(root+'/pll_full/')) and
            r['comm'] in ['spectre', 'ocean'] and
            any(a.startswith(root + '/netlists/') or a.startswith(root+'/pll_full/') for a in r['argv']))

def own_gui(r):
    return (r['uid'] == uid and r['comm'] == 'virtuoso' and
            r['cwd'] == root and root + '/cds.lib' in r['argv'])

def identical(a, b):
    return b is not None and all(a[k] == b[k] for k in
                                ['pid', 'uid', 'start_ticks', 'argv', 'cwd'])

def send(r, sig, reason):
    if not identical(r, inspect(r['pid'])):
        return
    try:
        os.kill(r['pid'], sig)
    except ProcessLookupError:
        return
    actions.append({'pid': r['pid'], 'comm': r['comm'],
                    'signal': sig.name, 'reason': reason})

before = inventory()
drivers = [r for r in before if own_driver(r)]
guis = [r for r in before if own_gui(r)]
manifest = json.loads((project / 'results/resume_pending_launch_latest.json').read_text())
expected = {r['pid']: r for r in manifest['drivers'] if 'pid' in r}
for r in drivers:
    if r['pid'] in expected:
        e = expected[r['pid']]
        assert r['start_ticks'] == e['process_start_ticks']
        assert r['argv'][1:] == e['argv'][1:]
        assert Path(r['argv'][0]).name == Path(e['argv'][0]).name == 'python3'

for r in drivers:
    send(r, signal.SIGTERM, 'Verified own PLL driver; allow result/status cleanup')
for r in guis:
    send(r, signal.SIGTERM, 'Verified own PLL Virtuoso cds.lib')

time.sleep(6)
for r in inventory():
    if own_simulator(r):
        send(r, signal.SIGTERM, 'Explicit own-project netlist and cwd')
    elif r['uid'] == uid and r['comm'] == 'cdsMsgServer' and any(
            'virtuoso' + str(g['pid']) in a for g in guis for a in r['argv']):
        send(r, signal.SIGTERM, 'Helper explicitly belongs to closed own Virtuoso')

time.sleep(4)
for r in inventory():
    if own_driver(r) or own_simulator(r) or own_gui(r):
        send(r, signal.SIGKILL, 'Verified own-process remainder after graceful stop')
time.sleep(1)
after = inventory()
remaining = [r for r in after if own_driver(r) or own_simulator(r) or own_gui(r)]
others = []
for r in before:
    if r['comm'] in ['spectre', 'virtuoso', 'ocean', 'cdsMsgServer'] and not (
            own_driver(r) or own_simulator(r) or own_gui(r)):
        current = inspect(r['pid'])
        others.append({'pid': r['pid'], 'comm': r['comm'], 'cwd': r['cwd'],
                       'identity_unchanged': identical(r, current),
                       'signal_sent_by_this_script': any(a['pid'] == r['pid'] for a in actions)})
report = {'time_unix': time.time(), 'project': root, 'actions': actions,
          'own_processes_remaining': remaining, 'other_sessions': others,
          'saved_results_retained': True, 'vm_shutdown_issued': False,
          'restart_authorized': False}
dest = project / 'results/session_shutdown_20261007.json'
dest.write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
assert not remaining, 'Own PLL processes remain; inspect before any broader action'
