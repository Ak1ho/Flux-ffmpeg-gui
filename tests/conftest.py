from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from studio.engine import HIDDEN
from studio.paths import ENGINES, defaults


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("媒体 samples")
    video = folder / "画面 one's sample.mp4"
    silent = folder / "无声片段.mp4"
    audio = folder / "测试声音.wav"
    image = folder / "封面.png"
    watermark = folder / "水印.png"
    subtitle = folder / "字'幕.srt"
    ffmpeg = str(ENGINES / "ffmpeg.exe")
    commands = [
        ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
        ["-f", "lavfi", "-i", "color=c=navy:size=240x320:rate=25", "-t", "1", "-c:v", "libx264", str(silent)],
        ["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100", "-t", "2", str(audio)],
        ["-f", "lavfi", "-i", "testsrc=size=320x180", "-frames:v", "1", str(image)],
        ["-f", "lavfi", "-i", "color=c=white:size=40x20", "-frames:v", "1", str(watermark)],
    ]
    for arguments in commands:
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments], capture_output=True, timeout=25, **HIDDEN)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,500\nMediaWorkbench test\n", encoding="utf-8")
    return {"video": video, "silent": silent, "audio": audio, "image": image, "watermark": watermark, "subtitle": subtitle}


@pytest.fixture
def job_factory(tmp_path):
    def make(sources, kind, operation="convert", **extra):
        options = defaults()
        options.update(output_dir=str(tmp_path / "输出 results"), format={"video": "mp4", "audio": "flac", "image": "png", "decrypt": "original"}[kind], collision="rename")
        options.update(extra)
        return {"id": uuid.uuid4().hex, "inputs": [str(source) for source in sources], "kind": kind, "operation": operation, "options": options}
    return make
