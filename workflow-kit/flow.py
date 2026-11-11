"""Local five-stage Codex video workflow. Human approvals are recorded, never inferred.

No cloud calls, no API-key reads and no source-file mutations are performed here.
The approval ledger prevents accidental stale work; it is not an authentication system.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / 'video-use-local' / 'run.cjs'
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.webm', '.mts', '.m2ts', '.mpg', '.mpeg', '.3gp', '.wmv', '.flv', '.ts'}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp', '.gif', '.heic', '.avif',
    '.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg', '.opus', '.wma', '.aif', '.aiff'}


class FlowError(Exception):
    pass


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise FlowError(f'无法读取 JSON：{path}：{exc}') from exc


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def sha256(path):
    path = Path(path)
    if not path.is_file():
        raise FlowError(f'缺少文件：{path}')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def project_paths(project):
    p = Path(project).resolve()
    return {'root': p, 'edit': p / 'edit', 'state': p / 'edit/workflow/state.json',
            'brief': p / 'edit/brief.json', 'manifest': p / 'edit/analysis/media_manifest.json',
            'strategy': p / 'edit/01_strategy/strategy.md',
            'reference_analysis': p / 'edit/01_strategy/reference_analysis.md',
            'board': p / 'edit/02_storyboard/storyboard.json',
            'board_html': p / 'edit/02_storyboard/storyboard.html',
            'edl': p / 'edit/edl.json'}


def resolve_file(value, base):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def state_for(paths):
    state = read_json(paths['state'])
    if state.get('schema_version') != 1:
        raise FlowError('不支持的工作流状态版本。')
    return state


def init_project(args):
    paths = project_paths(args.project)
    if paths['state'].exists() or paths['brief'].exists():
        raise FlowError('该目录已有工作流或 brief，不覆盖。请使用 status 或选择新目录。')
    for directory in ['素材', '参考视频', '封面参考', 'edit/analysis', 'edit/01_strategy', 'edit/02_storyboard',
                      'edit/03_preview', 'edit/04_final', 'edit/cover', 'edit/workflow']:
        (paths['root'] / directory).mkdir(parents=True, exist_ok=True)
    write_json(paths['brief'], {
        'project_name': args.name or paths['root'].name, 'objective': '',
        'target_duration_s': None, 'aspect_ratio': '', 'fps': '30',
        'required_content': [], 'avoid_content': [], 'subtitles_required': False,
        'allow_silent_audio': False, 'notes': '',
        'preview_long_edge': 1280, 'final_long_edge': 1920,
        'cover': {'required': True, 'title': '', 'reference_files': [], 'series_id': '', 'size': None},
    })
    paths['strategy'].write_text('# 剪辑思路（待 Codex 根据素材与要求填写）\n\n尚未生成，不能提交确认。\n', encoding='utf-8')
    write_json(paths['state'], {'schema_version': 1, 'project_name': args.name or paths['root'].name,
        'synthetic': bool(args.synthetic), 'created_at': now(), 'approvals': {}, 'renders': {}})
    return {'project': str(paths['root']), 'synthetic': bool(args.synthetic), 'next': '放入素材/可选参考，填写 brief 后盘点；此时未批准任何阶段。'}


def validate_brief(paths):
    brief = read_json(paths['brief'])
    if not str(brief.get('objective', '')).strip():
        raise FlowError('brief.objective 需写明本片目标。')
    target = brief.get('target_duration_s')
    if not isinstance(target, (int, float)) or not math.isfinite(target) or target <= 0:
        raise FlowError('brief.target_duration_s 需为正数。')
    ratio = str(brief.get('aspect_ratio', ''))
    if not re.fullmatch(r'\d+(?:\.\d+)?:\d+(?:\.\d+)?', ratio):
        raise FlowError('brief.aspect_ratio 需填写，例如 16:9、9:16 或 1:1。')
    w, h = map(float, ratio.split(':'))
    if min(w, h) <= 0:
        raise FlowError('画幅比必须大于零。')
    try:
        fps = Fraction(str(brief.get('fps', '')))
    except (ValueError, ZeroDivisionError):
        raise FlowError('brief.fps 需为正帧率，例如 30 或 30000/1001。')
    if not 0 < fps <= 240:
        raise FlowError('本流程 fps 范围为 0–240（不含0）。')
    if brief.get('preview_long_edge', 1280) != 1280 or brief.get('final_long_edge', 1920) != 1920:
        raise FlowError('当前本地后端仅验证预览长边1280、终稿长边1920；其他规格需先扩展并验收后端。')
    return brief


def current_inputs(paths):
    """Read the source manifest and rehash its files. New/changed footage invalidates approval."""
    brief = validate_brief(paths)
    manifest = read_json(paths['manifest'])
    sources = manifest.get('sources', [])
    refs = manifest.get('references', [])
    if not isinstance(sources, list) or not sources:
        raise FlowError('素材清单没有 sources；先执行素材盘点。')
    if not isinstance(refs, list):
        raise FlowError('manifest.references 必须为列表。')
    files = {}
    ids = set()
    for kind, rows in [('source', sources), ('reference', refs)]:
        for item in rows:
            if not isinstance(item, dict) or not item.get('id') or not item.get('path') or not item.get('sha256'):
                raise FlowError('素材清单项须有 id/path/sha256。')
            if item['id'] in ids:
                raise FlowError(f'清单 id 重复：{item["id"]}')
            ids.add(item['id'])
            media = resolve_file(item['path'], paths['root'])
            actual = sha256(media)
            if actual != item['sha256']:
                raise FlowError(f'素材已变更，请重新盘点并确认：{media.name}')
            files[str(media)] = actual
    listed = set(files)
    for folder in ['素材', '参考视频']:
        for media in (paths['root'] / folder).rglob('*'):
            relative_parts = media.relative_to(paths['root'] / folder).parts
            ignored = any(part.startswith('.') or part.casefold() in {'edit', 'node_modules'} for part in relative_parts)
            if not ignored and not media.is_symlink() and media.is_file() and media.suffix.lower() in MEDIA_EXTENSIONS and str(media.resolve()) not in listed:
                raise FlowError(f'发现尚未盘点的媒体：{media}；请刷新清单。')
    inputs = {'brief': sha256(paths['brief']), 'manifest': sha256(paths['manifest']), 'media': files}
    try:
        from cover import cover_input_hashes
        cover_references = cover_input_hashes(paths, brief)
        if cover_references:
            inputs['cover_references'] = cover_references
    except (ValueError, OSError) as exc:
        raise FlowError(str(exc)) from exc
    return brief, manifest, inputs


def validate_strategy(paths, manifest):
    source = paths['strategy'].read_text(encoding='utf-8-sig') if paths['strategy'].exists() else ''
    if len(source.strip()) < 100 or '尚未生成，不能提交确认' in source:
        raise FlowError('剪辑思路尚未完成；需写明结构、关键内容、节奏、声音和参考取舍。')
    result = {'strategy': sha256(paths['strategy'])}
    if manifest.get('references'):
        if not paths['reference_analysis'].exists() or len(paths['reference_analysis'].read_text(encoding='utf-8-sig').strip()) < 80:
            raise FlowError('有参考视频时，须先完成 reference_analysis.md，注明源时间码与采用/不采用的内容。')
        result['reference_analysis'] = sha256(paths['reference_analysis'])
        # Hypit's detailed reading files are part of the reviewed interpretation,
        # when authored. Adding, removing or changing either changes this digest.
        for name in ['ANALYSIS.md', 'TIMELINE.md']:
            detail = paths['strategy'].parent / name
            if detail.is_file():
                result[name] = sha256(detail)
        try:
            from hypit_reference import validate_reference_evidence
            result['hypit_reference_evidence'] = validate_reference_evidence(paths['root'], manifest)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise FlowError(str(exc)) from exc
    return result


def node_command(command, *args):
    node = shutil.which('node')
    if not node or not LAUNCHER.is_file():
        raise FlowError('缺少 Node.js 或 video-use-local/run.cjs。')
    return [node, str(LAUNCHER), command, *map(str, args)]


def run_capture(command, cwd=None, log=None):
    proc = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace')
    if log:
        Path(log).write_text(proc.stdout + '\n' + proc.stderr, encoding='utf-8')
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-1600:]
        raise FlowError(f'命令执行失败，返回码 {proc.returncode}。{tail}')
    return proc


def probe(path):
    raw = run_capture(node_command('ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path))
    try:
        return json.loads(raw.stdout)
    except ValueError as exc:
        raise FlowError(f'ffprobe 返回无效 JSON：{path}') from exc


def effective_size(stream):
    w, h = int(stream.get('width', 0)), int(stream.get('height', 0))
    for side in stream.get('side_data_list', []):
        if int(round(float(side.get('rotation', 0)))) % 180 == 90:
            w, h = h, w
            break
    return w, h


def validate_edl(paths, brief, manifest, inspect_media=False):
    edl = read_json(paths['edl'])
    if not isinstance(edl, dict):
        raise FlowError('EDL 必须为 JSON 对象。')
    supported = {'version', 'sources', 'ranges', 'grade', 'overlays', 'subtitles', 'total_duration_s', 'music', 'audio_master'}
    unknown = set(edl) - supported
    if unknown:
        raise FlowError('当前后端不支持这些 EDL 字段，不能静默忽略：' + ', '.join(sorted(unknown)))
    if edl.get('version', 1) != 1:
        raise FlowError('当前后端仅支持 EDL version 1。')
    if edl.get('grade') is not None and not isinstance(edl.get('grade'), str):
        raise FlowError('EDL.grade 需为预设名或 FFmpeg 滤镜字符串。')
    ranges = edl.get('ranges')
    sources = edl.get('sources')
    if not isinstance(ranges, list) or not ranges or not isinstance(sources, dict):
        raise FlowError('EDL 需包含非空 ranges 与 sources。')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', str(k)) for k in sources):
        raise FlowError('EDL source id 仅可用英文字母、数字、下划线、短横线。')
    source_manifest = {str(resolve_file(row['path'], paths['root'])): row for row in manifest['sources']}
    dependencies = {'edl': sha256(paths['edl']), 'files': {}}
    expected = 0.0
    selected_media = {}
    for cut in ranges:
        if not isinstance(cut, dict):
            raise FlowError('EDL ranges 每项必须为对象。')
        extra = set(cut) - {'source', 'start', 'end', 'beat', 'note', 'quote', 'reason', 'id', 'shot_id'}
        if extra:
            raise FlowError('当前后端不支持这些镜头字段，不能静默忽略：' + ', '.join(sorted(extra)))
        source = cut.get('source')
        if source not in sources:
            raise FlowError(f'EDL 引用未知素材：{source}')
        media = resolve_file(sources[source], paths['edit'])
        row = source_manifest.get(str(media))
        if row is None:
            raise FlowError(f'EDL 素材不在清单 sources 中，先盘点：{media}')
        try:
            start, end = float(cut['start']), float(cut['end'])
        except (KeyError, ValueError, TypeError):
            raise FlowError('EDL 切点须有数值 start/end。')
        if not math.isfinite(start + end) or start < 0 or end <= start:
            raise FlowError('EDL 必须 0 <= start < end。')
        if end - start < 1 / float(Fraction(str(brief['fps']))):
            raise FlowError('EDL 镜头时长不足一个输出帧，请调整切点。')
        if 'duration' in row and end > float(row['duration']) + 0.05:
            raise FlowError(f'切点超出源素材时长：{source}')
        expected += end - start
        selected_media[str(media)] = row
        dependencies['files'][str(media)] = sha256(media)
    if abs(float(edl.get('total_duration_s', -1)) - expected) > 0.02:
        raise FlowError(f'EDL.total_duration_s 必须与 ranges 总长一致，当前应为 {expected:.3f} 秒。')
    # Brief can intentionally describe an approximate target, while the strategy fixes the actual duration.
    if expected > max(float(brief['target_duration_s']) * 1.25, float(brief['target_duration_s']) + 5):
        raise FlowError('EDL 超出 brief 目标时长较多；先向用户落实时长并更新思路。')
    for overlay in edl.get('overlays') or []:
        if not isinstance(overlay, dict) or set(overlay) - {'file', 'start_in_output', 'duration'}:
            raise FlowError('overlays 仅支持 file/start_in_output/duration，不能静默忽略其他字段。')
        file = resolve_file(overlay['file'], paths['edit'])
        dependencies['files'][str(file)] = sha256(file)
        begin, duration = float(overlay['start_in_output']), float(overlay['duration'])
        if not math.isfinite(begin + duration) or begin < 0 or duration <= 0 or begin + duration > expected + .05:
            raise FlowError('叠加片段的时间范围不在成片内。')
    if edl.get('subtitles'):
        file = resolve_file(edl['subtitles'], paths['edit'])
        dependencies['files'][str(file)] = sha256(file)
    elif brief.get('subtitles_required'):
        raise FlowError('brief 要求字幕，但 EDL 未绑定已核对的字幕文件。')
    if edl.get('audio_master'):
        try:
            from soundtrack import validate_soundtrack
            master_file = validate_soundtrack(edl['audio_master'], paths['edit'], expected, inspect=inspect_media)
            if edl.get('music'):
                raise ValueError('完整预混主轨与额外music不能同时使用。')
            dependencies['files'][str(master_file)] = sha256(master_file)
        except ValueError as exc:
            raise FlowError(str(exc)) from exc
    if edl.get('music'):
        music = edl['music']
        if not isinstance(music, dict) or not music.get('file'):
            raise FlowError('EDL.music 必须包含 file。')
        file = resolve_file(music['file'], paths['edit'])
        dependencies['files'][str(file)] = sha256(file)
        from music import validate_music
        validate_music(music, paths['edit'])
        for option, default in [('volume_db', -24), ('fade_in_s', .5), ('fade_out_s', 1.0)]:
            value = float(music.get(option, default))
            if not math.isfinite(value) or (option != 'volume_db' and not 0 <= value <= expected):
                raise FlowError(f'music.{option} 无效。')
    if inspect_media:
        numerator, denominator = map(float, brief['aspect_ratio'].split(':'))
        target_ratio = numerator / denominator
        seen_ratios = []
        audio_layouts = set()
        for media, row in selected_media.items():
            details = probe(media)
            videos = [s for s in details.get('streams', []) if s.get('codec_type') == 'video']
            audios = [s for s in details.get('streams', []) if s.get('codec_type') == 'audio']
            if not videos or not audios:
                raise FlowError(f'当前 V1 后端要求每个选中素材均有视频和音轨；先标准化/补静音并重新盘点：{Path(media).name}')
            audio_layouts.add((audios[0].get('channels'), audios[0].get('channel_layout')))
            w, h = effective_size(videos[0])
            if min(w, h) <= 0:
                raise FlowError('无法判断源画幅。')
            ratio = w / h
            seen_ratios.append(ratio)
            if abs(ratio / target_ratio - 1) > 0.015:
                raise FlowError(f'素材画幅与 brief 不符；先按批准的裁切/留边方案标准化：{Path(media).name}')
        if max(seen_ratios) - min(seen_ratios) > .002:
            raise FlowError('选中素材的宽高比不一致；请先标准化后重新分镜与确认。')
        # With a complete replacement master, source audio is only a temporary
        # concat track. The renderer explicitly converts mono/stereo to stereo.
        master_normalized = bool(edl.get('audio_master')) and all(channels in (1, 2) for channels, _ in audio_layouts)
        if len(audio_layouts) > 1 and not master_normalized:
            raise FlowError('选中素材的音轨声道布局不一致；请先标准化后重新分镜与确认。')
    return edl, dependencies


def validate_storyboard(paths, edl):
    board = read_json(paths['board'])
    shots = board.get('shots', [])
    if len(shots) != len(edl['ranges']):
        raise FlowError('分镜 shots 数量必须与 EDL ranges 一致。')
    files = {}
    for index, (shot, cut) in enumerate(zip(shots, edl['ranges']), 1):
        if shot.get('missing'):
            raise FlowError(f'分镜 {index} 标记缺素材，不能批准或渲染。')
        if shot.get('source') != cut['source'] or any(abs(float(shot.get(k, -1)) - float(cut[k])) > .001 for k in ['start', 'end']):
            raise FlowError(f'分镜 {index} 与 EDL 的源素材或时间码不一致。')
        if not str(shot.get('key_content', '')).strip() or not shot.get('frame_path'):
            raise FlowError(f'分镜 {index} 缺少关键内容或真实源素材截图。')
        frame_time = float(shot.get('frame', -1))
        if not float(shot['start']) <= frame_time <= float(shot['end']):
            raise FlowError(f'分镜 {index} 的关键帧时间不在镜头范围内。')
        frame = resolve_file(shot['frame_path'], paths['edit'])
        files[str(frame)] = sha256(frame)
        for keyframe in shot.get('keyframes', []):
            if not float(shot['start']) <= float(keyframe.get('time', -1)) <= float(shot['end']):
                raise FlowError(f'分镜 {index} 的扩展关键帧时间不在镜头范围内。')
            image = resolve_file(keyframe['path'], paths['edit'])
            files[str(image)] = sha256(image)
    required = read_json(paths['brief']).get('required_content', [])
    covered = {item for shot in shots for item in shot.get('covers', [])}
    missing = [item for item in required if item not in covered]
    if missing:
        raise FlowError('分镜未覆盖必含内容：' + '；'.join(missing))
    if not paths['board_html'].exists():
        raise FlowError('缺少供用户查看的 storyboard.html。')
    return {'storyboard': sha256(paths['board']), 'storyboard_html': sha256(paths['board_html']), 'frames': files}


def stage_digest(paths, stage):
    brief, manifest, base = current_inputs(paths)
    content = {'inputs': base, **validate_strategy(paths, manifest)}
    if stage in ['storyboard', 'preview']:
        edl, dependencies = validate_edl(paths, brief, manifest)
        content.update(dependencies)
        content.update(validate_storyboard(paths, edl))
        content['renderer_files'] = {str(file): sha256(file) for file in [Path(__file__),
            Path(__file__).with_name('music.py'), Path(__file__).with_name('soundtrack.py'), LAUNCHER,
            ROOT / 'video-use/helpers/render.py', ROOT / 'video-use/helpers/grade.py']}
    if stage == 'preview':
        from cover import validate_cover
        content['cover'] = validate_cover(paths, brief)
        state = state_for(paths)
        record = state.get('renders', {}).get('preview')
        if not record or record.get('storyboard_digest') != stage_digest(paths, 'storyboard'):
            raise FlowError('缺少与当前分镜匹配的预览版。')
        video = resolve_file(record['file'], paths['root'])
        report = resolve_file(record['qa_file'], paths['root'])
        qa = read_json(report)
        actual = sha256(video)
        if not qa.get('technical_passed') or qa.get('video_sha256') != actual:
            raise FlowError('预览技术检查未通过，或预览文件已被修改。')
        content['preview'] = actual
        content['preview_qa'] = sha256(report)
        content['render_record'] = record
    return digest(content)


def require_approval(paths, stage):
    if not isinstance(paths, dict):
        paths = project_paths(paths)
    state = state_for(paths)
    approval = state.get('approvals', {}).get(stage)
    current = stage_digest(paths, stage)
    if not approval or approval.get('digest') != current:
        raise FlowError(f'{stage} 尚未得到当前版本的确认，或内容已修改使旧确认失效。')
    if approval.get('actor') == 'synthetic_test' and not state.get('synthetic'):
        raise FlowError('合成测试确认不能用于真实项目。')
    return current


def approve_stage(args):
    paths = project_paths(args.project)
    state = state_for(paths)
    if not args.message.strip():
        raise FlowError('必须记录真人用户的明确确认原文。')
    if args.synthetic_test and not state.get('synthetic'):
        raise FlowError('--synthetic-test 仅允许合成测试项目。')
    if args.stage in ['storyboard', 'preview']:
        require_approval(paths, 'strategy')
    if args.stage == 'preview':
        require_approval(paths, 'storyboard')
    fingerprint = stage_digest(paths, args.stage)
    state['approvals'][args.stage] = {'digest': fingerprint, 'message': args.message.strip(),
        'approved_at': now(), 'actor': 'synthetic_test' if args.synthetic_test else 'human_user'}
    write_json(paths['state'], state)
    return {'stage': args.stage, 'approved': True, 'digest': fingerprint, 'synthetic': state.get('synthetic', False)}


def quality_report(paths, video, edl, brief, long_edge):
    detail = probe(video)
    streams = detail.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video']
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    checks = []
    def add(name, passed, detail=None):
        checks.append({'check': name, 'passed': bool(passed), 'detail': detail})
    add('video_stream', len(videos) == 1)
    add('audio_stream', len(audios) > 0)
    if not videos:
        raise FlowError('导出无视频流。')
    video_stream = videos[0]
    w, h = effective_size(video_stream)
    add('long_edge', max(w, h) == long_edge, {'width': w, 'height': h, 'expected_long_edge': long_edge})
    a, b = map(float, brief['aspect_ratio'].split(':'))
    add('aspect_ratio', h > 0 and abs((w / h) / (a / b) - 1) < .015)
    fps = Fraction(str(brief['fps']))
    actual_fps = Fraction(video_stream.get('avg_frame_rate', '0'))
    add('frame_rate', abs(float(actual_fps - fps)) < .001, str(actual_fps))
    expected = sum(float(s['end']) - float(s['start']) for s in edl['ranges'])
    duration = float(detail.get('format', {}).get('duration', 0))
    tolerance = max(.15, len(edl['ranges']) / float(fps) + .05)
    add('full_duration', abs(duration - expected) <= tolerance, {'actual': duration, 'expected': expected, 'tolerance': tolerance})
    decode = run_capture(node_command('ffmpeg', '-v', 'error', '-i', video, '-f', 'null', '-'))
    add('full_decode', not decode.stderr.strip(), decode.stderr.strip()[-1000:])
    audio_measurement = None
    if audios:
        measured = run_capture(node_command('ffmpeg', '-hide_banner', '-nostats', '-i', video,
            '-af', 'loudnorm=I=-14:TP=-1:LRA=11:print_format=json', '-vn', '-f', 'null', '-'))
        match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', measured.stderr, re.S)
        if match:
            audio_measurement = json.loads(match.group())
            integrated = float(audio_measurement['input_i'])
            peak = float(audio_measurement['input_tp'])
            audible = math.isfinite(integrated)
            add('audio_measurement', audible or bool(brief.get('allow_silent_audio')), audio_measurement)
            add('audio_peak', (math.isfinite(peak) and peak <= 0.5) or (not audible and bool(brief.get('allow_silent_audio'))), peak)
        else:
            add('audio_measurement', False, '无法解析响度测量。')
    return {'schema_version': 1, 'checked_at': now(), 'video': str(video), 'video_sha256': sha256(video),
        'technical_passed': all(c['passed'] for c in checks), 'checks': checks,
        'scope': '只验证文件、参数、时长、完整解码与音频数值；画面语义、字幕内容、剪辑节奏和听感仍需人工/用户预览确认。'}


def next_version(directory, prefix):
    for index in range(1, 10000):
        path = directory / f'{prefix}_v{index:03d}.mp4'
        if not path.exists() and not path.with_suffix('.qa.json').exists():
            return path
    raise FlowError('版本数量过多。')


def render_project(args, final=False):
    paths = project_paths(args.project)
    state = state_for(paths)
    require_approval(paths, 'strategy')
    board_digest = require_approval(paths, 'storyboard')
    preview_digest = require_approval(paths, 'preview') if final else None
    brief, manifest, _ = current_inputs(paths)
    cover_files = []
    if final:
        from cover import validate_cover
        cover_files = validate_cover(paths, brief).get('deliverables', [])
    edl, _ = validate_edl(paths, brief, manifest, inspect_media=True)
    output_dir = paths['edit'] / ('04_final' if final else '03_preview')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = next_version(output_dir, 'final' if final else 'preview')
    log = output.with_suffix('.render.log')
    # Compose at the same 1920-pixel canvas in both stages. Pixel-positioned overlays
    # would otherwise occupy different fractions of a --draft 1280-pixel canvas.
    raw = output if final and not edl.get('music') and not edl.get('audio_master') else output.with_name(output.stem + '.composition.mp4')
    command = node_command('render', paths['edl'], '-o', raw, '--fps', str(brief['fps']))
    if edl.get('audio_master'):
        # The segment track is temporary and may be silent. Its loudnorm pass
        # would yield -inf/inf measurements; the prepared master is applied below.
        command.append('--no-loudnorm')
    if not final:
        command.append('--preview')
    before = stage_digest(paths, 'storyboard')
    run_capture(command, cwd=paths['root'], log=log)
    delivery_source = raw
    if edl.get('audio_master'):
        from soundtrack import replace_soundtrack
        mastered = output if final else output.with_name(output.stem + '.mastered.mp4')
        duration = sum(float(s['end']) - float(s['start']) for s in edl['ranges'])
        replace_soundtrack(raw, mastered, edl['audio_master'], duration, paths['edit'], log_path=output.with_suffix('.soundtrack.log'))
        delivery_source = mastered
    if edl.get('music'):
        from music import mix_music
        mixed = output if final else output.with_name(output.stem + '.mixed.mp4')
        duration = sum(float(s['end']) - float(s['start']) for s in edl['ranges'])
        mix_music(raw, mixed, edl['music'], duration, paths['edit'], log_path=output.with_suffix('.music.log'))
        delivery_source = mixed
    if not final:
        scale = 'scale=-2:1280' if float(brief['aspect_ratio'].split(':')[0]) < float(brief['aspect_ratio'].split(':')[1]) else 'scale=1280:-2'
        run_capture(node_command('ffmpeg', '-y', '-v', 'error', '-i', delivery_source, '-vf', scale,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '25', '-pix_fmt', 'yuv420p',
            '-c:a', 'copy', '-movflags', '+faststart', output), cwd=paths['root'], log=output.with_suffix('.downscale.log'))
    if stage_digest(paths, 'storyboard') != before or before != board_digest:
        raise FlowError('渲染期间上游输入发生变化，当前导出不得提交确认。')
    if final and stage_digest(paths, 'preview') != preview_digest:
        raise FlowError('渲染期间获批预览发生变化，当前终稿不得交付。')
    qa = quality_report(paths, output, edl, brief, 1920 if final else 1280)
    qa_path = output.with_suffix('.qa.json')
    write_json(qa_path, qa)
    if not qa['technical_passed']:
        raise FlowError(f'技术检查失败，不标记完成。查看：{qa_path}')
    record = {'file': str(output), 'qa_file': str(qa_path), 'created_at': now(),
        'storyboard_digest': board_digest, 'edl_sha256': sha256(paths['edl']),
        'fps': str(brief['fps']), 'long_edge': 1920 if final else 1280,
        'video_sha256': qa['video_sha256'], 'synthetic': bool(state.get('synthetic'))}
    if final:
        record['approved_preview_digest'] = preview_digest
    state['renders']['final' if final else 'preview'] = record
    # A new preview is a new review object even if the edit decisions are unchanged.
    if not final:
        state['approvals'].pop('preview', None)
    write_json(paths['state'], state)
    return {'stage': 'final' if final else 'preview', 'file': str(output), 'qa': str(qa_path),
        'cover_files': cover_files,
        'synthetic': state.get('synthetic', False), 'next': '完整终稿已导出；保留工程与源素材。' if final else '向真人用户发送此全长预览，等待明确确认。'}


def status_project(args):
    paths = project_paths(args.project)
    state = state_for(paths)
    status = {}
    for stage in ['strategy', 'storyboard', 'preview']:
        try:
            fingerprint = stage_digest(paths, stage)
            approved = state.get('approvals', {}).get(stage, {}).get('digest') == fingerprint
            status[stage] = {'ready': True, 'approved_current_version': approved}
        except (FlowError, OSError, ValueError, KeyError, TypeError) as exc:
            status[stage] = {'ready': False, 'approved_current_version': False, 'reason': str(exc)}
    final = state.get('renders', {}).get('final')
    final_current = False
    if final and status['preview']['approved_current_version']:
        try:
            final_current = final.get('approved_preview_digest') == stage_digest(paths, 'preview') and sha256(final['file']) == final['video_sha256']
        except FlowError:
            pass
    return {'project': str(paths['root']), 'synthetic': bool(state.get('synthetic')), 'stages': status,
            'final_current': final_current, 'renders': state.get('renders', {}),
            'approval_note': 'approve 仅记录用户明确确认；脚本不能认证聊天身份。不得由 Agent 自行批准真实项目。'}


def doctor(args):
    proc = run_capture(node_command('doctor'))
    return {'video_use_doctor': proc.stdout.strip(), 'workflow_version': 1,
        'validated_backend_limits': ['固定终稿长边1920，交付预览长边1280', '统一 fps/画幅且每段有音轨', 'overlay 只支持视觉；music 为固定增益伴奏，不是自动ducking', '无云调用'],
        'human_gates': ['strategy', 'storyboard', 'preview']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Codex 五阶段视频工作流（本地确认与版本控制）')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--project', required=True)
    init.add_argument('--name')
    init.add_argument('--synthetic', action='store_true', help='仅用于明确标记的合成验收项目')
    commands.add_parser('doctor')
    for command in ['status', 'render-preview', 'render-final', 'require']:
        item = commands.add_parser(command)
        item.add_argument('--project', required=True)
        if command == 'require':
            item.add_argument('--stage', required=True, choices=['strategy', 'storyboard', 'preview'])
    approval = commands.add_parser('approve', description='仅在真人用户已明确确认当前成果时记录原文，不允许 Agent 自批。')
    approval.add_argument('--project', required=True)
    approval.add_argument('--stage', required=True, choices=['strategy', 'storyboard', 'preview'])
    approval.add_argument('--message', required=True)
    approval.add_argument('--synthetic-test', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init': result = init_project(args)
        elif args.command == 'status': result = status_project(args)
        elif args.command == 'approve': result = approve_stage(args)
        elif args.command == 'doctor': result = doctor(args)
        elif args.command == 'require': result = {'stage': args.stage, 'approved_current_version': True, 'digest': require_approval(args.project, args.stage)}
        elif args.command == 'render-preview': result = render_project(args)
        else: result = render_project(args, final=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FlowError, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
