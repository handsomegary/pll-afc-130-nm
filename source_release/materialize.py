#!/usr/bin/env python3
"""Verify the publication and bind archived sources to a fresh Linux run tree."""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INCLUDES = re.compile(r'^\s*(?:include|ahdl_include)\s+"([^"]+)"', re.MULTILINE)
TOKENS = re.compile(r'@[A-Z_]+@')
SAFE_PATH = re.compile(r'/[a-zA-Z0-9._/+:-]+\Z')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_sources():
    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='ascii'))
    index = json.loads((HERE / 'include_index.json').read_text(encoding='ascii'))
    included = []
    names = set()
    external = set()
    for item in manifest['files']:
        path = HERE / item['path']
        if path.resolve() != path or HERE not in path.parents or path in names:
            raise ValueError('Invalid or repeated source path: ' + str(path))
        names.add(path)
        data = path.read_bytes()
        if sha(data) != item['published_sha256']:
            raise ValueError('Source differs from release manifest: ' + item['path'])
        if path.suffix != '.scs':
            continue
        for target in INCLUDES.findall(data.decode('ascii')):
            if target.startswith('@TECH_ROOT@/'):
                external.add(target[len('@TECH_ROOT@/'):])
                kind = 'licensed_model'
            else:
                parent = HERE / 'project' if target.startswith('@PROJECT_ROOT@/') else path.parent
                local_name = target[len('@PROJECT_ROOT@/'):] if target.startswith('@PROJECT_ROOT@/') else target
                child = (parent / local_name).resolve()
                if HERE not in child.parents or not child.is_file():
                    raise ValueError('Missing local include: ' + target)
                kind = 'published_source'
            included.append({'source': item['path'], 'target': target, 'kind': kind})
    if included != index:
        raise ValueError('Include index differs from the published circuit sources')
    return manifest['files'], sorted(external)


def safe_absolute(value):
    normalized = Path(value).resolve().as_posix()
    if not SAFE_PATH.fullmatch(normalized):
        raise ValueError('Use a Linux absolute path with letters, digits and simple punctuation: ' + normalized)
    return normalized


def configure(args, files, models):
    if os.name != 'posix':
        raise ValueError('Configure the runnable design on its Linux simulation host')
    destination = Path(safe_absolute(args.output))
    if destination.exists() or destination == HERE or HERE in destination.parents:
        raise ValueError('Choose a new directory outside this publication')
    if not destination.parent.is_dir():
        raise ValueError('The parent directory must exist')
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', args.oa_library):
        raise ValueError('An OA library name must be a valid identifier')
    host = socket.gethostname()
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', host):
        raise ValueError('The guest hostname cannot be embedded safely')
    bindings = {
        '@PROJECT_ROOT@': destination.as_posix(), '@TECH_ROOT@': safe_absolute(args.tech_root),
        '@IC_ROOT@': safe_absolute(args.ic_root), '@SPECTRE_ROOT@': safe_absolute(args.spectre_root),
        '@TECH_LIBRARY@': args.oa_library, '@GUEST_HOST@': host,
    }
    tech = Path(bindings['@TECH_ROOT@'])
    missing = [s for s in models if not (tech / s).is_file()]
    if missing:
        raise ValueError('Missing licensed model inputs under the local technology root: ' + ', '.join(missing))
    history = json.loads((HERE / 'licensed_inputs.json').read_text(encoding='ascii'))
    for entry in history['files']:
        path = tech / entry['relative_path']
        if not path.is_file() or sha(path.read_bytes()) != entry['sha256']:
            raise ValueError('External model differs from the recorded selected run: ' + entry['relative_path'])
    if not (tech / args.oa_library).is_dir() or not (Path(bindings['@IC_ROOT@']) / 'share/cdssetup/cds.lib').is_file():
        raise ValueError('Check local OA library and IC startup library paths before configuring')
    if not (Path(bindings['@SPECTRE_ROOT@'])/'bin/spectre').is_file():
        raise ValueError('The configured Spectre installation lacks bin/spectre')
    staging = Path(tempfile.mkdtemp(prefix='.pll130-source-', dir=destination.parent))
    try:
        for item in files:
            rel = Path(item['path'])
            target = staging / (Path(*rel.parts[1:]) if rel.parts[0] == 'project' else rel)
            source = (HERE / rel).read_text(encoding='ascii')
            for label, value in bindings.items():
                source = source.replace(label, value)
            if TOKENS.search(source):
                raise ValueError('Unbound token in ' + str(rel))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='ascii', newline='\n') as handle:
                handle.write(source)
            if target.suffix in ('.sh', '.csh'):
                target.chmod(0o755)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print('Wrote configured source tree: ' + str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action')
    commands.add_parser('verify', help='Offline source digest and include checks')
    bind = commands.add_parser('configure', help='Prepare a fresh source tree on a licensed Linux host')
    bind.add_argument('--output', required=True)
    bind.add_argument('--tech-root', required=True)
    bind.add_argument('--ic-root', required=True)
    bind.add_argument('--spectre-root', required=True)
    bind.add_argument('--oa-library', required=True, help='Local OA library directory name under --tech-root')
    args = parser.parse_args()
    if not args.action:
        parser.error('Choose verify or configure')
    files, models = verify_sources()
    if args.action == 'verify':
        print(json.dumps({'verified_source_files': len(files), 'external_model_entries': models}))
    else:
        configure(args, files, models)


if __name__ == '__main__':
    main()
