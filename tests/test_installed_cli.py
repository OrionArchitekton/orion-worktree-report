from conftest import invoke

def test_select_and_account(installed_cli,repo,linked,git_env):
    p,r=invoke(installed_cli,[repo,linked[0]],env=git_env)
    assert p.returncode==0, r
    assert r["coverage"]["status"]=="complete"
    assert r["coverage"]["repositories_selected"]==1
    assert r["coverage"]["repositories_discovered"]==1
    assert r["coverage"]["worktrees_observed"]==3
    assert r["conclusion"]=="no_overlap_observed"

from conftest import git
import os
import base64
import pytest

def test_version(installed_cli,git_env):
    p,r=invoke(installed_cli,env=git_env,args=["version"])
    assert p.returncode==0 and r["interface_version"]==1 and r["authority"]=="none"

@pytest.mark.parametrize("mode",["unborn","detached"])
def test_head_states(installed_cli,repo,tmp_path,git_env,mode):
    if mode=="unborn":
        repo=tmp_path/"unborn";repo.mkdir();git(repo,"init","-b","fresh",env=git_env)
    else:git(repo,"checkout","--detach",env=git_env)
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==0,r
    h=r["worktrees"][0]["head"]
    assert h["state"]==("unborn" if mode=="unborn" else "commit")
    assert (h["branch"] is None)==(mode=="detached")

@pytest.mark.parametrize("args",[["scan","--repo","relative"],["cleanup"],["scan"],["scan","--repo","/tmp/x","--apply"]])
def test_invalid_invocation(installed_cli,git_env,args):
    p,r=invoke(installed_cli,env=git_env,args=args)
    assert p.returncode==2 and r["conclusion"]=="indeterminate"

def test_exact_overlap(installed_cli,repo,linked,git_env):
    for root in linked:(root/"shared.txt").write_text("changed\n")
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==1,r
    assert r["coverage"]["status"]=="complete"
    assert len(r["overlaps"])==1
    assert base64.b64decode(r["overlaps"][0]["path"]["path_b64"])==b"shared.txt"

@pytest.mark.parametrize('args', [['--js','version'],['scan','--rep','/tmp/synthetic']])
def test_abbreviated_options_are_unknown(installed_cli,git_env,args):
    p,r=invoke(installed_cli,env=git_env,args=args)
    assert p.returncode==2,r
def test_runtime_environment_contains_only_reporter(installed_cli):
    import json, subprocess
    runtime = installed_cli.parent/'python'
    p = subprocess.run([str(runtime), '-I', '-c',
                        'import json,importlib.metadata as m; print(json.dumps(sorted(d.metadata["Name"] for d in m.distributions())))'],
                       capture_output=True, check=True)
    assert json.loads(p.stdout) == ['orion-worktree-report']


@pytest.mark.parametrize('missing_selection',[False,True])
def test_text_coverage_counts_match_json(installed_cli,repo,linked,tmp_path,git_env,missing_selection):
    import json, subprocess
    roots=[repo,tmp_path/'missing'] if missing_selection else [repo]
    p,r=invoke(installed_cli,roots,env=git_env)
    text=subprocess.run([str(installed_cli),'scan',*[v for root in roots for v in ('--repo',str(root))]],
                        env=git_env,capture_output=True,timeout=75)
    assert text.returncode==p.returncode
    rows=[json.loads(line) for line in text.stdout.decode().splitlines()[1:]]
    coverage=next((row['coverage'] for row in rows if 'coverage' in row),None)
    assert coverage==r['coverage']
    assert coverage['registered_worktrees']==(None if missing_selection else 3)
