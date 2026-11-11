"""Bind reviewed cover images to the existing combined preview approval.

Only validates local files. It never creates artwork or records an approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


def _read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _hash(path):
    if not path.is_file():
        raise ValueError('封面或来源文件不存在：' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value, edit):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('封面清单路径必须为非空字符串。')
    path = Path(value)
    return path.resolve() if path.is_absolute() else (edit / path).resolve()


def _target_size(value):
    if value is None:
        return None
    if isinstance(value, dict):
        value = [value.get('width'), value.get('height')]
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in value)):
        raise ValueError('cover.size 应为正整数 [宽,高] 或 {width,height}，未确定时为 null。')
    return tuple(value)


def cover_input_hashes(paths_or_edit, brief):
    """Reference art/logo inputs bind to strategy before any candidate cover exists."""
    edit = Path(paths_or_edit['edit'] if isinstance(paths_or_edit, dict) else paths_or_edit).resolve()
    config = brief.get('cover') or {}
    if not isinstance(config, dict):
        raise ValueError('brief.cover 必须为对象。')
    references = config.get('reference_files', [])
    if not isinstance(references, list):
        raise ValueError('cover.reference_files 必须为路径列表。')
    return {str(path): _hash(path) for path in sorted({_resolve(value, edit) for value in references})}


def validate_cover(paths_or_edit, brief):
    """Return hashable cover data and actual deliverables; legacy projects stay optional."""
    edit = Path(paths_or_edit['edit'] if isinstance(paths_or_edit, dict) else paths_or_edit).resolve()
    config = brief.get('cover')
    if config is None:
        config = {}
    if not isinstance(config, dict) or not isinstance(config.get('required', False), bool):
        raise ValueError('brief.cover 必须为对象，required 必须为 true 或 false。')
    required = config.get('required', False)
    manifest = edit / 'cover/cover_manifest.json'
    if not manifest.exists():
        if required:
            raise ValueError('本项目要求封面；预览确认前须准备 edit/cover/cover_manifest.json 与实际 PNG/JPG。')
        return {}
    data = _read(manifest)
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('封面清单必须为 version 1 对象。')
    entries = data.get('files')
    if not isinstance(entries, list) or not entries:
        raise ValueError('封面清单 files 需至少包含一张待确认 PNG/JPG。')
    if not isinstance(data.get('title', ''), str):
        raise ValueError('封面清单 title 必须为字符串。')
    if config.get('title') and config['title'] != data.get('title'):
        raise ValueError('封面清单标题与已确定的 brief.cover.title 不一致。')
    target = _target_size(config.get('size'))
    deliverables, files = [], {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('file'):
            raise ValueError('封面 files 每项必须包含 file。')
        path = _resolve(entry['file'], edit)
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
            raise ValueError('待交付封面仅支持 PNG/JPG：' + path.name)
        if str(path) in files:
            raise ValueError('封面清单不能重复引用同一成品。')
        checksum = _hash(path)
        try:
            with Image.open(path) as picture:
                if picture.format not in {'PNG', 'JPEG'}:
                    raise ValueError('封面文件内容不是 PNG/JPG：' + path.name)
                if target and picture.size != target:
                    raise ValueError('封面尺寸与 brief.cover.size 不一致：' + path.name)
                picture.verify()
            with Image.open(path) as decoded:
                decoded.load()
        except OSError as exc:
            raise ValueError('封面图片无法解码：' + path.name) from exc
        files[str(path)] = checksum
        deliverables.append(str(path))
    source_files = data.get('source_files', [])
    references = config.get('reference_files', [])
    if not isinstance(source_files, list) or not isinstance(references, list):
        raise ValueError('封面 source_files 与 cover.reference_files 必须为路径列表。')
    sources = {_resolve(value, edit) for value in source_files}
    expected_references = {_resolve(value, edit) for value in references}
    if not expected_references <= sources:
        raise ValueError('封面清单 source_files 未包含 brief 中声明的全部参考图。')
    source_hashes = {str(path): _hash(path) for path in sorted(sources)}
    return {'manifest': _hash(manifest), 'files': files, 'source_files': source_hashes,
            'deliverables': deliverables}
