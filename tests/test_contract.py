"""Supplemental internal invariants, exercised using the installed package."""
import json
import subprocess
from conftest import invoke


def test_invalid_cross_fields_cannot_serialize(installed_cli,repo,git_env):
    _,r=invoke(installed_cli,[repo],env=git_env)
    r['coverage']['worktrees_observed']=0
    script='import json,sys;from orion_worktree_report.report import render;render(json.load(sys.stdin),True)'
    p=subprocess.run([str(installed_cli.parent/'python'),'-I','-c',script],input=json.dumps(r).encode(),capture_output=True,env=git_env)
    assert p.returncode!=0 and b'internal_contract' in p.stderr
    assert not p.stdout


def test_owned_deadline_and_generic_internal_failure(installed_cli,repo,git_env):
    script='''import os,sys
from orion_worktree_report import cli,git_read
reader=git_read.Git()
reader.deadline=0
try:
 reader.run(None,"--version")
except git_read.ReadError as e:
 if e.code!="scan_deadline":raise
else:raise AssertionError("deadline ignored")
def fail(roots):raise RuntimeError("synthetic hidden diagnostic")
cli.scan=fail
sys.argv=["orion-worktree-report","--json","scan","--repo",sys.argv[1]]
raise SystemExit(cli.main())
'''
    p=subprocess.run([str(installed_cli.parent/'python'),'-I','-c',script,str(repo)],capture_output=True,env=git_env)
    r=json.loads(p.stdout)
    assert p.returncode==70 and r['problems'][0]['code']=='internal_error'
    assert b'hidden diagnostic' not in p.stdout+p.stderr
