"""Reproducible source archive and full-code listing; excludes secrets/runtime data."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'node_modules', 'artifacts', 'data', '.cache', 'certs', 'phone-setup'}


def source_files():
    for path in sorted(ROOT.rglob('*')):
        parts = path.relative_to(ROOT).parts
        if not path.is_file() or any(part in EXCLUDED for part in parts):
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            continue
        if path.suffix in {'.pyc', '.zip'} or path.name in {'SafeWalk_CivicMesh_Source.md', 'SOURCE_MANIFEST.json'}:
            continue
        yield path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, default=ROOT.parent)
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    files = list(source_files())
    listing = ['# SafeWalk CivicMesh — complete source listing', '',
               'Every source/configuration file is included below in full. Binary PWA icons are included as base64. '
               'The ZIP contains the original filesystem layout. Runtime credentials and personal data are excluded.', '']
    manifest = {}
    for path in files:
        name = path.relative_to(ROOT).as_posix(); content = path.read_bytes()
        manifest[name] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        listing.extend([f'## `{name}`', ''])
        try:
            text = content.decode('utf-8')
            language = {'.py':'python','.js':'javascript','.mjs':'javascript','.json':'json','.webmanifest':'json',
                        '.html':'html','.sql':'sql','.yml':'yaml','.sh':'bash','.ps1':'powershell','.md':'markdown','.svg':'xml'}.get(path.suffix,'text')
            # A four-backtick fence safely contains README's normal triple fences.
            listing.extend([f'````{language}', text.rstrip('\n'), '````', ''])
        except UnicodeDecodeError:
            listing.extend(['Original binary content, base64 encoded:', '```base64', base64.b64encode(content).decode(), '```', ''])
    source_path = args.output_dir/'SafeWalk_CivicMesh_Source.md'; source_path.write_text('\n'.join(listing),encoding='utf-8')
    manifest_path = args.output_dir/'SafeWalk_CivicMesh_Manifest.json'; manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    archive_path = args.output_dir/'SafeWalk_CivicMesh.zip'
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        def add(name, content, executable=False):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 24, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, content, compresslevel=9)
        for path in files:
            add('safewalk-civicmesh/'+path.relative_to(ROOT).as_posix(), path.read_bytes(), path.suffix == '.sh')
        add('safewalk-civicmesh/SOURCE_MANIFEST.json',manifest_path.read_text().encode())
    print(json.dumps({'archive':str(archive_path),'full_source':str(source_path),'source_files':len(files),
                      'archive_bytes':archive_path.stat().st_size},indent=2))


if __name__=='__main__':
    main()
