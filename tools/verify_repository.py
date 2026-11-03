#!/usr/bin/env python3
"""Check the publication inventory and historical result bindings offline.

This is a repository guard, not a simulator or an electrical qualification.
No process models, prior personal paths, private credentials, raw waveforms,
or archive files belong in the tracked publication inventory.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys


HEX_SHA = re.compile(r'^[0-9a-f]{64}$')
INCLUDES = re.compile(r'^\s*(?:include|ahdl_include)\s+"([^\"]+)"', re.MULTILINE)
MOS = re.compile(r'^M\w+\s+\([^\n]+\)\s+(?:n12|p12)\s+w=[0-9.]+u\s+l=[0-9.]+u\s*$', re.MULTILINE)
PRIVATE_PATH = re.compile(r'(?:[A-Za-z]:[/\\](?:Users|Documents and Settings)[/\\]|/(?:home|Users)/[^\s"<>]+)')
PRIVATE_TARGET = 'config/process_models.local.scs'
REPORT_PDFS = {'report/pll130-afc.pdf', 'report/atlas/gallery.pdf'}
AUTHORED_EDA_FILES = {
    'source_release/project/cds.lib',
    'source_release/project/pll_full/analog/pll130_analog.va',
    'source_release/project/pll_full/digital/benches/afc_test_source.va',
    'source_release/project/pll_full/digital/pll130_afc_handoff.va',
    'source_release/project/pll_full/digital/pll130_digital_va.va',
}
BLOCKED_SUFFIXES = {'.lib', '.va', '.vams', '.pem', '.key', '.p12', '.pfx', '.raw',
                    '.zip', '.7z', '.rar', '.gz', '.pdf', '.so', '.dll', '.exe', '.db'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def electrical_body_sha(text):
    """LF-normalized nonblank lines, excluding full comments and includes.

    All executable whitespace is preserved, including trailing whitespace.
    The resulting nonempty line sequence ends in one LF.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or INCLUDES.match(line):
            continue
        lines.append(line)
    return hashlib.sha256(('\n'.join(lines) + '\n').encode('utf-8')).hexdigest()


def repository_path(root, name):
    value = Path(name)
    if value.is_absolute() or '..' in value.parts or not value.parts:
        raise ValueError('Unsafe repository path: ' + str(name))
    unresolved = root / value
    if unresolved.is_symlink():
        raise ValueError('A provenance path cannot refer to a symbolic link.')
    path = unresolved.resolve()
    path.relative_to(root)
    if '.git' in path.relative_to(root).parts:
        raise ValueError('A provenance path cannot refer to Git internals.')
    return path


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def git_command(root, *arguments):
    try:
        result = subprocess.run(['git', '-C', str(root)] + list(arguments),
                                capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result if result.returncode == 0 else None


def publication_files(root):
    result = git_command(root, 'rev-parse', '--show-toplevel')
    is_own_git = result is not None and Path(result.stdout.decode().strip()).resolve() == root
    if is_own_git:
        files = git_command(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
        if files is None:
            raise ValueError('Cannot obtain the Git publication inventory.')
        names = [value.decode('utf-8') for value in files.stdout.split(b'\0') if value]
        tracked = git_command(root, 'ls-files', '--cached', '-z')
        tracked_names = {value.decode('utf-8') for value in tracked.stdout.split(b'\0') if value}
        return sorted(set(names)), tracked_names, True
    names = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if '.git' in parts or '__pycache__' in parts or parts[0] == 'runs' or name == PRIVATE_TARGET:
            continue
        names.append(name)
    return sorted(names), set(), False


def equal(actual, expected, description):
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError('Non-numeric claim: ' + description)
        if not math.isclose(actual, expected, rel_tol=1e-14, abs_tol=0.0):
            raise ValueError('Recorded claim mismatch: ' + description)
    elif actual != expected:
        raise ValueError('Recorded claim mismatch: ' + description)


def verify_results(root, entries):
    summary = read_json(root / 'results' / 'nominal_tt.json')
    by_path = {entry['path']: entry for entry in entries}
    ledgers = {}
    for key in ['afc_on', 'afc_off', 'weak_clamp_regression']:
        item = summary[key]
        path = repository_path(root, item['measurement_file'])
        ledger = read_json(path)
        provenance = ledger['publication_provenance']
        if provenance.get('public_sources_not_resimulated') is not True:
            raise ValueError('Historical evidence must retain the public-copy simulation limitation.')
        original_sha = provenance['original_json_sha256']
        if not HEX_SHA.fullmatch(original_sha):
            raise ValueError('Invalid original measurement digest.')
        entry = by_path[item['measurement_file']]
        equal(entry['original_sha256'], original_sha, key + ' original measurement binding')
        if 'measurement_original_sha256' in item:
            equal(item['measurement_original_sha256'], original_sha, key + ' summary measurement binding')
        ledgers[key] = ledger
    on, off, weak = [ledgers[key] for key in ['afc_on', 'afc_off', 'weak_clamp_regression']]
    selected = summary['afc_on']
    equal(selected['code'], on['handoff']['final_code'], 'AFC selected code')
    equal(selected['code'], 29, 'historical selected case')
    equal(selected['locked'], on['locked'], 'AFC overall qualification')
    equal(on['afc_success'], True, 'AFC handoff success')
    equal(on['simulator_electrical_pass'], True, 'AFC electrical qualification')
    equal(on['fine_loop']['locked'], True, 'AFC fine-loop capture')
    equal(selected['tail_frequency_Hz'], on['fine_loop']['final_frequency_Hz'], 'AFC tail frequency')
    equal(selected['afc_enable_to_lock_s'], on['fine_loop']['lock_time_s'] - on['handoff']['afc_enable_time_s'],
          'AFC enable-to-lock duration')
    equal(selected['locked_tail_power_W'], on['power']['locked_tail']['branches']['total_current']['average_power_W'],
          'AFC locked-tail supply power')
    equal(selected['bench_original_sha256'], on['bench_evidence']['sha256'], 'AFC original bench binding')
    equal(selected['bench_original_sha256'], by_path['circuits/benches/pll_afc_on.scs']['original_sha256'],
          'AFC published bench provenance')
    if on['handoff']['clamp_max_error_V'] > on['configuration']['clamp_tolerance_V']:
        raise ValueError('The selected historical clamp case failed its fixed tolerance.')
    disabled = summary['afc_off']
    equal(disabled['locked'], off['loop']['locked'], 'AFC-off bounded capture result')
    equal(disabled['locked'], False, 'AFC-off no-capture result')
    equal(disabled['observation_end_s'], off['observation_interval_s'][1], 'AFC-off observation boundary')
    equal(disabled['observation_end_s'], 6.5e-6, 'AFC-off bounded observation interval')
    equal(disabled['tail_frequency_Hz'], off['loop']['final_frequency_Hz'], 'AFC-off tail frequency')
    equal(disabled['bench_original_sha256'], off['bench_sha256'], 'AFC-off original bench binding')
    equal(disabled['bench_original_sha256'], by_path['circuits/benches/pll_afc_off.scs']['original_sha256'],
          'AFC-off published bench provenance')
    equal(off['power']['enable_to_lock'], None, 'AFC-off unknown energy to lock')
    equal(off['power']['locked_tail'], None, 'AFC-off unknown locked-tail power')
    equal(weak['afc_success'], False, 'Weak-clamp regression preserved failure')
    equal(weak['locked'], False, 'Weak-clamp overall qualification remains false')
    equal(weak['simulator_electrical_pass'], False, 'Weak-clamp electrical failure')
    if weak['handoff']['clamp_max_error_V'] <= weak['configuration']['clamp_tolerance_V']:
        raise ValueError('The failed weak-clamp regression no longer retains its failing voltage excursion.')
    for loop in [on['fine_loop'], off['loop'], weak['fine_loop']]:
        equal(loop['physical_noise_jitter_s'], None, 'Physical noise jitter remains unmeasured')
    return {'selected_code': selected['code'], 'historical_nominal_capture': selected['locked'],
            'bounded_off_no_capture': not disabled['locked'], 'weak_clamp_failure_preserved': True,
            'public_sources_resimulated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--forbid-token', default=''.join(chr(value) for value in [115, 109, 105, 99]),
                        help='Optional additional naming token to exclude, case-insensitively')
    args = parser.parse_args()
    root = args.root.resolve()
    files, tracked, own_git = publication_files(root)
    if not files:
        raise ValueError('The publication inventory is empty.')
    if PRIVATE_TARGET in tracked:
        raise ValueError('The local model adapter is tracked.')
    ignore_path = root / '.gitignore'
    if not ignore_path.is_file():
        raise ValueError('The repository must define its private/runtime exclusions in .gitignore.')
    ignore_rules = {line.strip().lstrip('/') for line in ignore_path.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')}
    if not ({PRIVATE_TARGET, 'config/*.local.scs'} & ignore_rules):
        raise ValueError('The local model adapter must be ignored explicitly.')
    if not {'runs/', 'runs'} & ignore_rules:
        raise ValueError('Simulation runs must be ignored.')
    if own_git and git_command(root, 'check-ignore', '--no-index', PRIVATE_TARGET) is None:
        raise ValueError('Git does not ignore the local model adapter.')
    forbidden = args.forbid_token.casefold()
    for name in files:
        path = repository_path(root, name)
        if not name.isascii():
            raise ValueError('Non-ASCII publication filename: ' + name)
        if forbidden and forbidden in name.casefold():
            raise ValueError('Excluded naming token found in a publication filename.')
        if name == PRIVATE_TARGET or name.startswith('runs/'):
            raise ValueError('Private model/runtime file included in the publication inventory: ' + name)
        allowed_artifact = name in AUTHORED_EDA_FILES or name in REPORT_PDFS
        if (path.suffix.lower() in BLOCKED_SUFFIXES and not allowed_artifact) or path.name.startswith(('id_rsa', 'id_ed25519')):
            raise ValueError('Model, binary, archive, raw, or credential file included: ' + name)
        if path.is_symlink() or not path.is_file():
            raise ValueError('The publication inventory must contain ordinary files: ' + name)
        if path.stat().st_size > 30 * 1024 * 1024:
            raise ValueError('Unexpected large publication file: ' + name)
        data = path.read_bytes()
        if name in REPORT_PDFS:
            if not data.startswith(b'%PDF-') or not data.rstrip().endswith(b'%%EOF'):
                raise ValueError('Expected a compiled report PDF.')
            continue  # Binary output is bound to its digest below.
        if not data.isascii() or b'\0' in data:
            raise ValueError('Publication text must be ASCII English: ' + name)
        text = data.decode('ascii')
        if forbidden and forbidden in text.casefold():
            raise ValueError('Excluded naming token found in publication content: ' + name)
        if PRIVATE_PATH.search(text):
            raise ValueError('Personal absolute path found in publication content: ' + name)
        if re.search(r'^-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----$', text, re.MULTILINE):
            raise ValueError('Private key material found in publication content: ' + name)
        if path.suffix == '.scs' and re.search(r'^\s*model\s+\w+', text, re.MULTILINE):
            raise ValueError('Process model cards are not part of this publication: ' + name)
    manifest = read_json(root / 'provenance' / 'manifest.json')
    equal(manifest['recorded_simulation_status'], 'historical_source_bound_results_not_new_public_copy_simulation',
          'Publication simulation status')
    equal(manifest['private_model_files_included'], False, 'Private model exclusion')
    entries = manifest['entries']
    names = [entry['path'] for entry in entries]
    if not entries or len(names) != len(set(names)):
        raise ValueError('Manifest paths must be nonempty and unique.')
    electrical = []
    for entry in entries:
        path = repository_path(root, entry['path'])
        if entry['path'] not in files:
            raise ValueError('A manifest entry is missing from the publication inventory: ' + entry['path'])
        if not HEX_SHA.fullmatch(entry['publication_sha256']):
            raise ValueError('Invalid publication digest: ' + entry['path'])
        if entry.get('original_sha256') is not None and not HEX_SHA.fullmatch(entry['original_sha256']):
            raise ValueError('Invalid original digest: ' + entry['path'])
        equal(sha(path), entry['publication_sha256'], entry['path'] + ' publication digest')
        body_sha = entry.get('electrical_body_sha256')
        if body_sha is not None:
            if path.suffix != '.scs' or not HEX_SHA.fullmatch(body_sha):
                raise ValueError('Invalid electrical body entry: ' + entry['path'])
            equal(electrical_body_sha(path.read_text()), body_sha, entry['path'] + ' electrical body')
            electrical.append(path)
    if len(electrical) != 6:
        raise ValueError('The selected circuit publication must bind exactly six electrical sources.')
    afc = [path for path in electrical if path.relative_to(root).as_posix() == 'circuits/blocks/afc_mos.scs']
    if len(afc) != 1 or len(MOS.findall(afc[0].read_text())) != 7135:
        raise ValueError('The selected flat AFC source must contain exactly 7135 ordinary MOS instances.')
    adapter = (root / PRIVATE_TARGET).resolve()
    for path in electrical:
        for include in INCLUDES.findall(path.read_text()):
            target = Path(include)
            if target.is_absolute():
                raise ValueError('A published circuit include must use a relative path.')
            resolved = (path.parent / target).resolve()
            resolved.relative_to(root)
            if resolved == adapter:
                continue
            relative = resolved.relative_to(root).as_posix()
            if not resolved.is_file() or relative not in names:
                raise ValueError('Unbound project include: ' + relative)
    claims = verify_results(root, entries)
    print(json.dumps({'status': 'passed', 'verification_scope': 'Offline publication guard only',
                      'publication_files_checked': len(files), 'manifest_entries_checked': len(entries),
                      'electrical_sources_checked': len(electrical), 'AFC_MOS_instances': 7135,
                      'inventory_from_git': own_git, 'recorded_results': claims}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Verification failed: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
