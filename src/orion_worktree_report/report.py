"""One-shot observations. Internal module, not a supported Python API."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from . import __version__
from .git_read import Git, ReadError
from .contract import validate


def path_value(raw):
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = None
    return {'path_b64': base64.b64encode(raw).decode('ascii'), 'path_utf8': text}


def identity(tag, *parts):
    return 'sha256:' + hashlib.sha256(json.dumps([tag, *parts], ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def empty_report(command='scan'):
    return {'interface_version': 1, 'package_version': __version__, 'command': command,
            'scan_id': str(uuid.uuid4()), 'started_at': stamp(), 'finished_at': None,
            'authority': 'none', 'scope': 'registered-worktrees/dirty-paths',
            'ignore_policy': 'repository-only', 'inputs': [], 'repositories': [],
            'worktrees': [], 'overlaps': [], 'problems': [],
            'coverage': {'status': 'unavailable', 'repositories_selected': 0,
                         'repositories_discovered': 0, 'registered_worktrees': None,
                         'worktrees_observed': 0, 'worktrees_unavailable': 0},
            'conclusion': 'indeterminate', 'exit': 4}


def problem(report, error, scope, rid=None, wid=None):
    p = {'scope': scope, 'repository_id': rid, 'worktree_id': wid, 'code': error.code}
    if error.feature:
        p['feature'] = error.feature
    report['problems'].append(p)


def input_problem(error):
    return {'code': error.code, **({'feature': error.feature} if error.feature else {})}


def failure(code, exit_code=4):
    r = empty_report()
    problem(r, ReadError(code), 'selection')
    r.update(finished_at=stamp(), exit=exit_code)
    return r


def scan(roots):
    if not roots or len(roots) > 8 or any(not os.path.isabs(p) or len(os.fsencode(p)) > 4096 for p in roots):
        return failure('invalid_invocation', 2)
    r = empty_report()
    canonical = [os.path.realpath(os.fsencode(p)) for p in roots]
    r['inputs'] = [{'root': path_value(os.fsencode(p)), 'repository_id': None, 'problem': None} for p in roots]
    try:
        git = Git()
    except ReadError as e:
        problem(r, e, 'selection')
        for row in r['inputs']:
            row['problem'] = input_problem(e)
        r['coverage']['repositories_selected'] = len(set(canonical))
        r['finished_at'] = stamp()
        return r
    repos, unresolved = {}, set()
    discovery_failed = False
    for root, row in zip(canonical, r['inputs']):
        try:
            common = git.identify(root)
            rid = identity('repository', path_value(common)['path_b64'])
            row['repository_id'] = rid
            repos.setdefault(common, (rid, root))
        except ReadError as e:
            row['problem'] = input_problem(e)
            discovery_failed = True
            if root not in unresolved:
                problem(r, e, 'selection')
                unresolved.add(root)
    r['coverage']['repositories_selected'] = len(repos) + len(unresolved)
    total = 0
    for common, (rid, root) in sorted(repos.items()):
        rr = {'repository_id': rid, 'common_directory': path_value(common), 'discovery_state': 'observed'}
        r['repositories'].append(rr)
        try:
            before = git.registrations(root)
            total += len(before)
            if total > 64:
                raise ReadError('worktree_limit')
            for checkout, _ in before:
                wid = identity('worktree', rid, path_value(checkout)['path_b64'])
                row = {'worktree_id': wid, 'repository_id': rid, 'root': path_value(checkout),
                       'observation_state': 'unavailable', 'head': None, 'dirty_paths': None, 'renames': None}
                r['worktrees'].append(row)
                try:
                    if not os.path.isdir(checkout):
                        raise ReadError('checkout_unavailable')
                    if git.identify(checkout) != common:
                        raise ReadError('state_changed')
                    a, b = git.sample(checkout), git.sample(checkout)
                    if a != b:
                        raise ReadError('state_changed')
                    head = dict(a['head'])
                    branch = head.pop('branch_bytes')
                    head['branch'] = path_value(branch) if branch is not None else None
                    row.update(observation_state='observed', head=head, dirty_paths=[path_value(p) for p in a['paths']],
                               renames=[{'source': path_value(src), 'destination': path_value(dst), 'kind': kind} for src, dst, kind in a['renames']])
                except ReadError as e:
                    row['observation_state'] = 'changed' if e.code == 'state_changed' else 'unsupported' if e.feature else 'unavailable'
                    problem(r, e, 'worktree', rid, wid)
            if git.registrations(root) != before:
                raise ReadError('state_changed')
        except ReadError as e:
            rr['discovery_state'] = 'changed' if e.code == 'state_changed' else 'unavailable'
            discovery_failed = True
            problem(r, e, 'repository', rid)
            for row in r['worktrees']:
                if row['repository_id'] == rid:
                    row.update(observation_state='changed' if e.code == 'state_changed' else 'unavailable',
                               head=None, dirty_paths=None, renames=None)
    r['coverage']['repositories_discovered'] = sum(x['discovery_state'] == 'observed' for x in r['repositories'])
    observed = sum(x['observation_state'] == 'observed' for x in r['worktrees'])
    r['coverage'].update(worktrees_observed=observed, worktrees_unavailable=len(r['worktrees'])-observed,
                         registered_worktrees=None if discovery_failed else total)
    r['worktrees'].sort(key=lambda w: base64.b64decode(w['root']['path_b64']))
    overlap_overflow = False
    for i, a in enumerate(r['worktrees']):
        if time.monotonic() >= git.deadline:
            if not any(p['code'] == 'scan_deadline' for p in r['problems']):
                problem(r, ReadError('scan_deadline'), 'scan')
            break
        if overlap_overflow or a['observation_state'] != 'observed':
            continue
        for b in r['worktrees'][i+1:]:
            if b['observation_state'] != 'observed' or a['repository_id'] != b['repository_id']:
                continue
            shared = {p['path_b64'] for p in a['dirty_paths']} & {p['path_b64'] for p in b['dirty_paths']}
            for value in sorted(shared, key=base64.b64decode):
                if len(r['overlaps']) == 1000:
                    problem(r, ReadError('overlap_limit'), 'scan')
                    overlap_overflow = True
                    break
                pair = sorted((a['worktree_id'], b['worktree_id']))
                r['overlaps'].append({'id': identity('overlap', a['repository_id'], value, pair),
                                      'repository_id': a['repository_id'], 'worktree_ids': pair,
                                      'path': path_value(base64.b64decode(value))})
            if overlap_overflow:
                break
    r['overlaps'].sort(key=lambda x: (x['repository_id'], x['worktree_ids'], base64.b64decode(x['path']['path_b64'])))
    if observed:
        complete = not r['problems']
        r['coverage']['status'] = 'complete' if complete else 'partial'
        r['exit'] = (1 if r['overlaps'] else 0) if complete else 3
        r['conclusion'] = 'overlap_observed' if r['overlaps'] else 'no_overlap_observed' if complete else 'indeterminate'
    r['finished_at'] = stamp()
    return r


def render(r, structured):
    validate(r)
    chunks, size = [], 1
    for chunk in json.JSONEncoder(ensure_ascii=True, separators=(',', ':')).iterencode(r):
        size += len(chunk)  # ensure_ascii makes every character one UTF-8 byte.
        if size > 1048576:
            break
        chunks.append(chunk)
    if size > 1048576:
        r = failure('output_limit')
        raw = json.dumps(r, ensure_ascii=True, separators=(',', ':')) + '\n'
    else:
        raw = ''.join(chunks) + '\n'
    if structured:
        return raw, r['exit']
    lines = [f"coverage={r.get('coverage', {}).get('status', 'version')} conclusion={r.get('conclusion', 'version')} exit={r['exit']}"]
    if 'coverage' in r:
        lines.append(json.dumps({'coverage': r['coverage']}, ensure_ascii=True))
    lines += [json.dumps(x, ensure_ascii=True) for key in ('inputs', 'repositories', 'worktrees', 'overlaps', 'problems') for x in r.get(key, [])]
    if r['command'] == 'version':
        lines = [f"orion-worktree-report {__version__}; interface=1; authority=none"]
    text = '\n'.join(lines) + '\n'
    if len(text.encode('utf-8')) > 1048576:
        return render(failure('output_limit'), False)
    return text, r['exit']
