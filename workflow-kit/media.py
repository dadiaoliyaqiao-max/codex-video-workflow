"""Local-only media inventory and real-footage storyboard rendering.

Run with the installed video-use Python (Pillow is required). No ASR or network
requests are made. Source descriptions are authored by Codex/the user, not inferred
from filenames or contact sheets by this program.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from PIL import Image, ImageDraw, ImageFont

KIT = Path(__file__).resolve().parent
WORKSPACE = KIT.parent
LAUNCHER = WORKSPACE / "video-use-local" / "run.cjs"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts", ".mpeg", ".mpg", ".3gp", ".wmv", ".flv", ".ts"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".avif"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
MEDIA_EXT = VIDEO_EXT | IMAGE_EXT | AUDIO_EXT
FONT_FILE = Path("C:/Windows/Fonts/msyh.ttc")
SCOPE_NOTE = "技术信息和抽样截图仅用于定位素材，不代表完整观看、内容理解或语义验收；关键内容由 Codex 结合实际画面/转写填写。"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == value:
        return
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tool(command: str, args: list[str]) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node or not LAUNCHER.is_file():
        raise RuntimeError("本地 node / video-use-local/run.cjs 未就绪。")
    result = subprocess.run([node, str(LAUNCHER), command, *map(str, args)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{command} 失败：{result.stderr.strip()[-1200:] or result.stdout.strip()[-1200:]}")
    return result


def finite(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("时间必须是有限秒数")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("时间必须是有限秒数")
    return number


def clock(value: float) -> str:
    milliseconds = max(0, round(value * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def image_frame(source: Path, second: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    args = ["-y", "-v", "error"]
    if source.suffix.lower() not in IMAGE_EXT:
        args += ["-ss", f"{second:.6f}"]
    args += ["-i", str(source), "-frames:v", "1", "-vf",
             "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=black",
             "-update", "1", str(output)]
    tool("ffmpeg", args)
    if not output.is_file() or not output.stat().st_size:
        raise RuntimeError("未得到真实截图，请检查源时码及媒体可解码性。")
    with Image.open(output) as picture:
        picture.verify()


def font(size: int) -> ImageFont.ImageFont:
    return ImageFont.truetype(str(FONT_FILE), size) if FONT_FILE.is_file() else ImageFont.load_default()


def contact_sheet(source: Path, record: dict, output: Path) -> None:
    duration = record.get("duration")
    count = 1 if record["kind"] == "image" else 6
    if count > 1 and (duration is None or duration <= 0):
        raise ValueError("视频没有可用时长，无法抽样")
    seconds = [0.0] if count == 1 else [float(duration) * (i + 0.5) / count for i in range(count)]
    cols = min(count, 3)
    rows = math.ceil(count / cols)
    canvas = Image.new("RGB", (640 * cols, 400 * rows + 52), "#172235")
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), f"{record['id']} 抽样索引（不是完整观看或内容理解）", font=font(22), fill="white")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="frames-", dir=output.parent) as temporary:
        for i, second in enumerate(seconds):
            path = Path(temporary) / f"{i:03d}.png"
            image_frame(source, second, path)
            x, y = (i % cols) * 640, 52 + (i // cols) * 400
            with Image.open(path) as picture:
                canvas.paste(picture.convert("RGB"), (x, y))
            draw.text((x + 10, y + 365), f"源时码 {clock(second)}", font=font(20), fill="white")
    canvas.save(output)


def inspect_file(path: Path, project: Path, prefix: str) -> dict:
    relative = path.relative_to(project).as_posix()
    record: dict[str, Any] = {
        "id": prefix + hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:12],
        "path": str(path.resolve()), "relative_path": relative,
        "sha256": sha256(path), "bytes": path.stat().st_size,
        "kind": "image" if path.suffix.lower() in IMAGE_EXT else ("audio" if path.suffix.lower() in AUDIO_EXT else "video"),
        "duration": None, "width": None, "height": None, "has_audio": False,
    }
    try:
        probe = json.loads(tool("ffprobe", ["-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]).stdout)
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        record["has_audio"] = audio is not None
        if video:
            width, height = int(video["width"]), int(video["height"])
            rotation = next((s.get("rotation") for s in video.get("side_data_list", []) if s.get("rotation") is not None), 0)
            record["coded_width"], record["coded_height"] = width, height
            record["rotation"] = rotation
            if round(float(rotation)) % 360 in (90, 270):
                width, height = height, width
            record.update(width=width, height=height, video_codec=video.get("codec_name"),
                          frame_rate=video.get("avg_frame_rate") or video.get("r_frame_rate"),
                          color_transfer=video.get("color_transfer"))
        if audio:
            record.update(audio_codec=audio.get("codec_name"), sample_rate=audio.get("sample_rate"), channels=audio.get("channels"))
        duration = probe.get("format", {}).get("duration") or (video or audio or {}).get("duration")
        if duration is not None:
            record["duration"] = finite(duration)
        if record["kind"] != "image" and (record["duration"] is None or record["duration"] <= 0):
            record["probe_error"] = "媒体无有效时长"
        if record["kind"] in {"image", "video"} and not video:
            record["probe_error"] = "未检测到可显示视频/图像流"
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        record["probe_error"] = str(error)
    return record


def media_files(folder: Path):
    if not folder.is_dir():
        return
    for current, directories, files in os.walk(folder, followlinks=False):
        directories[:] = sorted(d for d in directories if not d.startswith(".") and d.casefold() not in {"edit", "node_modules"} and not (Path(current) / d).is_symlink())
        for name in sorted(files):
            path = Path(current) / name
            if not name.startswith(".") and not path.is_symlink() and path.suffix.lower() in MEDIA_EXT:
                yield path


STYLE = """body{font:16px/1.55 'Microsoft YaHei',sans-serif;color:#18283b;background:#f4f7fb;margin:24px}h1{font-size:28px}h2{font-size:21px}section,.note{background:white;padding:20px;margin:18px 0;border-radius:8px}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #d8e0ea}th{background:#223c5d;color:white}img{max-width:100%;height:auto}.frames{display:flex;flex-wrap:wrap;gap:16px}.frames figure{margin:0;width:420px}.warn{color:#9d251f;white-space:pre-wrap}.meta{color:#526478;overflow-wrap:anywhere}pre{white-space:pre-wrap}code{overflow-wrap:anywhere}a{color:#165fa4}"""


def page(title: str, body: str) -> str:
    return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style><body><h1>{html.escape(title)}</h1>{body}</body></html>'


def inventory(project: Path) -> int:
    analysis = project / "edit" / "analysis"
    manifest = {"schema_version": 1, "project": str(project), "scope_note": SCOPE_NOTE, "sources": [], "references": []}
    for folder, collection, prefix in [("素材", "sources", "M"), ("参考视频", "references", "R")]:
        for path in media_files(project / folder):
            record = inspect_file(path, project, prefix)
            if record["kind"] != "audio" and not record.get("probe_error"):
                destination = analysis / "contact_sheets" / f"{record['id']}.png"
                try:
                    contact_sheet(path, record, destination)
                    record["contact_sheet"] = destination.relative_to(project / "edit").as_posix()
                except (RuntimeError, ValueError, OSError) as error:
                    record["thumbnail_error"] = str(error)
            manifest[collection].append(record)
    ids = [r["id"] for r in manifest["sources"] + manifest["references"]]
    if len(ids) != len(set(ids)):
        raise ValueError("检测到素材 ID 冲突，请报告后处理。")
    write_json(analysis / "media_manifest.json", manifest)
    body = f'<p class="note">{html.escape(SCOPE_NOTE)}</p>'
    for collection, title in [("sources", "待剪素材"), ("references", "参考资料（不自动作为成片素材）")]:
        body += f"<h2>{title}</h2>"
        if not manifest[collection]:
            body += "<p>尚无可识别媒体文件。</p>"
        for record in manifest[collection]:
            body += f'<section><h3>{html.escape(record["id"])}</h3><p class="meta">{html.escape(record["relative_path"])}</p><p>{html.escape(record["kind"])}；时长 {html.escape(str(record["duration"]))} 秒；显示尺寸 {record["width"]}×{record["height"]}；音轨 {record["has_audio"]}</p>'
            if record.get("contact_sheet"):
                relative = Path(record["contact_sheet"]).relative_to("analysis").as_posix()
                body += f'<img src="{html.escape(relative, quote=True)}" alt="原素材抽样索引">'
            if record.get("probe_error") or record.get("thumbnail_error"):
                body += f'<p class="warn">{html.escape(record.get("probe_error") or record["thumbnail_error"])}</p>'
            body += "</section>"
    write_text(analysis / "素材索引.html", page("素材技术盘点与抽样索引", body))
    print(json.dumps({"manifest": str(analysis / "media_manifest.json"), "index": str(analysis / "素材索引.html"), "sources": len(manifest["sources"]), "references": len(manifest["references"]), "note": SCOPE_NOTE}, ensure_ascii=False))
    return 0


def require_strategy(project: Path) -> None:
    result = subprocess.run([sys.executable, str(KIT / "flow.py"), "require", "--project", str(project), "--stage", "strategy"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError("剪辑思路尚未确认或已变更：" + (result.stderr.strip() or result.stdout.strip()))


def plain(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def asset_path(value: str, edit: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else edit / path


def storyboard(project: Path) -> int:
    require_strategy(project)  # Mandatory before writing any derived storyboard artifact.
    edit = project / "edit"
    board_path = edit / "02_storyboard" / "storyboard.json"
    board = read_json(board_path)
    if not isinstance(board, dict):
        raise ValueError("storyboard.json 顶层必须是对象。")
    manifest = read_json(edit / "analysis" / "media_manifest.json")
    brief = read_json(edit / "brief.json")
    source_map = {s["id"]: s for s in manifest["sources"]}
    shots = board.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("storyboard.json 必须有非空 shots 数组。")
    if not all(isinstance(shot, dict) for shot in shots):
        raise ValueError("shots 中每项必须是镜头对象。")
    required = brief.get("required_content", [])
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise ValueError("brief.required_content 必须是字符串列表。")
    errors: list[str] = []
    allowed_top = {"schema_version", "version", "title", "shots", "grade", "overlays", "subtitles", "music", "audio_master"}
    for key in set(board) - allowed_top:
        errors.append(f"未支持的分镜顶层字段：{key}；须明确实现或移除计划后重新确认。")
    allowed_shot = {"id", "source", "start", "end", "key_content", "frame", "frame_path", "caption", "audio", "purpose", "transition", "covers", "keyframes", "missing"}
    body = f'<p class="note">{html.escape(SCOPE_NOTE)}</p>'
    body += '<p>下列图片均由原素材真实抽取；时间为源视频秒数。镜头表中的文案、音频和效果是计划，只有成功编译进 EDL 的功能才会进入后续渲染。</p>'
    timeline = 0.0
    seen = set()
    ranges, used_sources = [], {}
    covered = set()
    for index, shot in enumerate(shots):
        shot_errors = []
        sid = str(shot.get("id", f"S{index+1:03d}"))
        if sid in seen:
            shot_errors.append("镜头 ID 重复")
        seen.add(sid)
        for key in set(shot) - allowed_shot:
            shot_errors.append(f"未支持字段 {key}")
        source_id = shot.get("source")
        record = source_map.get(source_id)
        missing = bool(shot.get("missing")) or record is None
        shot["id"] = sid
        shot["missing"] = missing
        start, end, duration = 0.0, 0.0, 0.0
        try:
            start, end = finite(shot["start"]), finite(shot["end"])
            if start < 0 or end <= start:
                raise ValueError("需满足 0 ≤ start < end")
            duration = end - start
        except (KeyError, TypeError, ValueError) as error:
            shot_errors.append("无效源时间范围：" + str(error))
        key_content = shot.get("key_content", "")
        if not isinstance(key_content, str) or not key_content.strip():
            shot_errors.append("缺少 key_content 关键内容描述")
        covers = shot.get("covers", [])
        if not isinstance(covers, list) or not all(isinstance(c, str) for c in covers):
            shot_errors.append("covers 必须为要点字符串列表")
            covers = []
        covered.update(covers)
        if any(c not in required for c in covers):
            shot_errors.append("covers 包含 brief.required_content 中不存在的要点")
        transition = shot.get("transition", "cut")
        if transition not in {"cut", "none", "", None}:
            shot_errors.append(f"转场 {transition} 尚未预处理，当前只直接编译 cut/none")
        audio = shot.get("audio", "source")
        if audio == 'master' and board.get('audio_master'):
            pass
        elif not isinstance(audio, str) or audio.strip().lower() not in {"", "source", "original", "原声", "保留原声", "同期声", "保留同期声"}:
            shot_errors.append("镜头音频计划尚未预处理；直接编译仅支持保留源音轨，背景音乐请使用受控 music 扩展")
        caption = shot.get("caption", "")
        if caption and not board.get("subtitles"):
            shot_errors.append("有字幕文案但顶层 subtitles 尚未指向已准备的字幕文件")
        images = []
        if missing:
            shot_errors.append("缺素材：先补拍/提供有效 source，再生成分镜")
            shot.pop("frame_path", None)
        elif record:
            source = Path(record["path"])
            if not source.is_file():
                shot["missing"] = True
                shot_errors.append("原素材文件已不存在")
            elif record.get("sha256") != sha256(source):
                shot_errors.append("原素材已变化，须重新 inventory 并确认剪辑思路")
            elif record.get("probe_error"):
                shot_errors.append("素材技术盘点失败：" + record["probe_error"])
            else:
                if record.get("kind") != "video":
                    shot_errors.append("图片/音频镜头须先封装成统一画布的视频并纳入素材清单，当前不可直接编译")
                source_duration = record.get("duration")
                if record.get("kind") == "video" and (source_duration is None or end > float(source_duration) + 0.02):
                    shot_errors.append("镜头结束时间超出原视频有效时长")
                frame_time = shot.get("frame", (start + end) / 2)
                try:
                    frame_time = finite(frame_time)
                    if not start <= frame_time < end:
                        raise ValueError("frame 必须落在 [start,end) 内")
                    if source_duration and frame_time >= float(source_duration):
                        raise ValueError("frame 超出源时长")
                    shot["frame"] = frame_time
                    frame_path = edit / "02_storyboard" / "frames" / f"shot-{index+1:03d}.png"
                    if record.get("kind") != "audio":
                        image_frame(source, frame_time, frame_path)
                        shot["frame_path"] = frame_path.relative_to(edit).as_posix()
                        images.append((frame_path, frame_time, "主关键帧"))
                except (TypeError, ValueError, RuntimeError) as error:
                    shot_errors.append("主关键帧失败：" + str(error))
                    shot.pop("frame_path", None)
                keyframes = shot.get("keyframes", [])
                if not isinstance(keyframes, list):
                    shot_errors.append("keyframes 必须是列表")
                    keyframes = []
                for number, item in enumerate(keyframes, 1):
                    try:
                        second = finite(item["time"])
                        if not start <= second < end:
                            raise ValueError("关键帧 time 必须落在 [start,end) 内")
                        target = edit / "02_storyboard" / "frames" / f"shot-{index+1:03d}-key-{number:02d}.png"
                        image_frame(source, second, target)
                        item["path"] = target.relative_to(edit).as_posix()
                        images.append((target, second, plain(item.get("description", "补充关键帧"))))
                    except (KeyError, TypeError, ValueError, RuntimeError) as error:
                        shot_errors.append(f"补充关键帧 {number} 失败：{error}")
                        if isinstance(item, dict):
                            item.pop("path", None)
                ranges.append({"source": source_id, "start": start, "end": end, "beat": plain(shot.get("purpose") or key_content), "note": sid})
                used_sources[source_id] = str(source.resolve())
        body += f'<section><h2>{html.escape(sid)} · 成片 {clock(timeline)}–{clock(timeline+duration)}（{duration:.3f} 秒）</h2>'
        body += f'<p><b>关键内容：</b>{html.escape(plain(key_content))}</p><p><b>覆盖必含内容：</b>{html.escape("；".join(covers) or "无")}</p>'
        body += f'<p class="meta">源：{html.escape(str(source_id))} · {html.escape(record["relative_path"] if record else "缺素材")}<br>源范围：{clock(start)}–{clock(end)}</p><div class="frames">'
        for path, second, description in images:
            relative = path.relative_to(edit / "02_storyboard").as_posix()
            body += f'<figure><img src="{html.escape(relative, quote=True)}" alt="原素材真实截图"><figcaption>{html.escape(description)} · 源 {clock(second)}</figcaption></figure>'
        body += '</div><table><tr><th>字幕/口播文案</th><th>音频计划</th><th>镜头目的</th><th>转场</th></tr>'
        displayed_audio = '全片确定预混主轨（替换现场声；人声、配乐、音效连续）' if audio == 'master' else audio
        body += '<tr>' + ''.join(f'<td>{html.escape(plain(v))}</td>' for v in [caption, displayed_audio, shot.get("purpose", ""), transition]) + '</tr></table>'
        if shot_errors:
            body += '<p class="warn">' + html.escape("\n".join(shot_errors)) + '</p>'
            errors.extend(f"{sid}：{error}" for error in shot_errors)
        body += '</section>'
        timeline += duration
    absent = [content for content in required if content not in covered]
    if absent:
        errors.append("未覆盖必含内容：" + "；".join(absent))
    subtitles = board.get("subtitles")
    if subtitles and (not isinstance(subtitles, str) or not asset_path(subtitles, edit).is_file()):
        errors.append("顶层 subtitles 未指向存在的字幕文件")
    overlays = board.get("overlays", [])
    if not isinstance(overlays, list):
        errors.append("overlays 必须是列表")
    else:
        for i, overlay in enumerate(overlays):
            try:
                if set(overlay) - {"file", "start_in_output", "duration"}:
                    raise ValueError("含尚未实现的叠加属性")
                if not asset_path(overlay["file"], edit).is_file():
                    raise ValueError("叠加文件不存在")
                if finite(overlay["start_in_output"]) < 0 or finite(overlay["duration"]) <= 0:
                    raise ValueError("叠加时间无效")
                if finite(overlay["start_in_output"]) + finite(overlay["duration"]) > timeline + 0.02:
                    raise ValueError("叠加结束时间超出成片时长")
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"overlay {i+1}：{error}")
    if board.get('audio_master'):
        try:
            from soundtrack import validate_soundtrack
            validate_soundtrack(board['audio_master'], edit, timeline, inspect=True)
            if board.get('music'):
                raise ValueError('audio_master 已是完整混音，不能再叠加 music。')
            body = '<section><h2>全片声音主轨</h2><pre>' + html.escape(json.dumps(board['audio_master'], ensure_ascii=False, indent=2)) + '</pre><p>固定完整预混主轨替换现场声，预览与终稿复用同一文件。</p></section>' + body
        except (ValueError, RuntimeError) as error:
            errors.append('全片声音：' + str(error))
    music = board.get("music")
    if music is not None:
        try:
            if not isinstance(music, dict) or set(music) - {"file", "volume_db", "loop", "fade_in_s", "fade_out_s"}:
                raise ValueError("music 必须是受控配乐对象，且不可包含未知键")
            if not asset_path(music["file"], edit).is_file():
                raise ValueError("配乐文件不存在")
            if "loop" in music and not isinstance(music["loop"], bool):
                raise ValueError("loop 必须是布尔值")
            finite(music.get("volume_db", -24))
            if finite(music.get("fade_in_s", 0.5)) < 0 or finite(music.get("fade_out_s", 1)) < 0:
                raise ValueError("配乐淡变时长不可为负")
            body = '<section><h2>背景音乐计划</h2><pre>' + html.escape(json.dumps(music, ensure_ascii=False, indent=2)) + '</pre><p>由本地 music.py 在剪辑后混音，两阶段使用同一配置。</p></section>' + body
        except (KeyError, TypeError, ValueError) as error:
            errors.append("配乐：" + str(error))
    body = '<section><h2>必含内容覆盖</h2>' + ''.join(f'<p>{"已规划" if content in covered else "缺少镜头"}：{html.escape(content)}</p>' for content in required) + '</section>' + body
    body += '<section><h2>编译状态</h2>' + (f'<pre class="warn">{html.escape(chr(10).join(errors))}</pre><p>分镜 HTML 已生成；EDL 未生成，不能批准分镜或渲染。先落实缺项再重新生成。</p>' if errors else '<p>EDL 已生成；等待用户确认分镜。本程序不自动批准任何阶段。</p>') + '</section>'
    write_json(board_path, board)
    write_text(edit / "02_storyboard" / "storyboard.html", page(plain(board.get("title", "关键内容分镜")), body))
    write_json(edit / "02_storyboard" / "compile_report.json", {"ok": not errors, "errors": errors, "total_duration_s": timeline, "uncovered_required_content": absent})
    edl_path = edit / "edl.json"
    if errors:
        if edl_path.is_file():
            edl_path.unlink()
    else:
        edl = {"version": 1, "sources": used_sources, "ranges": ranges, "grade": board.get("grade", "none"), "overlays": overlays, "total_duration_s": timeline}
        if subtitles:
            edl["subtitles"] = subtitles
        if "music" in board:
            edl["music"] = board["music"]
        if 'audio_master' in board:
            edl['audio_master'] = board['audio_master']
        write_json(edl_path, edl)
    print(json.dumps({"storyboard": str(edit / "02_storyboard" / "storyboard.html"), "edl_ready": not errors, "errors": errors}, ensure_ascii=False))
    return 2 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="本地素材技术索引和真实关键内容分镜；不调用云服务。")
    parser.add_argument("command", choices=["inventory", "storyboard"])
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    if not project.is_dir():
        parser.error("项目目录不存在；先运行 flow.py init。")
    try:
        return inventory(project) if args.command == "inventory" else storyboard(project)
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
