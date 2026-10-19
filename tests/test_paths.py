import base64
import os
import pytest
from conftest import git, invoke


def raw_paths(row):
    return {base64.b64decode(p['path_b64']) for p in row['dirty_paths']}


def test_byte_paths_rename_and_order(installed_cli, repo, linked, tmp_path, git_env):
    names = [b' space ', b'tab\tname', b'line\nname', b'arrow -> name', b'-leading',
             'caf\u00e9'.encode(), b'bad-\xff', b'case', b'Case', b'e\xcc\x81', b'\xc3\xa9']
    for root in linked:
        for name in names:
            fd = os.open(os.fsencode(root)+b'/'+name, os.O_WRONLY|os.O_CREAT, 0o600)
            os.write(fd, b'synthetic\n'); os.close(fd)
    git(linked[0], 'mv', 'shared.txt', 'renamed.txt', env=git_env)
    (linked[1]/'shared.txt').unlink()
    clone = tmp_path/'clone'
    git(tmp_path, 'clone', '--no-hardlinks', repo, clone, env=git_env)
    (clone/'shared.txt').write_text('other clone\n')
    a, r = invoke(installed_cli, [repo, clone], env=git_env)
    b, s = invoke(installed_cli, [clone, linked[1], repo], env=git_env)
    assert a.returncode == b.returncode == 1, r
    assert r['repositories'] == s['repositories'] and r['worktrees'] == s['worktrees']
    assert r['overlaps'] == s['overlaps']
    assert {base64.b64decode(o['path']['path_b64']) for o in r['overlaps']} == set(names+[b'shared.txt'])
    for w in r['worktrees']:
        if w['root']['path_utf8'] == str(linked[0]):
            assert raw_paths(w) == set(names+[b'shared.txt',b'renamed.txt'])
            assert w['renames'][0]['source']['path_utf8'] == 'shared.txt'
            assert w['renames'][0]['destination']['path_utf8'] == 'renamed.txt'
            assert next(p for p in w['dirty_paths'] if base64.b64decode(p['path_b64'])==b'bad-\xff')['path_utf8'] is None
    assert b'\xff' not in a.stdout and b'\x1b' not in a.stdout


def test_unmerged_and_repository_ignores(installed_cli, repo, linked, git_env):
    for root, name in zip(linked, ['one','two']):
        (root/'shared.txt').write_text(name+'\n')
        git(root,'add','shared.txt',env=git_env);git(root,'commit','-m',name,env=git_env)
    import subprocess
    result = subprocess.run(['git','-C',str(linked[0]),'merge','b'],env=git_env,capture_output=True)
    assert result.returncode == 1
    (linked[1]/'shared.txt').write_text('dirty\n')
    for root in linked:
        (root/'.gitignore').write_text('ignored\n')
        (root/'ignored').write_text('not counted\n')
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode == 1,r
    assert {o['path']['path_utf8'] for o in r['overlaps']} == {'shared.txt','.gitignore'}


def test_raw_absolute_root_and_locked_registration(installed_cli,tmp_path,git_env):
    root=tmp_path/os.fsdecode(b'root-\xff\n trailing ');root.mkdir()
    git(root,'init','-b','alternate',env=git_env)
    (root/'file').touch();git(root,'add','file',env=git_env)
    git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','base',env=git_env)
    other=tmp_path/'group'/'nested';other.parent.mkdir()
    git(root,'worktree','add','--detach',other,env=git_env)
    git(root,'worktree','lock',other,env=git_env)
    p,r=invoke(installed_cli,[root],env=git_env)
    assert p.returncode==0,r
    assert r['coverage']['registered_worktrees']==2
    value=next(w['root'] for w in r['worktrees'] if w['root']['path_utf8'] is None)
    assert base64.b64decode(value['path_b64'])==os.fsencode(root)

@pytest.mark.parametrize('algorithm',['sha1','sha256'])
@pytest.mark.parametrize('index_version',[2,3,4])
@pytest.mark.parametrize('gitlink',[False,True])
def test_native_index_formats(installed_cli,tmp_path,git_env,algorithm,index_version,gitlink):
    root=tmp_path/'native-index';root.mkdir()
    git(root,'init','-b','synthetic','--object-format='+algorithm,env=git_env)
    for name in ['link','nested-a','nested-b']:(root/name).write_text('base\n')
    git(root,'add','.',env=git_env)
    git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','base',env=git_env)
    if gitlink:
        oid=git(root,'rev-parse','HEAD',env=git_env).strip().decode()
        git(root,'update-index','--add','--cacheinfo','160000,'+oid+',sub',env=git_env)
    git(root,'update-index','--index-version',index_version,env=git_env)
    (root/'link').write_text('dirty\n')
    p,r=invoke(installed_cli,[root],env=git_env)
    if gitlink:
        assert p.returncode==4 and r['problems'][0]['feature']=='submodule',r
        return
    assert p.returncode==0,r
    assert r['worktrees'][0]['dirty_paths'][0]['path_utf8']=='link'
    assert len(r['worktrees'][0]['head']['oid'])==(40 if algorithm=='sha1' else 64)


def test_intent_to_add_extended_index_entry(installed_cli,repo,git_env):
    (repo/'intent').write_text('synthetic\n')
    git(repo,'add','-N','intent',env=git_env)
    p,r=invoke(installed_cli,[repo],env=git_env)
    assert p.returncode==0,r
    assert {x['path_utf8'] for x in r['worktrees'][0]['dirty_paths']}=={'intent'}


@pytest.mark.parametrize('algorithm',['sha1','sha256'])
@pytest.mark.parametrize('index_version',[2,3,4])
@pytest.mark.parametrize('flag',['--assume-unchanged','--skip-worktree'])
def test_hidden_index_changes_are_unavailable(installed_cli,tmp_path,git_env,algorithm,index_version,flag):
    from test_effects import inventory
    root=tmp_path/'hidden-changes';root.mkdir()
    git(root,'init','-b','synthetic','--object-format='+algorithm,env=git_env)
    (root/'shared.txt').write_text('base\n')
    git(root,'add','.',env=git_env)
    git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','base',env=git_env)
    linked=tmp_path/'linked'
    git(root,'worktree','add','--detach',linked,env=git_env)
    for checkout in [root,linked]:
        git(checkout,'update-index',flag,'shared.txt',env=git_env)
        git(checkout,'update-index','--index-version',index_version,env=git_env)
        (checkout/'shared.txt').write_text('hidden change\n')
        assert git(checkout,'status','--porcelain=v2',env=git_env)==b'', 'Fixture must hide the change from Git status'
    before=inventory([root,linked])
    p,r=invoke(installed_cli,[root],env=git_env)
    assert p.returncode==4,r
    assert r['coverage']['status']=='unavailable' and r['conclusion']=='indeterminate'
    assert all(w['dirty_paths'] is None for w in r['worktrees'])
    assert {e['code'] for e in r['problems']}=={'unsupported_repository_feature'}
    assert {e['feature'] for e in r['problems']}=={'unproven_read_effect'}
    assert inventory([root,linked])==before
