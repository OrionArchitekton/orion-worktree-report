import hashlib
import os
import subprocess
import pytest
from conftest import git, invoke


def inventory(roots):
    result={}
    for root in roots:
        for parent, dirs, files in os.walk(root, followlinks=False):
            for name in dirs+files:
                full=os.path.join(parent,name)
                key=os.fsencode(full)
                st=os.lstat(full)
                result[key]=(st.st_mode, st.st_mtime_ns, st.st_ctime_ns, os.readlink(full) if os.path.islink(full) else
                             hashlib.sha256(open(full,'rb').read()).hexdigest() if os.path.isfile(full) else None)
    return result


def test_native_read_effects_and_environment_scrubbing(installed_cli,repo,linked,tmp_path,git_env):
    sentinel=tmp_path/'sentinel'
    hook=tmp_path/'monitor'
    hook.write_text('#!/bin/sh\nprintf called >> '+str(sentinel)+'\nexit 1\n');hook.chmod(0o700)
    git(repo,'config','core.fsmonitor',hook,env=git_env)
    git(repo,'config','credential.helper',hook,env=git_env)
    git(repo,'config','remote.origin.url','https://example.invalid/private',env=git_env)
    (linked[0]/'shared.txt').write_text('dirty\n')
    (linked[1]/'extra').touch()
    before=inventory([repo,*linked])
    trace=tmp_path/'trace';index=tmp_path/'redirected-index';obj=tmp_path/'objects';obj.mkdir()
    env={**git_env,'GIT_DIR':str(tmp_path/'wrong'),'GIT_WORK_TREE':str(tmp_path/'wrong'),
         'GIT_INDEX_FILE':str(index),'GIT_OBJECT_DIRECTORY':str(obj),
         'GIT_TRACE':str(trace),'GIT_TRACE2_EVENT':str(trace),
         'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.fsmonitor','GIT_CONFIG_VALUE_0':str(hook),
         'GIT_CONFIG_PARAMETERS':"'core.fsmonitor'='"+str(hook)+"'",'GIT_SSH_COMMAND':str(hook),
         'GIT_EXTERNAL_DIFF':str(hook),'GIT_PAGER':str(hook)}
    p,r=invoke(installed_cli,[repo],env=env)
    assert p.returncode==0,r
    assert before==inventory([repo,*linked])
    assert not sentinel.exists() and not trace.exists() and not index.exists() and not list(obj.iterdir())
    assert b'example.invalid/private' not in p.stdout+p.stderr


def test_clean_filter_refused_before_execution(installed_cli,repo,tmp_path,git_env):
    sentinel=tmp_path/'filter-called'
    hook=tmp_path/'filter'
    hook.write_text('#!/bin/sh\nprintf called >> '+str(sentinel)+'\ncat\n');hook.chmod(0o700)
    (repo/'.gitattributes').write_text('shared.txt filter=sentinel\n')
    git(repo,'config','filter.sentinel.clean',hook,env=git_env)
    # Same size forces ordinary status to compare through the configured driver.
    (repo/'shared.txt').write_text('edit\n')
    git(repo,'status','--porcelain=v2','-z',env=git_env)
    assert sentinel.exists(), 'Fixture did not prove the hazardous read effect'
    sentinel.unlink()
    before=inventory([repo])
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and r['problems'][0]['feature']=='content_filter',r
    assert not sentinel.exists() and inventory([repo])==before


@pytest.mark.parametrize('location', ['main', 'linked', 'worktree'])
def test_included_config_never_opened_before_refusal(installed_cli,repo,linked,tmp_path,git_env,location):
    outside = tmp_path/'not-selected.cfg'
    outside.write_bytes(b'#'+b'x'*(4*1024*1024)+b'\n')
    selected = repo if location == 'main' else linked[0]
    if location == 'worktree':
        git(repo,'config','extensions.worktreeConfig','true',env=git_env)
        git(selected,'config','--worktree','includeIf.gitdir:/**.path',outside,env=git_env)
    else:
        git(repo,'config','include.path',outside,env=git_env)
    trace = tmp_path/'config.trace'
    p = subprocess.run(['strace','-f','-yy','-s','0','-e','trace=openat,read',
                        '-o',str(trace),str(installed_cli),'--json','scan','--repo',str(selected)],
                       cwd=selected,env=git_env,capture_output=True,timeout=75)
    import json
    r = json.loads(p.stdout)
    assert p.returncode == 4 and r['problems'][0]['feature'] == 'included_config', r
    # No target open, including a zero-byte/failed read. Starting inside the
    # selected repository must not let the explicit-file config query discover it.
    assert str(outside) not in trace.read_text()


@pytest.mark.parametrize('feature',['bare','included_config','submodule','sparse','split_index','partial_clone'])
def test_unsupported_features_refused(installed_cli,repo,tmp_path,git_env,feature):
    if feature=='bare':
        repo=tmp_path/'bare';repo.mkdir();git(repo,'init','--bare',env=git_env)
    elif feature=='included_config':
        included=tmp_path/'included';included.write_text('[user]\n name = synthetic\n')
        git(repo,'config','include.path',included,env=git_env)
    elif feature=='submodule':
        oid=git(repo,'rev-parse','HEAD',env=git_env).strip().decode()
        git(repo,'update-index','--add','--cacheinfo','160000,'+oid+',sub',env=git_env)
    elif feature=='sparse':git(repo,'sparse-checkout','init','--cone',env=git_env)
    elif feature=='split_index':git(repo,'update-index','--split-index',env=git_env)
    elif feature=='partial_clone':git(repo,'config','remote.origin.promisor','true',env=git_env)
    before=inventory([repo])
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and r['conclusion']=='indeterminate',r
    assert r['problems'][0].get('feature')==feature,r
    assert inventory([repo])==before


def test_cold_installed_command_creates_no_cache_inside_selected_repo(installed_cli,git_env):
    import shutil
    # A dedicated installed environment can itself sit in a caller's repository.
    # Clear package bytecode to exercise cold startup; all setup precedes inventory.
    target=installed_cli.parent.parent
    package=target/'lib/python3.11/site-packages/orion_worktree_report'
    for cache in (target/'lib/python3.11/site-packages').rglob('__pycache__'):
        shutil.rmtree(cache)
    git(target,'init','-b','synthetic-effects',env=git_env)
    (target/'.git/info/exclude').write_text('*\n')
    try:
        before=inventory([target])
        p,r=invoke(installed_cli,[target],env=git_env)
        assert p.returncode==0,r
        assert inventory([target])==before, 'Cold command startup wrote inside the selected repository'
    finally:
        shutil.rmtree(target/'.git')


def test_command_catalog_is_observation_only(installed_cli,repo,wrap_git,tmp_path):
    import json
    trace=tmp_path/'command-catalog'
    body='with open('+repr(str(trace))+',"a") as f:\n    f.write(__import__("json").dumps(args)+"\\n")'
    p,r=invoke(installed_cli,[repo],env=wrap_git(body))
    assert p.returncode==0,r
    seen=[]
    for line in trace.read_text().splitlines():
        args=json.loads(line)
        if '-C' in args:tail=args[args.index('-C')+2:]
        else:
            # Global options precede setup-free version/config reads.
            pos=2
            while pos < len(args) and args[pos]=='-c':pos+=2
            tail=args[pos:]
        seen.append(tail[0])
        assert tail[0] in {'--version','rev-parse','symbolic-ref','config','worktree','ls-files','status'}
        if tail[0]=='worktree':assert tail==['worktree','list','--porcelain','-z']
        if tail[0]=='config':assert '--no-includes' in tail and '--name-only' in tail
        if tail[0]=='status':assert '--porcelain=v2' in tail and '-z' in tail
    assert {'--version','config','worktree','ls-files','status'}<=set(seen)


def test_unknown_mandatory_index_extension_refused(installed_cli,repo,git_env):
    index=repo/'.git/index';raw=index.read_bytes()[:-20]+b'demo'+bytes(4)
    index.write_bytes(raw+hashlib.sha1(raw).digest())
    before=inventory([repo])
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==4 and r['problems'][0]['feature']=='unproven_read_effect',r
    assert inventory([repo])==before
