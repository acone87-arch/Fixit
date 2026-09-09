"""Exercise release ordering/rollback with synthetic commands, never the VPS."""
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux deployment shell harness runs in CI')


@pytest.mark.parametrize('failure', ['', 'migration', 'health'])
def test_backup_precedes_migration_and_failure_restores_image(tmp_path, failure):
    repo = tmp_path / 'fixit'; repo.mkdir()
    (repo / '.env').write_text('SYNTHETIC_CONFIG=1\n')
    commands = tmp_path / 'bin'; commands.mkdir()
    harness = '''#!/usr/bin/env python3
import io,json,os,pathlib,sys,tarfile
name=pathlib.Path(sys.argv[0]).name; args=sys.argv[1:]; root=pathlib.Path(os.environ['HARNESS_ROOT'])
with (root/'calls').open('a') as log: log.write(json.dumps([name,*args])+'\\n')
if name=='git':
    if args[:2]==['rev-parse','HEAD']: print((root/'head').read_text())
    if args[:2]==['checkout','--detach']: (root/'head').write_text(args[2])
if name=='docker':
    if args[0]=='inspect': print('old-image' if args[2]=='{{.Image}}' else 'fixit-api')
    if 'ps' in args: print('old-container')
    if 'pg_dump' in args: print('synthetic dump')
    if 'pg_restore' in args: print('synthetic archive list')
    if args[0]=='run':
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
            item=tarfile.TarInfo('uploads/photo.jpg');item.size=5;archive.addfile(item,io.BytesIO(b'photo'))
    if 'upgrade' in args and os.environ['FAILURE']=='migration': sys.exit(17)
if name=='curl' and os.environ['FAILURE']=='health': sys.exit(7)
'''
    for name in ['git', 'docker', 'curl', 'sleep']:
        path = commands / name; path.write_text(harness); path.chmod(0o755)
    previous = '1' * 40; release = '2' * 40
    (tmp_path / 'head').write_text(previous)
    source = Path('scripts/deploy_pilot_release.sh').read_text().replace('/opt/fixit', str(repo))
    script = tmp_path / 'release.sh'; script.write_text(source)
    env = {**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'], 'HARNESS_ROOT': str(tmp_path), 'FAILURE': failure}
    result = subprocess.run(['bash', str(script), release], env=env, capture_output=True, text=True, timeout=20)
    calls = [json.loads(line) for line in (tmp_path / 'calls').read_text().splitlines()]
    position = lambda value: next(i for i, call in enumerate(calls) if value in call)
    assert position('stop') < position('pg_dump') < position('pg_restore') < position('upgrade')
    assert next((repo / 'backups').glob('*/database.dump')).stat().st_size > 0
    assert next((repo / 'backups').glob('*/uploads.tar.gz')).stat().st_size > 0
    if failure:
        assert result.returncode != 0, result.stdout
        assert (tmp_path / 'head').read_text() == previous
        assert ['docker', 'tag', 'old-image', 'fixit-api'] in calls
        assert 'Recovery files:' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert (tmp_path / 'head').read_text() == release
        assert f'Release SHA: {release}' in result.stdout
