"""Synthetic-only integration checks for media.py. Does not touch user footage."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from PIL import Image
import media
import hypit_reference


def flow(project: Path, *args: str, expected: int = 0):
    result = subprocess.run([sys.executable, str(media.KIT / "flow.py"), *args, "--project", str(project)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == expected, result.stdout + result.stderr
    return result


def main():
    project = media.KIT / "_verification" / "media" / ("run-" + uuid.uuid4().hex[:8])
    flow(project, "init", "--name", "合成素材媒体工具验证", "--synthetic")
    source = project / "素材" / "synthetic-colors.mp4"
    media.tool("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)])
    media.image_frame(source, 1.0, project / "素材" / "synthetic-still.png")
    media.tool("ffmpeg", ["-y", "-v", "error", "-i", str(source), "-vn", str(project / "素材" / "synthetic-sound.wav")])
    shutil.copy2(source, project / "参考视频" / "synthetic-reference.mp4")
    assert media.inventory(project) == 0
    edit = project / "edit"
    manifest = media.read_json(edit / "analysis" / "media_manifest.json")
    assert len(manifest["sources"]) == 3 and len(manifest["references"]) == 1
    record = next(r for r in manifest["sources"] if r["kind"] == "video")
    assert record["sha256"] == media.sha256(source)
    assert record["width"] == 320 and record["height"] == 180 and record["has_audio"]
    assert (edit / record["contact_sheet"]).is_file()
    brief = media.read_json(edit / "brief.json")
    brief.update(objective="仅验证本地技术流程，不使用真实素材、不调用模型。", target_duration_s=4, aspect_ratio="16:9", fps="24", required_content=["合成测试图开场", "合成测试图结束"])
    media.write_json(edit / "brief.json", brief)
    board = {"title": "合成测试分镜（非真实用户剪辑）", "shots": [
        {"id": "S001", "source": record["id"], "start": 0.25, "end": 2.25, "frame": 1, "key_content": "合成测试图的前段，验证真实截帧。", "covers": ["合成测试图开场"], "caption": "", "audio": "source", "transition": "cut", "keyframes": [{"time": 0.5, "description": "第一帧证据"}, {"time": 2, "description": "同镜头稍后画面"}]},
        {"id": "S002", "source": record["id"], "start": 3, "end": 5, "frame": 4, "key_content": "合成测试图后段，验证源时码和成片时码。", "covers": ["合成测试图结束"], "audio": "保留原声", "transition": "none"}
    ]}
    board_path = edit / "02_storyboard" / "storyboard.json"
    media.write_json(board_path, board)
    try:
        media.storyboard(project)
        raise AssertionError("未确认思路却生成了分镜")
    except ValueError as error:
        assert "尚未确认" in str(error)
    assert not (edit / "02_storyboard" / "storyboard.html").exists()
    (edit / "01_strategy" / "strategy.md").write_text("合成测试专用思路：前两秒展示合成测试图，后两秒展示同一合成测试图的后段。保留测试正弦波音频，顺序硬切，不添加人物或真实事件，不宣称任何真实剪辑已经验证。必须覆盖合成开场和结束，画幅十六比九，帧率二十四，输出目标四秒。该思路仅用于验证本地工具的确认和截图机制。", encoding="utf-8")
    (edit / "01_strategy" / "reference_analysis.md").write_text("参考为相同的合成测试图，不代表真实平台样片或用户参考。0至6秒包含合成图形运动以及正弦波。仅复用测试的画幅与帧率，不评估叙事、人物、审美或参考视频学习能力。测试脚本仅验证工具能记录源时码和真实抽帧。", encoding="utf-8")
    hypit_reference.prepare_reference(project)
    flow(project, "approve", "--stage", "strategy", "--message", "合成自动化测试专用，非用户确认", "--synthetic-test")
    assert media.storyboard(project) == 0
    edl = media.read_json(edit / "edl.json")
    assert len(edl["ranges"]) == 2 and edl["total_duration_s"] == 4
    complete_board = media.read_json(board_path)
    for shot in complete_board["shots"]:
        with Image.open(edit / shot["frame_path"]) as picture:
            assert picture.size == (640, 360)
    flow(project, "approve", "--stage", "storyboard", "--message", "合成自动化测试专用分镜确认", "--synthetic-test")
    flow(project, "require", "--stage", "storyboard")
    # Unsupported plans remain visible in HTML while preventing a stale EDL.
    blocked = json.loads(json.dumps(complete_board))
    blocked["shots"][0]["caption"] = "测试字幕尚未准备 SRT"
    media.write_json(board_path, blocked)
    assert media.storyboard(project) == 2
    assert not (edit / "edl.json").exists()
    assert "测试字幕尚未准备 SRT" in (edit / "02_storyboard" / "storyboard.html").read_text(encoding="utf-8")
    blocked = json.loads(json.dumps(complete_board))
    blocked["shots"][0]["transition"] = "crossfade"
    media.write_json(board_path, blocked)
    assert media.storyboard(project) == 2 and not (edit / "edl.json").exists()
    blocked = json.loads(json.dumps(complete_board))
    blocked["shots"][0]["source"] = "M_missing"
    media.write_json(board_path, blocked)
    assert media.storyboard(project) == 2
    assert media.read_json(board_path)["shots"][0]["missing"] is True
    assert not (edit / "edl.json").exists()
    # Restore the valid artifact for visual review, without re-approving it.
    media.write_json(board_path, complete_board)
    assert media.storyboard(project) == 0
    report = {"ok": True, "synthetic_only": True, "project": str(project), "checks": ["media probe/hash/contact sheet", "image/audio/video classification", "strategy gate blocks writes", "real source-frame storyboard and source/output timecodes", "key-content coverage", "EDL compatibility with flow.py", "missing subtitles keep HTML and remove EDL", "unsupported transition blocked", "missing media blocked"], "storyboard": str(edit / "02_storyboard" / "storyboard.html")}
    media.write_json(project / "media-test-report.json", report)
    media.write_json(media.KIT / "_verification" / "media" / "latest-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
