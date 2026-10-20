import json, os, subprocess, sys
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def installed_cli(tmp_path_factory):
    selected = os.environ.get("WORKTREE_REPORT_TEST_BINARY")
    if selected:
        return Path(selected)
    root = Path(__file__).resolve().parents[1]
    target = tmp_path_factory.mktemp("installed")
    import importlib.metadata
    installer_pin = next(line.split(' --hash=')[0] for line in (root/'requirements-test.lock').read_text().splitlines() if line.startswith('pip=='))
    assert 'pip=='+importlib.metadata.version('pip') == installer_pin, 'Use the reviewed installer lock'
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(target)], check=True)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(target/"wheels"), str(root)], check=True, capture_output=True)
    subprocess.run([sys.executable, "-I", "-m", "pip", "--python", str(target/"bin/python"), "install", "--no-index", "--no-deps", *map(str,(target/"wheels").glob("*.whl"))], check=True, capture_output=True)
    return target/"bin/orion-worktree-report"

@pytest.fixture
def git_env():
    env={k:v for k,v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    env.update(GIT_CONFIG_GLOBAL="/dev/null",GIT_CONFIG_SYSTEM="/dev/null",GIT_CONFIG_NOSYSTEM="1",GIT_OPTIONAL_LOCKS="0")
    return env

def git(root,*args,env=None):
    return subprocess.check_output(["git","-C",str(root),*map(str,args)],env=env,stderr=subprocess.PIPE)

@pytest.fixture
def repo(tmp_path,git_env):
    root=tmp_path/"repo";root.mkdir()
    git(root,"init","-b","main",env=git_env)
    git(root,"config","user.name","Synthetic fixture",env=git_env)
    git(root,"config","user.email","fixture@example.invalid",env=git_env)
    (root/"shared.txt").write_text("base\n")
    git(root,"add",".",env=git_env);git(root,"commit","-m","base",env=git_env)
    return root

@pytest.fixture
def linked(repo,tmp_path,git_env):
    paths=[]
    for n in ["a","b"]:
        p=tmp_path/"group"/n;p.parent.mkdir(exist_ok=True)
        git(repo,"worktree","add","-b",n,p,"main",env=git_env);paths.append(p)
    return paths

def invoke(binary,roots=(),*,env=None,args=None):
    argv=[str(binary),"--json",*(args if args is not None else ["scan",*[v for p in roots for v in ("--repo",str(p))]])]
    p=subprocess.run(argv,env=env,capture_output=True,timeout=75)
    return p,json.loads(p.stdout)

@pytest.fixture
def wrap_git(tmp_path,git_env):
    import shutil
    real = shutil.which('git')
    def make(body):
        bindir=tmp_path/'tools';bindir.mkdir(exist_ok=True)
        script=bindir/'git'
        script.write_text('#!'+sys.executable+'\nimport os,sys,time,signal,subprocess\nfrom pathlib import Path\nargs=sys.argv[1:]\nroot=args[args.index("-C")+1] if "-C" in args else None\n'+body+'\nos.execv('+repr(real)+', ['+repr(real)+',*args])\n')
        script.chmod(0o700)
        return {**git_env,'PATH':str(bindir)+os.pathsep+git_env['PATH']}
    return make
