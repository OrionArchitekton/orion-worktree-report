import os
import shutil
import subprocess
import time
import pytest
from conftest import git, invoke


def test_missing_registration_preserves_positive(installed_cli,repo,linked,tmp_path,git_env):
    for root in linked:(root/'shared.txt').write_text('changed\n')
    missing=tmp_path/'missing'
    git(repo,'worktree','add','--detach',missing,env=git_env)
    shutil.rmtree(missing)
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==3 and r['conclusion']=='overlap_observed',r
    assert r['coverage']['registered_worktrees']==4
    assert r['coverage']['worktrees_observed']==3 and r['coverage']['worktrees_unavailable']==1
    assert next(w for w in r['worktrees'] if w['root']['path_utf8']==str(missing))['dirty_paths'] is None


def test_unknown_repository_never_fabricates_zero(installed_cli,repo,tmp_path,git_env):
    p,r=invoke(installed_cli,[repo,tmp_path/'absent'],env=git_env)
    assert p.returncode==3 and r['coverage']['registered_worktrees'] is None
    assert r['coverage']['repositories_selected']==2
    assert r['conclusion']=='indeterminate'


@pytest.mark.parametrize('fault,code',[
    ('sys.stderr.write("synthetic secret diagnostic");sys.exit(128)','git_failed'),
    ('sys.stdout.buffer.write(b"? ../escape\\0");sys.exit(0)','status_parse_error'),
    ('sys.stdout.buffer.write(b"? truncated");sys.exit(0)','status_parse_error'),
    ('sys.stdout.buffer.write(b"x"*(2*1024*1024+1));sys.exit(0)','command_output_limit'),
    ('sys.stderr.buffer.write(b"x"*(64*1024+1));sys.exit(0)','command_output_limit'),
    ('time.sleep(20)','git_timeout'),
])
def test_owned_git_failures(installed_cli,repo,wrap_git,fault,code):
    env=wrap_git('if "status" in args:\n    '+fault)
    start=time.monotonic();p,r=invoke(installed_cli,[repo],env=env)
    assert p.returncode==4 and r['conclusion']=='indeterminate',r
    assert code in {e['code'] for e in r['problems']}
    assert b'synthetic secret diagnostic' not in p.stdout+p.stderr
    assert time.monotonic()-start<12


@pytest.mark.parametrize('surface',['status','index','head','config','registrations'])
def test_detected_drift_invalidates_scope(installed_cli,repo,linked,wrap_git,tmp_path,surface):
    marker=tmp_path/'marker'
    # Change one owned fixture after its first status read, or registration list.
    triggers='"worktree" in args and "list" in args' if surface=='registrations' else '"status" in args'
    mutation={
      'status': '(Path(root)/"appeared").touch()',
      'index': '(Path(root)/".git"/"index").touch(); (Path(root)/"new").touch(); subprocess.run([REAL,"-C",root,"add","new"],check=True)',
      'head': 'subprocess.run([REAL,"-C",root,"symbolic-ref","HEAD","refs/heads/alternate"],check=True)',
      'config': 'subprocess.run([REAL,"-C",root,"config","core.filemode","false"],check=True)',
      'registrations': 'subprocess.run([REAL,"-C",root,"worktree","lock",TARGET],check=True)',
    }[surface]
    import shutil
    mutation=mutation.replace('REAL',repr(shutil.which('git'))).replace('TARGET',repr(str(linked[0])))
    body='if '+triggers+' and root=='+repr(str(repo))+' and not Path('+repr(str(marker))+').exists():\n    result=subprocess.run(['+repr(shutil.which('git'))+',*args],capture_output=True)\n    Path('+repr(str(marker))+').touch()\n    '+mutation+'\n    sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr);sys.exit(result.returncode)'
    p,r=invoke(installed_cli,[repo],env=wrap_git(body))
    assert p.returncode==(4 if surface in ('head','registrations') else 3),r
    assert r['conclusion']=='indeterminate'
    assert 'state_changed' in {e['code'] for e in r['problems']}
    assert r['coverage']['status']==('unavailable' if surface in ('head','registrations') else 'partial')


def test_missing_and_old_git(installed_cli,repo,git_env,wrap_git):
    p,r=invoke(installed_cli,[repo],env={**git_env,'PATH':''})
    assert p.returncode==4 and r['problems'][0]['code']=='git_missing'
    env=wrap_git('if "--version" in args:\n    print("git version 2.42.0");sys.exit(0)')
    p,r=invoke(installed_cli,[repo],env=env)
    assert p.returncode==4 and r['problems'][0]['code']=='unsupported_git_version'
    p,r=invoke(installed_cli,env={**git_env,'PATH':''},args=['version'])
    assert p.returncode==0


def test_owned_descendant_stopped_without_touching_unrelated(installed_cli,repo,wrap_git,tmp_path):
    pidfile=tmp_path/'descendant-pid'
    import sys
    # The wrapper deliberately closes its pipes after spawning a sleeping descendant.
    body='if "--version" in args:\n    c=subprocess.Popen(['+repr(sys.executable)+',"-c","import time; time.sleep(30)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n    Path('+repr(str(pidfile))+').write_text(str(c.pid))\n    print("git version 2.43.0");sys.exit(0)'
    unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    try:
        p,r=invoke(installed_cli,[repo],env=wrap_git(body))
        assert p.returncode==0,r
        pid=int(pidfile.read_text())
        stat='/proc/'+str(pid)+'/stat'
        assert not os.path.exists(stat) or open(stat).read().split()[2]=='Z'
        assert unrelated.poll() is None
    finally:
        unrelated.terminate();unrelated.wait()


def test_broken_output_is_unsuccessful(installed_cli,repo,git_env):
    p=subprocess.Popen([str(installed_cli),'--json','scan','--repo',str(repo)],env=git_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    p.stdout.close()
    assert p.wait(timeout=10)!=0
    assert b'Traceback' not in p.stderr.read()


def test_failed_final_discovery_does_not_claim_detected_change(installed_cli,repo,wrap_git,tmp_path):
    marker=tmp_path/'registration-read'
    body='if "worktree" in args and "list" in args:\n    if Path('+repr(str(marker))+').exists():sys.exit(128)\n    Path('+repr(str(marker))+').touch()'
    p,r=invoke(installed_cli,[repo],env=wrap_git(body))
    assert p.returncode==4,r
    assert r['worktrees'][0]['observation_state']=='unavailable'
    assert {e['code'] for e in r['problems']}=={'git_failed'}


def test_every_input_keeps_its_resolution_problem(installed_cli,repo,tmp_path,git_env):
    p,r=invoke(installed_cli,[repo],env={**git_env,'PATH':''})
    assert p.returncode==4 and r['coverage']['repositories_selected']==1
    assert len(r['inputs'])==1 and r['inputs'][0]['problem']['code']=='git_missing'
    from conftest import git
    filtered=tmp_path/'filtered';git(tmp_path,'clone','--no-hardlinks',repo,filtered,env=git_env)
    git(filtered,'config','filter.demo.clean','cat',env=git_env)
    p,r=invoke(installed_cli,[repo,filtered,tmp_path/'missing'],env=git_env)
    assert p.returncode==3
    assert r['inputs'][0]['problem'] is None
    assert r['inputs'][1]['problem']=={'code':'unsupported_repository_feature','feature':'content_filter'}
    assert r['inputs'][2]['problem']['code']=='git_failed'
