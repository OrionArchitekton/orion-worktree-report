"""Fail-closed member inspection and clean installed-artifact acceptance.

Run using the locked development interpreter, after building into dist/.
No deployment, upload, package index or estate integration is performed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser


def inspect_artifact(artifact, allowed, kind):
    """Validate all entries, including directory/link/duplicate/traversal hazards."""
    if kind == 'wheel':
        with zipfile.ZipFile(artifact) as archive:
            entries = [(x.filename, x.file_size, stat.S_IFMT(x.external_attr >> 16)) for x in archive.infolist()]
            if any(mode not in (0, stat.S_IFREG) for _, _, mode in entries):
                raise ValueError('nonregular_archive_member')
    elif kind == 'sdist':
        with tarfile.open(artifact, 'r:gz') as archive:
            members = archive.getmembers()
            if any(not (x.isfile() or x.isdir()) for x in members):
                raise ValueError('nonregular_archive_member')
            entries = [(x.name, x.size, stat.S_IFDIR if x.isdir() else stat.S_IFREG) for x in members]
    else:
        raise ValueError('unknown_artifact_kind')
    names, all_names, size = [], set(), 0
    for name, count, mode in entries:
        parts = name.split('/')
        if name.startswith('/') or any(x in ('', '.', '..') for x in parts) or '\\' in name or name in all_names:
            raise ValueError('unsafe_archive_member')
        all_names.add(name)
        if mode != stat.S_IFDIR:
            names.append(name); size += count
        elif not any(x.startswith(name+'/') for x in allowed):
            raise ValueError('unapproved_archive_directory')
    if set(names) != set(allowed) or size > 4*1024*1024:
        raise ValueError('archive_member_mismatch')
    return sorted(names)


def run(argv, *, cwd=None, env=None, log):
    p = subprocess.run(list(map(str,argv)), cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=180)
    log.write_bytes(p.stdout)
    if p.returncode:
        raise ValueError('acceptance_command_failed: '+log.name)
    return p


def verify(root, artifacts, output):
    root, artifacts, output = root.resolve(), artifacts.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root/'release-members.json').read_text())
    import importlib.metadata
    tools = {}
    for line in (root/'requirements-test.lock').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, expected = line.split(' --hash=')[0].split('==')
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise ValueError('unreviewed_acceptance_tool: '+name)
        tools[name] = actual
    wheel = artifacts/'orion_worktree_report-0.1.0-py3-none-any.whl'
    sdist = artifacts/'orion_worktree_report-0.1.0.tar.gz'
    allowed_wheel = manifest['wheel']
    allowed_sdist = ['orion_worktree_report-0.1.0/'+x for x in manifest['source']+manifest['sdist_generated']]
    members = {'wheel': inspect_artifact(wheel,allowed_wheel,'wheel'),
               'sdist': inspect_artifact(sdist,allowed_sdist,'sdist')}
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read('orion_worktree_report-0.1.0.dist-info/METADATA'))
        if metadata['Name'] != 'orion-worktree-report' or metadata['Version'] != '0.1.0' or metadata.get_all('Requires-Dist'):
            raise ValueError('unexpected_package_metadata')
        for name in members['wheel']:
            if '/licenses/' in name:
                if archive.read(name) != (root/Path(name).name).read_bytes():
                    raise ValueError('license_notice_mismatch')
    # Only neutral source and fixtures are allowed. Reject private installation markers.
    for artifact in (wheel, sdist):
        with (zipfile.ZipFile(artifact) if artifact == wheel else tarfile.open(artifact,'r:gz')) as archive:
            names = archive.namelist() if artifact == wheel else [m.name for m in archive.getmembers() if m.isfile()]
            for name in names:
                raw = archive.read(name) if artifact == wheel else archive.extractfile(name).read()
                if any(marker in raw for marker in (b'/home/'+b'ori'+b'on', b'.clau'+b'de/scripts', b'BEGIN '+b'PRIVATE KEY')):
                    raise ValueError('private_archive_marker')
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel,sdist)}
    report = {'artifacts':digests,'members':members,'installed_acceptance':[],
              'acceptance_tools':tools, 'installer':{'pip':tools['pip'],'target_bootstrap':'without-pip'},
              'python':sys.version.split()[0], 'git':subprocess.check_output(['git','--version']).decode().strip()}
    # Environment never inherits a source import path or another installed binary override.
    clean_env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR')}
    with tempfile.TemporaryDirectory(prefix='worktree-report-acceptance-') as scratch:
        temp = Path(scratch)
        extracted = temp/'extracted'; extracted.mkdir()
        with tarfile.open(sdist,'r:gz') as archive:
            # Validated exact regular members above; no extraction of arbitrary input.
            for member in archive.getmembers():
                if member.isfile():
                    dest = extracted/member.name; dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(archive.extractfile(member).read())
        source = extracted/'orion_worktree_report-0.1.0'
        # Build the extracted sdist with the same locked backend in the verifier interpreter.
        rebuilt = temp/'rebuilt'; rebuilt.mkdir()
        run([sys.executable,'-I','-m','build','--wheel','--no-isolation','--outdir',rebuilt,source],log=output/'sdist-build.log',env=clean_env)
        rebuilt_wheel = rebuilt/wheel.name
        inspect_artifact(rebuilt_wheel, allowed_wheel, 'wheel')
        # The rebuilt package code and notices must agree; timestamps/RECORD may differ.
        with zipfile.ZipFile(wheel) as a, zipfile.ZipFile(rebuilt_wheel) as b:
            for name in allowed_wheel:
                if not name.endswith('/RECORD'):
                    if a.read(name) != b.read(name):
                        raise ValueError('sdist_wheel_source_disagreement')
        for label, selected, test_root in [('wheel',wheel,root),('sdist',rebuilt_wheel,source)]:
            target=temp/label
            run([sys.executable,'-m','venv','--without-pip',target],log=output/(label+'-venv.log'),env=clean_env)
            binary=target/'bin/orion-worktree-report'
            installer=[sys.executable,'-I','-m','pip','--python',target/'bin/python']
            run([*installer,'install','--no-index','--no-deps',selected],log=output/(label+'-install.log'),env=clean_env)
            test_env={**clean_env,'WORKTREE_REPORT_TEST_BINARY':str(binary),'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
            result=run([sys.executable,'-I','-m','pytest','-q','-p','no:cacheprovider',test_root/'tests'],cwd=temp,env=test_env,log=output/(label+'-tests.log'))
            run([*installer,'check'],log=output/(label+'-pip-check.log'),env=clean_env)
            report['installed_acceptance'].append({'origin':label,'artifact_sha256':hashlib.sha256(selected.read_bytes()).hexdigest(),
                'exit':result.returncode,'summary':result.stdout.decode().strip().splitlines()[-1]})
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','artifacts':digests,'installed_acceptance':report['installed_acceptance']}))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--artifacts',type=Path,default=Path('dist'))
    p.add_argument('--output',type=Path,default=Path('.private/release-verification'))
    args=p.parse_args()
    verify(Path(__file__).resolve().parents[1],args.artifacts,args.output)


if __name__=='__main__':
    main()
