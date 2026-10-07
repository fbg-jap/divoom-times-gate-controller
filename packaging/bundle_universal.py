"""Build source delivery archives without local data, SDKs or credentials."""
from pathlib import Path
import hashlib
import json
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
VERSION = '3.1.0'
BASE = f'divoom-keeper-{VERSION}'
ROOT_FILES = {'app.py', 'shell_main.py', 'server.py', 'README.md', 'LICENSE', 'LICENSE.md', 'LICENSE.txt',
              'requirements.txt', 'requirements-core.txt', 'requirements-server.txt',
              'run_linux.sh', 'build_linux.sh', 'Dockerfile', 'compose.yaml', '.dockerignore',
              'run_studio.ps1', 'build_windows.ps1', '.env.example', '.gitignore'}
EXCLUDED = {'node_modules', '.gradle', '.idea', 'build', '__pycache__', '.git', 'Pods', 'xcuserdata'}


def files():
    candidates = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for directory in ['keeper', 'web', 'tests', 'docs', 'packaging', '.github']:
        candidates.extend((ROOT / directory).rglob('*'))
    for path in sorted(set(candidates)):
        rel = path.relative_to(ROOT)
        if not path.is_file() or set(rel.parts) & EXCLUDED:
            continue
        if path.suffix in {'.pyc', '.keystore', '.jks', '.log'} or path.name in {'local.properties', '.DS_Store'}:
            continue
        yield path, rel


def main():
    DIST.mkdir(exist_ok=True)
    source = DIST / f'DivoomKeeper-{VERSION}-source.zip'
    docker = DIST / f'DivoomKeeper-{VERSION}-docker.zip'
    linux = DIST / f'DivoomKeeper-{VERSION}-linux-source.tar.gz'
    selected = list(files())
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, rel in selected:
            archive.write(path, (Path(BASE) / rel).as_posix())
    def linux_filter(info):
        if info.isfile():
            info.mode = 0o755 if info.name.endswith('.sh') else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        return info
    with tarfile.open(linux, 'w:gz') as archive:
        for path, rel in selected:
            if rel.parts[0] == 'web' or rel.name in {'Dockerfile', 'compose.yaml', '.dockerignore', '.env.example'}:
                continue
            archive.add(path, arcname=(Path(BASE) / rel).as_posix(), filter=linux_filter)
    with zipfile.ZipFile(docker, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, rel in selected:
            if rel.parts[0] in {'keeper', 'docs'} or rel.name in ROOT_FILES or (
                rel.parts[0] == 'web' and len(rel.parts) > 1 and rel.parts[1] in {'src', 'public', 'package.json', 'package-lock.json', 'index.html'}
            ):
                archive.write(path, (Path(BASE) / rel).as_posix())
    outputs = [source, docker, linux, DIST / f'DivoomKeeper-{VERSION}-android-debug.apk',
               DIST / f'DivoomKeeper-{VERSION}-windows.zip']
    report = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
              for p in outputs if p.is_file()}
    (DIST / f'DivoomKeeper-{VERSION}-SHA256.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
