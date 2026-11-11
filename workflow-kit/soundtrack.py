"""Apply an explicitly prepared full-timeline soundtrack without cutting speech."""
from pathlib import Path
import json
import math
import subprocess

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / 'video-use-local/run.cjs'


def validate_soundtrack(config, edit, duration, inspect=False):
    if not isinstance(config, dict) or set(config) != {'file', 'mode'} or config.get('mode') != 'replace':
        raise ValueError('audio_master 仅支持 {file, mode:"replace"} 的全片确定预混主轨。')
    value = config.get('file')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('audio_master.file 必须为非空文件路径。')
    file = Path(value)
    file = file.resolve() if file.is_absolute() else (Path(edit) / file).resolve()
    if not file.is_file():
        raise ValueError('audio_master 预混文件不存在：' + str(file))
    if inspect:
        result = subprocess.run(['node', str(LAUNCHER), 'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(file)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
        data = json.loads(result.stdout)
        if not any(s.get('codec_type') == 'audio' for s in data.get('streams', [])):
            raise ValueError('audio_master 没有音轨。')
        actual = float(data.get('format', {}).get('duration', 0))
        if not math.isfinite(actual) or abs(actual - duration) > .05:
            raise ValueError(f'audio_master 时长{actual:.3f}与成片{duration:.3f}不匹配。')
    return file


def replace_soundtrack(source, target, config, duration, edit, log_path=None):
    file = validate_soundtrack(config, edit, duration, inspect=True)
    command = ['node', str(LAUNCHER), 'ffmpeg', '-y', '-hide_banner', '-nostdin', '-i', str(source), '-i', str(file),
        '-map', '0:v:0', '-map', '1:a:0', '-t', f'{duration:.9f}', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k',
        '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(target)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if log_path:
        Path(log_path).write_text(result.stdout + '\n' + result.stderr, 'utf-8')
    if result.returncode:
        raise ValueError('全片预混主轨替换失败：' + result.stderr[-2000:])
