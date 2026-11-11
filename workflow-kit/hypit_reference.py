"""Local Hypit reference evidence for the five-stage video workflow.

Only local media commands are invoked. Evidence is an inspection aid, not a
semantic reading, transcript or human approval. This ledger guards stale files;
it does not authenticate the operator or prove that a human watched a video.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / 'hypit-local/run.cjs'
PACKAGE = Path(os.environ.get('VIDEO_WORKFLOW_HYPIT_DIR', str(ROOT / 'hypit-local/node_modules/@hypit/hypit'))) / 'package.json'
EXPECTED_VERSION = '0.3.1'
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.webm', '.mts', '.m2ts', '.mpg', '.mpeg', '.3gp', '.wmv', '.flv', '.ts'}
NOTE = ('Hypit 提供本地媒体证据；抽样图和变化候选不代表完整观看、语义镜头识别或口播转写。'
        'Codex 仍须阅读全片结构，按需密集检查关键区间，并取得真实声音/转写证据。'
        'Hypit quick probe 未完整处理显示旋转/SAR；原 FFprobe 技术清单仍为画幅依据。')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(path, base):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def video_references(manifest):
    return [r for r in manifest.get('references', [])
            if r.get('kind') == 'video' or (not r.get('kind') and Path(r['path']).suffix.lower() in VIDEO_EXT)]


def check_installation():
    node = shutil.which('node')
    if not node or not WRAPPER.is_file() or not PACKAGE.is_file():
        raise ValueError('Hypit 本地安装未就绪：缺少 Node.js、hypit-local/run.cjs 或发行包。')
    package_version = str(read_json(PACKAGE).get('version', ''))
    if package_version != EXPECTED_VERSION:
        raise ValueError(f'当前集成已验证 Hypit {EXPECTED_VERSION}，实际为 {package_version}；先验证新版本。')
    command = [node, str(WRAPPER), '--version']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode or not re.search(r'(?<!\d)' + re.escape(package_version) + r'(?!\d)', result.stdout + result.stderr):
        raise ValueError('Hypit 可执行版本检查失败：' + (result.stderr or result.stdout)[-1000:])
    return {'version': package_version, 'command': command, 'output': result.stdout.strip(),
            'package_json_sha256': sha256(PACKAGE), 'wrapper_sha256': sha256(WRAPPER)}


def unique_run(edit):
    name = 'run_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:10]
    folder = Path(edit) / 'analysis/hypit' / name
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def record_command(edit, folder, name, args, expected_outputs=()):
    node = shutil.which('node')
    command = [node, str(WRAPPER), *map(str, args), '--json']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (folder / (name + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise ValueError(f'Hypit {name} 执行失败：' + (result.stderr or result.stdout)[-1800:])
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError(f'Hypit {name} 未返回有效 JSON：' + result.stdout[-1000:]) from exc
    output_json = folder / (name + '.json')
    write_json(output_json, payload)
    files = [output_json]
    for output in expected_outputs:
        output = Path(output)
        if output.is_dir():
            children = [p for p in sorted(output.rglob('*')) if p.is_file() and p.stat().st_size]
            if not children:
                raise ValueError(f'Hypit {name} 的预期目录没有产物：{output}')
            files.extend(children)
        elif output.is_file() and output.stat().st_size:
            files.append(output)
        else:
            raise ValueError(f'Hypit {name} 未产生预期文件：{output}')
    return {'name': name, 'argv': command, 'exit_code': result.returncode,
            'outputs': [{'path': p.relative_to(edit).as_posix(), 'sha256': sha256(p)} for p in files]}, payload


def prepare_reference(project):
    project = Path(project).resolve()
    edit = project / 'edit'
    source_manifest = read_json(edit / 'analysis/media_manifest.json')
    refs = video_references(source_manifest)
    if not refs:
        raise ValueError('清单中没有视频参考；先放入参考视频并运行 inventory。')
    installation = check_installation()
    run = unique_run(edit)
    proof = {'schema_version': 1, 'engine': 'hypit', 'version': installation['version'],
             'installation': installation, 'created_at': datetime.now(timezone.utc).isoformat(),
             'run': run.relative_to(edit).as_posix(), 'references': [], 'details': [], 'scope_note': NOTE}
    for row in refs:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', str(row.get('id', ''))):
            raise ValueError('参考ID仅可使用英文字母、数字、下划线和短横线。')
        source = resolve(row['path'], project)
        if not source.is_file() or sha256(source) != row['sha256']:
            raise ValueError('参考文件已变化或不存在，先重新盘点：' + str(source))
        duration = float(row.get('duration', 0))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('参考视频无有效时长：' + str(source))
        folder = run / row['id']
        folder.mkdir()
        commands = []
        record, _ = record_command(edit, folder, 'probe', ['media', 'probe', source])
        commands.append(record)
        record, _ = record_command(edit, folder, 'boundaries',
                                   ['media', 'boundaries', source, '--rate', '4', '--threshold', '0.12'])
        commands.append(record)
        grid = folder / 'overview.jpg'
        record, tile = record_command(edit, folder, 'tile',
            ['media', 'tile', source, '--start', '0', '--end', f'{max(duration - .0001, duration / 2):.6f}',
             '--every', f'{max(duration / 16, .04):.6f}', '--columns', '4', '--cell', '320', '--to', grid], [grid])
        if not isinstance(tile.get('samples'), list) or not tile['samples'] or not tile.get('frames'):
            raise ValueError('Hypit 抽样图没有有效样本。')
        commands.append(record)
        proof['references'].append({'id': row['id'], 'input_path': str(source), 'input_sha256': row['sha256'],
                                    'duration': duration, 'commands': commands})
    output = edit / 'analysis/hypit/manifest.json'
    write_json(run / 'run_manifest.json', proof)
    write_json(output, proof)
    validate_reference_evidence(project, source_manifest)
    return {'manifest': str(output), 'references': len(refs), 'engine': 'hypit',
            'version': proof['version'], 'scope_note': NOTE,
            'next': '读取实际证据并形成 reference_analysis.md；关键动作可运行 reference-detail，口播转写仍需选择服务。'}


def detail_reference(project, reference_id, start, end):
    project = Path(project).resolve()
    edit = project / 'edit'
    source_manifest = read_json(edit / 'analysis/media_manifest.json')
    validate_reference_evidence(project, source_manifest)
    refs = {r['id']: r for r in video_references(source_manifest)}
    if reference_id not in refs:
        raise ValueError('reference-id 不在视频参考清单中。')
    row = refs[reference_id]
    start, end = float(start), float(end)
    if not all(math.isfinite(n) for n in [start, end]) or not 0 <= start < end <= float(row['duration']):
        raise ValueError('密集检查需满足 0 <= start < end <= 参考片时长。')
    if end - start > 10:
        raise ValueError('逐帧检查一次最多10秒，请按需要分成多个关键区间。')
    check_installation()
    run = unique_run(edit)
    destination = run / 'dense'
    source = resolve(row['path'], project)
    record, payload = record_command(edit, run, 'tiles',
        ['media', 'tiles', source, '--start', str(start), '--end', str(end), '--every-frame',
         '--columns', '4', '--rows', '3', '--cell', '320', '--to', destination], [destination])
    if not payload.get('grids'):
        raise ValueError('Hypit 逐帧检查没有输出分页图片。')
    output = edit / 'analysis/hypit/manifest.json'
    proof = read_json(output)
    proof.setdefault('details', []).append({'id': reference_id, 'start': start, 'end': end,
        'input_sha256': row['sha256'], 'commands': [record]})
    write_json(output, proof)
    validate_reference_evidence(project, source_manifest)
    return {'manifest': str(output), 'reference_id': reference_id, 'start': start, 'end': end,
            'grids': len(payload['grids']), 'scope_note': NOTE}


def validate_reference_evidence(project, source_manifest):
    """Return the hashes included in strategy approval; fail on stale/missing proof."""
    project = Path(project).resolve()
    edit = project / 'edit'
    refs = video_references(source_manifest)
    if not refs:
        return {}
    manifest_path = edit / 'analysis/hypit/manifest.json'
    if not manifest_path.is_file():
        raise ValueError('参考视频尚未用 Hypit 采集证据；先运行 reference --project <项目目录>。')
    proof = read_json(manifest_path)
    if proof.get('schema_version') != 1 or proof.get('engine') != 'hypit' or proof.get('version') != EXPECTED_VERSION:
        raise ValueError('Hypit 参考证据版本或结构不受支持。')
    records = proof.get('references', [])
    if not isinstance(records, list) or len(records) != len(refs):
        raise ValueError('Hypit 证据与当前参考清单不匹配，需重新运行 reference。')
    recorded = {r.get('id'): r for r in records}
    if len(recorded) != len(refs) or set(recorded) != {r['id'] for r in refs}:
        raise ValueError('Hypit 证据参考ID不匹配。')
    hashes = {'manifest': sha256(manifest_path), 'files': {}}
    allowed_root = (edit / 'analysis/hypit').resolve()
    for row in refs:
        record = recorded[row['id']]
        source = resolve(row['path'], project)
        if record.get('input_sha256') != row['sha256'] or sha256(source) != row['sha256']:
            raise ValueError('参考文件已变化，Hypit 证据失效：' + row['id'])
        if resolve(record.get('input_path', ''), project) != source:
            raise ValueError('Hypit 证据源路径不匹配。')
        names = {c.get('name') for c in record.get('commands', [])}
        if not {'probe', 'boundaries', 'tile'} <= names:
            raise ValueError('Hypit 基础参考证据不完整。')
    for record in [*records, *proof.get('details', [])]:
        if record.get('id') not in recorded:
            raise ValueError('Hypit 详细证据引用未知参考。')
        if record.get('input_sha256') != recorded[record['id']]['input_sha256']:
            raise ValueError('Hypit 详细证据来自旧参考版本。')
        for command in record.get('commands', []):
            if command.get('exit_code') != 0 or not command.get('outputs'):
                raise ValueError('Hypit 命令未成功或缺少输出记录。')
            for artifact in command['outputs']:
                path = resolve(artifact['path'], edit)
                if not path.is_relative_to(allowed_root) or not path.is_file() or sha256(path) != artifact.get('sha256'):
                    raise ValueError('Hypit 证据文件缺失或已改变：' + str(path))
                hashes['files'][str(path)] = artifact['sha256']
    return hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description='Hypit 本地参考视频证据；不调用转写或生成服务。')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['reference', 'reference-detail']:
        child = commands.add_parser(name)
        child.add_argument('--project', required=True)
        if name == 'reference-detail':
            child.add_argument('--reference-id', required=True)
            child.add_argument('--start', type=float, required=True)
            child.add_argument('--end', type=float, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_reference(args.project) if args.command == 'reference' else detail_reference(args.project, args.reference_id, args.start, args.end)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
