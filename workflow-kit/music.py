"""Deterministic optional background-music pass for both preview and final.

This module performs local FFmpeg work only. It never downloads audio or invokes a model.
"""
from pathlib import Path
import json
import math
import shutil
import subprocess
import re

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / 'video-use-local/run.cjs'
ALLOWED = {'file', 'volume_db', 'loop', 'fade_in_s', 'fade_out_s'}


def validate_music(music, edl_dir):
    if not isinstance(music, dict) or not music.get('file'):
        raise ValueError('music 必须为带 file 的对象。')
    unknown = set(music) - ALLOWED
    if unknown:
        raise ValueError('尚不支持的 music 参数：' + ', '.join(sorted(unknown)))
    file = Path(music['file'])
    if not file.is_absolute():
        file = Path(edl_dir) / file
    file = file.resolve()
    if not file.is_file():
        raise ValueError('背景音乐文件不存在：' + str(file))
    values = {}
    for key, default in [('volume_db', -24), ('fade_in_s', 0.5), ('fade_out_s', 1.0)]:
        value = music.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f'music.{key} 需为有限数值。')
        values[key] = float(value)
    if not -60 <= values['volume_db'] <= 0:
        raise ValueError('music.volume_db 范围为 -60 至 0 dB。')
    if min(values['fade_in_s'], values['fade_out_s']) < 0:
        raise ValueError('音乐淡入淡出时长不能为负数。')
    if not isinstance(music.get('loop', True), bool):
        raise ValueError('music.loop 必须为 true 或 false。')
    return {'file': str(file), 'loop': music.get('loop', True), **values}


def _run(arguments):
    node = shutil.which('node')
    if not node or not LAUNCHER.is_file():
        raise ValueError('缺少本地 Node.js 或 video-use 启动入口。')
    result = subprocess.run([node, str(LAUNCHER), 'ffmpeg', *map(str, arguments)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('背景音乐处理失败：' + result.stderr[-2000:])
    return result


def _measure(stderr):
    for block in reversed(re.findall(r'\{[^{}]+\}', stderr, re.S)):
        try:
            data = json.loads(block)
            keys = ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']
            if all(key in data and math.isfinite(float(data[key])) for key in keys):
                return data
        except (ValueError, TypeError):
            continue
    raise ValueError('未取得有效响度测量，不能把静音或测量失败视为混音成功。')


def mix_music(input_path, output_path, music, duration, edl_dir, log_path=None):
    """Mix a locked music configuration into a composition without re-encoding video.

    Returns measured first-pass loudness. This is fixed background gain, not auto ducking.
    """
    config = validate_music(music, edl_dir)
    input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
    if not input_path.is_file() or input_path == output_path or output_path == Path(config['file']):
        raise ValueError('混音输入必须存在，输出不能覆盖输入或背景音乐。')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('混音成片时长无效。')
    if config['fade_in_s'] + config['fade_out_s'] > duration:
        raise ValueError('音乐淡入与淡出之和超过成片时长，请先调整已审配置。')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = ['-hide_banner', '-nostdin', '-y', '-i', input_path]
    if config['loop']:
        inputs += ['-stream_loop', '-1']
    inputs += ['-i', config['file']]
    filters = ['aresample=48000', 'asetpts=PTS-STARTPTS', f"volume={config['volume_db']:.6f}dB",
               f'atrim=duration={duration:.6f}', f'apad=whole_dur={duration:.6f}']
    if config['fade_in_s']:
        filters += [f"afade=t=in:st=0:d={config['fade_in_s']:.6f}"]
    if config['fade_out_s']:
        filters += [f"afade=t=out:st={duration-config['fade_out_s']:.6f}:d={config['fade_out_s']:.6f}"]
    prefix = ('[0:a:0]aresample=48000,asetpts=PTS-STARTPTS[voice];'
              '[1:a:0]' + ','.join(filters) + '[music];'
              '[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,')
    first = _run(inputs + ['-filter_complex', prefix + 'loudnorm=I=-14:TP=-1:LRA=11:print_format=json[a]',
                          '-map', '[a]', '-vn', '-t', str(duration), '-f', 'null', '-'])
    measured = _measure(first.stderr)
    loudnorm = ('loudnorm=I=-14:TP=-1:LRA=11:linear=true:print_format=json'
                f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}")
    second = _run(inputs + ['-filter_complex', prefix + loudnorm + '[a]', '-map', '0:v:0', '-map', '[a]',
                           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                           '-t', str(duration), '-movflags', '+faststart', output_path])
    if log_path:
        Path(log_path).write_text(first.stderr + '\nSECOND PASS\n' + second.stderr, encoding='utf-8')
    return {'file': str(output_path), 'music': config, 'first_pass_loudness': measured,
            'method': 'fixed background gain, then two-pass loudnorm; no automatic ducking'}
