"""Lean entrypoint. Preserve legacy approval digests; bind each preview to its native master."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import flow

HERE = Path(__file__).resolve().parent
RULES = {'version': '2026-11-01', 'read_first': str(flow.ROOT / 'AGENTS.md'),
         'skill': str(HERE / 'codex-video-workflow/SKILL.md'),
         'series': str(HERE / 'series-defaults.json')}


def picture_cache(paths, edl, brief, engine, board):
    """Only prepared full soundtracks may reuse a picture with temporary source audio."""
    visual = {k: v for k, v in edl.items() if k not in {'audio_master', 'music'}}
    sources = [flow.resolve_file(value, paths['edit']) for value in edl['sources'].values()]
    files = {str(file): flow.sha256(file) for file in sources}
    for overlay in edl.get('overlays', []):
        file = flow.resolve_file(overlay['file'], paths['edit']); files[str(file)] = flow.sha256(file)
    if edl.get('subtitles'):
        file = flow.resolve_file(edl['subtitles'], paths['edit']); files[str(file)] = flow.sha256(file)
    renderers = [flow.LAUNCHER, flow.ROOT / 'video-use/helpers/render.py', flow.ROOT / 'video-use/helpers/grade.py']
    key = flow.digest({'visual_edl': visual, 'assets': files, 'fps': str(brief['fps']), 'engine': engine,
                       'renderers': {str(f): flow.sha256(f) for f in renderers}})
    folder = paths['edit'] / 'workflow/cache/picture' / key
    folder.mkdir(parents=True, exist_ok=True)
    picture = folder / 'composition.mp4'; meta = folder / 'picture.json'
    if meta.exists():
        record = flow.read_json(meta)
        if record.get('sha256') != flow.sha256(picture):
            raise flow.FlowError('缓存画面被修改，不能复用于新混音。')
        return picture, True
    flow.run_capture(flow.node_command('render', paths['edl'], '-o', picture, '--fps', str(brief['fps']), '--no-loudnorm'),
                     cwd=paths['root'], log=folder / 'render.log')
    if flow.stage_digest(paths, 'storyboard') != board:
        raise flow.FlowError('画面合成期间输入变化，不写入缓存记录。')
    flow.write_json(meta, {'key': key, 'sha256': flow.sha256(picture)})
    return picture, False


def verify_master(paths, record, board_digest):
    if record.get('storyboard_digest') != board_digest:
        raise flow.FlowError('母版与当前分镜不一致，需生成当前预览。')
    for key, hash_key in [('file', 'sha256'), ('qa_file', 'qa_sha256')]:
        file = Path(record[key]).resolve()
        if not file.is_relative_to((paths['edit'] / 'workflow/cache').resolve()):
            raise flow.FlowError('母版记录必须位于本项目缓存目录。')
        if flow.sha256(file) != record[hash_key]:
            raise flow.FlowError('母版或检查记录被改动，需重新生成并审阅预览。')
    qa = flow.read_json(record['qa_file'])
    if not qa.get('technical_passed') or qa.get('video_sha256') != record['sha256']:
        raise flow.FlowError('母版缺少匹配的技术检查。')
    return qa


def render_preview(args):
    paths = flow.project_paths(args.project)
    flow.require_approval(paths, 'strategy')
    board = flow.require_approval(paths, 'storyboard')
    brief, manifest, _ = flow.current_inputs(paths)
    edl, _ = flow.validate_edl(paths, brief, manifest, inspect_media=True)
    if edl.get('audio_master') and edl.get('music'):
        raise flow.FlowError('先把配乐合入明确的audio_master，不能同时配置两种混音入口。')
    engine = flow.sha256(__file__)
    key = flow.digest({'board': board, 'engine': engine, 'quality': 'native-final'})
    cache = paths['edit'] / 'workflow/cache' / key
    cache.mkdir(parents=True, exist_ok=True)
    meta = cache / 'master.json'
    hit = False
    if meta.exists():
        master = flow.read_json(meta)
        verify_master(paths, master, board)
        hit = True
    else:
        native = cache / 'master.mp4'
        raw = cache / 'composition.mp4'
        if edl.get('audio_master'):
            raw, picture_reused = picture_cache(paths, edl, brief, engine, board)
        else:
            picture_reused = False
            command = flow.node_command('render', paths['edl'], '-o', raw, '--fps', str(brief['fps']))
            flow.run_capture(command, cwd=paths['root'], log=cache / 'render.log')
        duration = sum(float(s['end']) - float(s['start']) for s in edl['ranges'])
        if edl.get('audio_master'):
            from soundtrack import replace_soundtrack
            replace_soundtrack(raw, native, edl['audio_master'], duration, paths['edit'], log_path=cache / 'soundtrack.log')
        elif edl.get('music'):
            from music import mix_music
            mix_music(raw, native, edl['music'], duration, paths['edit'], log_path=cache / 'music.log')
        else:
            shutil.copyfile(raw, native)
        qa = flow.quality_report(paths, native, edl, brief, 1920)
        qa_file = cache / 'master.qa.json'
        flow.write_json(qa_file, qa)
        if not qa['technical_passed']:
            raise flow.FlowError('高清母版技术检查失败：' + str(qa_file))
        if flow.stage_digest(paths, 'storyboard') != board:
            raise flow.FlowError('合成期间已审输入变更，母版不能复用。')
        master = {'schema_version': 1, 'file': str(native), 'sha256': qa['video_sha256'],
                  'qa_file': str(qa_file), 'qa_sha256': flow.sha256(qa_file),
                  'storyboard_digest': board, 'engine_sha256': engine, 'picture_reused': picture_reused}
        flow.write_json(meta, master)
    state = flow.state_for(paths)
    previous = state.get('renders', {}).get('preview', {})
    if previous.get('native_master') == master and previous.get('storyboard_digest') == board:
        try:
            old_qa = flow.read_json(previous['qa_file'])
            reusable = old_qa.get('technical_passed') and old_qa.get('video_sha256') == previous['video_sha256'] == flow.sha256(previous['file'])
        except (flow.FlowError, KeyError):
            reusable = False
        if reusable:
            return {'stage': 'preview', 'file': previous['file'], 'qa': previous['qa_file'],
                    'reused': True, 'native_master_reused': True,
                    'next': '实际视频和当前封面一起审；未自动记录任何批准。'}
    out = paths['edit'] / '03_preview'
    out.mkdir(parents=True, exist_ok=True)
    output = flow.next_version(out, 'preview')
    a, b = map(float, brief['aspect_ratio'].split(':'))
    scale = 'scale=-2:1280' if a < b else 'scale=1280:-2'
    flow.run_capture(flow.node_command('ffmpeg', '-y', '-v', 'error', '-i', master['file'], '-vf', scale,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '25', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
        '-movflags', '+faststart', output), cwd=paths['root'], log=output.with_suffix('.downscale.log'))
    qa = flow.quality_report(paths, output, edl, brief, 1280)
    qa_file = output.with_suffix('.qa.json')
    flow.write_json(qa_file, qa)
    if not qa['technical_passed']:
        raise flow.FlowError('预览技术检查失败：' + str(qa_file))
    if flow.stage_digest(paths, 'storyboard') != board:
        raise flow.FlowError('生成预览期间已审输入变更。')
    state = flow.state_for(paths)
    state['renders']['preview'] = {'file': str(output), 'qa_file': str(qa_file), 'created_at': flow.now(),
        'storyboard_digest': board, 'edl_sha256': flow.sha256(paths['edl']), 'fps': str(brief['fps']),
        'long_edge': 1280, 'video_sha256': qa['video_sha256'], 'synthetic': bool(state.get('synthetic')),
        'native_master': master}
    state['approvals'].pop('preview', None)
    flow.write_json(paths['state'], state)
    return {'stage': 'preview', 'file': str(output), 'qa': str(qa_file), 'native_master_reused': hit,
            'next': '检查并展示完整视频和实际封面，等待用户确认当前组合。'}


def render_final(args):
    paths = flow.project_paths(args.project)
    flow.require_approval(paths, 'strategy')
    board = flow.require_approval(paths, 'storyboard')
    approval = flow.require_approval(paths, 'preview')
    state = flow.state_for(paths)
    existing = state.get('renders', {}).get('final', {})
    if existing.get('approved_preview_digest') == approval and Path(existing.get('file', '')).is_file():
        if flow.sha256(existing['file']) == existing.get('video_sha256'):
            try:
                old_qa = flow.read_json(existing['qa_file'])
            except (flow.FlowError, KeyError):
                old_qa = {}
            if old_qa.get('technical_passed') and old_qa.get('video_sha256') == existing['video_sha256']:
                return {'stage': 'final', 'file': existing['file'], 'qa': existing['qa_file'], 'reused': True}
    master = state['renders']['preview'].get('native_master')
    if master is None:
        # Old projects retain their original approval and final-render path.
        return flow.render_project(args, final=True)
    qa = verify_master(paths, master, board)
    from cover import validate_cover
    covers = validate_cover(paths, flow.read_json(paths['brief'])).get('deliverables', [])
    out = paths['edit'] / '04_final'
    out.mkdir(parents=True, exist_ok=True)
    output = flow.next_version(out, 'final')
    shutil.copyfile(master['file'], output)
    if flow.sha256(output) != master['sha256']:
        raise flow.FlowError('终稿复制校验失败。')
    if flow.stage_digest(paths, 'storyboard') != board or flow.stage_digest(paths, 'preview') != approval:
        raise flow.FlowError('复制期间已审输入变化，当前终稿不能交付。')
    qa = {**qa, 'video': str(output), 'checked_at': flow.now(),
          'reused_by_exact_byte_identity': {'master': master['file'], 'sha256': master['sha256'], 'original_qa': master['qa_file']}}
    qa_file = output.with_suffix('.qa.json')
    flow.write_json(qa_file, qa)
    state['renders']['final'] = {'file': str(output), 'qa_file': str(qa_file), 'created_at': flow.now(),
        'storyboard_digest': board, 'edl_sha256': flow.sha256(paths['edl']),
        'fps': state['renders']['preview']['fps'], 'long_edge': 1920,
        'video_sha256': master['sha256'], 'synthetic': bool(state.get('synthetic')),
        'approved_preview_digest': approval, 'reused_native_master': True}
    flow.write_json(paths['state'], state)
    return {'stage': 'final', 'file': str(output), 'qa': str(qa_file), 'cover_files': covers,
            'reused_native_master': True, 'next': '交付实际MP4与已审封面；相同字节复用母版检查。'}


def compact_context(args):
    paths = flow.project_paths(args.project)
    current = flow.status_project(args)
    brief = flow.read_json(paths['brief'])
    req_path = paths['edit'] / 'requirements_current.json'
    req = flow.read_json(req_path) if req_path.exists() else {}
    return {'workspace_rules': RULES, 'project': str(paths['root']),
            'objective': brief.get('objective'), 'stages': current['stages'], 'final_current': current['final_current'],
            'current_revision': req.get('revision'), 'latest_review': req.get('latest_review'),
            'files': {k: str(paths[k]) for k in ['brief', 'edl', 'board', 'state']},
            'note': '只读取本阶段需要的资料；这是状态检查，不是用户审批。'}


def metrics(args):
    p = flow.project_paths(args.project)['edit'] / 'workflow/metrics.jsonl'
    rows = [json.loads(line) for line in p.read_text('utf-8').splitlines() if line.strip()] if p.exists() else []
    by = defaultdict(lambda: {'calls': 0, 'elapsed_s': 0, 'failed': 0})
    for row in rows:
        item = by[row['command']]
        item['calls'] += 1; item['elapsed_s'] = round(item['elapsed_s'] + row['elapsed_s'], 3)
        item['failed'] += row['exit_code'] != 0
    return {'commands': dict(by), 'token_usage': None,
            'scope': '仅本入口命令耗时，不是全部模型/代理/人工等待时间；token未采集。'}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else ''
    project = argv[argv.index('--project') + 1] if '--project' in argv and argv.index('--project') + 1 < len(argv) else None
    started = time.monotonic(); code = 2
    try:
        if command in {'context', 'metrics', 'render-preview', 'render-final', 'status'}:
            parser = argparse.ArgumentParser()
            parser.add_argument('command'); parser.add_argument('--project', required=True)
            args = parser.parse_args(argv)
            operations = {'context': compact_context, 'metrics': metrics, 'render-preview': render_preview,
                          'render-final': render_final, 'status': flow.status_project}
            result = operations[command](args)
            if command == 'status': result['workspace_rules'] = RULES
            print(json.dumps(result, ensure_ascii=False, indent=2)); code = 0
        elif command in {'inventory', 'storyboard', 'reference', 'reference-detail'}:
            script = 'media.py' if command in {'inventory', 'storyboard'} else 'hypit_reference.py'
            code = subprocess.call([sys.executable, str(HERE / script), *argv])
        else:
            code = flow.main(argv)
        return code
    except (flow.FlowError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if project and command != 'metrics':
            folder = flow.project_paths(project)['edit'] / 'workflow'
            if folder.is_dir():
                row = {'at': flow.now(), 'command': command, 'elapsed_s': round(time.monotonic() - started, 3),
                       'exit_code': code, 'token_usage': None}
                with (folder / 'metrics.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    sys.exit(main())
