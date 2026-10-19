from conftest import invoke


def test_path_limit_is_not_clean(installed_cli, repo, git_env):
    for n in range(4097):
        (repo/f'file-{n}').touch()
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4,r['coverage']
    assert {e['code'] for e in r['problems']}=={'path_limit'}
    assert r['worktrees'][0]['dirty_paths'] is None
    assert r['conclusion']=='indeterminate'


def test_overlap_overflow_is_explicit(installed_cli, repo, linked, git_env):
    for root in linked:
        for n in range(1001):
            (root/f'file-{n}').touch()
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==3,r['coverage']
    assert r['coverage']['status']=='partial'
    assert len(r['overlaps'])==1000
    assert {e['code'] for e in r['problems']}=={'overlap_limit'}
    assert r['conclusion']=='overlap_observed'


def test_configuration_limit_is_aggregate(installed_cli,repo,git_env):
    from conftest import git
    git(repo,'config','extensions.worktreeConfig','true',env=git_env)
    with (repo/'.git/config').open('ab') as f:f.write(b'#'+b'x'*600000+b'\n')
    (repo/'.git/config.worktree').write_bytes(b'#'+b'x'*600000+b'\n')
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and 'config_limit' in {p['code'] for p in r['problems']},r['coverage']


def test_large_index_refused_before_index_commands(installed_cli,repo,git_env):
    with (repo/'.git/index').open('ab') as f:f.truncate(128*1024*1024+1)
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and {e['code'] for e in r['problems']}=={'index_limit'},r['problems']


def test_final_output_limit_uses_small_unavailable_result(installed_cli,repo,git_env):
    for n in range(3000):(repo/(str(n)+'x'*200)).touch()
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and len(p.stdout)<16384
    assert r['conclusion']=='indeterminate' and r['worktrees']==[]
    assert {e['code'] for e in r['problems']}=={'output_limit'}


def test_root_cap_is_before_dedup(installed_cli,repo,git_env):
    p,r=invoke(installed_cli,[repo]*9,env=git_env)
    assert p.returncode==2 and r['problems'][0]['code']=='invalid_invocation'


def test_registration_cap(installed_cli,repo,tmp_path,git_env):
    from conftest import git
    for n in range(64):git(repo,'worktree','add','--detach',tmp_path/f'w-{n}',env=git_env)
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and r['problems'][0]['code']=='worktree_limit',r
    assert r['coverage']['registered_worktrees'] is None
