"""Internal consistency checks before a result can leave the command."""
import base64


CODES = frozenset('invalid_invocation git_missing unsupported_git_version repository_unavailable checkout_unavailable git_failed git_timeout command_output_limit status_parse_error state_changed worktree_limit path_limit overlap_limit index_limit config_limit scan_deadline output_limit internal_error unsupported_repository_feature'.split())
FEATURES = frozenset('bare content_filter included_config submodule sparse split_index partial_clone unproven_read_effect'.split())


def require(condition):
    if not condition:
        raise ValueError('internal_contract')


def path(raw):
    require(isinstance(raw, dict) and set(raw) == {'path_b64', 'path_utf8'})
    value = base64.b64decode(raw['path_b64'], validate=True)
    require(base64.b64encode(value).decode() == raw['path_b64'])
    try:
        label = value.decode('utf-8')
    except UnicodeDecodeError:
        label = None
    require(raw['path_utf8'] == label)
    return value


def validate(r):
    require(r['interface_version'] == 1 and r['authority'] == 'none')
    if r['command'] == 'version':
        require(r['exit'] == 0)
        return
    require(r['command'] == 'scan' and r['ignore_policy'] == 'repository-only')
    require(r['scope'] == 'registered-worktrees/dirty-paths')
    c = r['coverage']
    repos = {x['repository_id']: x for x in r['repositories']}
    trees = {x['worktree_id']: x for x in r['worktrees']}
    require(len(repos) == len(r['repositories']) and len(trees) == len(r['worktrees']))
    for x in r['inputs']:
        path(x['root'])
        require(x['repository_id'] is None or x['repository_id'] in repos)
        require((x['repository_id'] is None) == (x['problem'] is not None))
        if x['problem'] is not None:
            require(x['problem']['code'] in CODES)
            if x['problem']['code'] == 'unsupported_repository_feature':
                require(x['problem']['feature'] in FEATURES)
    for x in repos.values():
        path(x['common_directory'])
        require(x['discovery_state'] in ('observed', 'changed', 'unavailable'))
    observed = 0
    for x in trees.values():
        path(x['root'])
        require(x['repository_id'] in repos)
        if x['observation_state'] == 'observed':
            observed += 1
            require(x['head']['state'] in ('commit', 'unborn'))
            require((x['head']['oid'] is None) == (x['head']['state'] == 'unborn'))
            if x['head']['branch'] is not None:
                path(x['head']['branch'])
            require(len(x['dirty_paths']) <= 4096)
            require(len({path(p) for p in x['dirty_paths']}) == len(x['dirty_paths']))
            for rename in x['renames']:
                require(rename['kind'] in ('rename', 'copy'))
                require(rename['source'] in x['dirty_paths'] and rename['destination'] in x['dirty_paths'])
        else:
            require(x['observation_state'] in ('changed', 'unavailable', 'unsupported'))
            require(x['head'] is None and x['dirty_paths'] is None and x['renames'] is None)
    require(c['worktrees_observed'] == observed and c['worktrees_unavailable'] == len(trees)-observed)
    require(c['registered_worktrees'] is None or c['registered_worktrees'] == len(trees))
    require(c['repositories_discovered'] == sum(x['discovery_state'] == 'observed' for x in repos.values()))
    require(c['repositories_selected'] >= len(repos))
    seen = set()
    require(len(r['overlaps']) <= 1000)
    for overlap in r['overlaps']:
        pair = overlap['worktree_ids']
        require(len(pair) == 2 and pair == sorted(set(pair)))
        require(overlap['id'] not in seen)
        seen.add(overlap['id'])
        path(overlap['path'])
        for key in pair:
            tree = trees[key]
            require(tree['observation_state'] == 'observed' and tree['repository_id'] == overlap['repository_id'])
            require(overlap['path'] in tree['dirty_paths'])
    for p in r['problems']:
        require(p['code'] in CODES)
        if p['code'] == 'unsupported_repository_feature':
            require(p['feature'] in FEATURES)
        else:
            require('feature' not in p)
    if c['status'] == 'complete':
        require(observed > 0 and not r['problems'] and c['registered_worktrees'] == observed)
        require(c['repositories_selected'] == c['repositories_discovered'])
        require((r['exit'], r['conclusion']) == ((1, 'overlap_observed') if r['overlaps'] else (0, 'no_overlap_observed')))
    elif c['status'] == 'partial':
        require(observed > 0 and bool(r['problems']) and r['exit'] == 3)
        require(r['conclusion'] == ('overlap_observed' if r['overlaps'] else 'indeterminate'))
    else:
        require(c['status'] == 'unavailable' and r['exit'] in (2, 4, 70))
        require(observed == 0 and not r['overlaps'] and bool(r['problems']) and r['conclusion'] == 'indeterminate')
