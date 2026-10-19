import importlib.util
from pathlib import Path
import zipfile
import pytest

spec=importlib.util.spec_from_file_location('verifier',Path(__file__).resolve().parents[1]/'tools/verify_release.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)


def test_unapproved_archive_member_refused(tmp_path):
    artifact=tmp_path/'synthetic.whl'
    with zipfile.ZipFile(artifact,'w') as a:
        a.writestr('allowed.py','')
        a.writestr('.private/receipt.json','{}')
    with pytest.raises(ValueError):
        verifier.inspect_artifact(artifact,{'allowed.py'},'wheel')

@pytest.mark.parametrize('names',[['allowed.py','allowed.py'],['../allowed.py'],['/allowed.py'],[]])
def test_unsafe_or_missing_members_refused(tmp_path,names):
    artifact=tmp_path/'synthetic.whl'
    with zipfile.ZipFile(artifact,'w') as a:
        for name in names:
            if name in a.namelist():
                with pytest.warns(UserWarning,match='Duplicate name'):a.writestr(name,'')
            else:a.writestr(name,'')
    with pytest.raises(ValueError):verifier.inspect_artifact(artifact,{'allowed.py'},'wheel')


def test_sdist_symlink_refused(tmp_path):
    import tarfile
    artifact=tmp_path/'synthetic.tar.gz'
    with tarfile.open(artifact,'w:gz') as a:
        link=tarfile.TarInfo('allowed.py');link.type=tarfile.SYMTYPE;link.linkname='/outside';a.addfile(link)
    with pytest.raises(ValueError):verifier.inspect_artifact(artifact,{'allowed.py'},'sdist')
