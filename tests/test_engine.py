from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from studio.catalog import FORMATS, classify, platform_for
from studio.engine import HIDDEN, execute, probe, publish, stage_path, tempo_filters, validate_options
from studio.paths import ROOT, defaults


def quiet(*args, **kwargs):
    pass


VIDEO_CASES = [
    ("convert", {"format": "mkv"}), ("compress", {"quality": 29}), ("trim", {"start": 0.25, "end": 1.25}),
    ("resize", {"width": 160, "height": 0}), ("crop", {"width": 100, "height": 100, "crop_x": 10, "crop_y": 10}),
    ("rotate", {"rotation": "90"}), ("speed", {"speed": 2}), ("mute", {}), ("extract", {"format": "mp3"}),
    ("gif", {"format": "gif", "width": 160, "fps": 8, "end": 1}), ("snapshot", {"format": "png", "start": 0.3}),
    ("concat", {}), ("watermark", {}), ("subtitle", {}), ("remux", {"format": "mkv"}),
]


@pytest.mark.parametrize("operation,options", VIDEO_CASES)
def test_video_operations(media, job_factory, operation, options):
    inputs = [media["video"], media["silent"]] if operation == "concat" else [media["video"]]
    arguments = dict(options)
    if operation in {"watermark", "subtitle"}:
        arguments["asset"] = str(media[operation])
    job = job_factory(inputs, "video", operation, **arguments)
    source_hash = hashlib.sha256(media["video"].read_bytes()).hexdigest()
    result = execute(job, quiet)
    output = Path(result["output"])
    assert output.is_file() and output.stat().st_size > 0
    assert not stage_path(job).exists()
    assert hashlib.sha256(media["video"].read_bytes()).hexdigest() == source_hash
    information = probe(output, job["options"])
    if operation == "mute":
        assert information["audio"] is None
    if operation == "extract":
        assert information["video"] is None and information["audio"]
    if operation == "resize":
        assert information["video"]["width"] == 160
    if operation == "rotate":
        assert information["video"]["width"] == 180 and information["video"]["height"] == 320
    if operation in {"trim", "speed"}:
        assert 0.85 < information["duration"] < 1.2
    if operation == "concat":
        assert 2.8 < information["duration"] < 3.4
        assert information["audio"]


@pytest.mark.parametrize("operation,options", [("convert", {}), ("trim", {"start": 0.1, "end": 1.1}), ("normalize", {"loudness": -16}), ("volume", {"gain": -6}), ("speed", {"speed": 0.25}), ("fade", {"fade_in": 0.25, "fade_out": 0.25}), ("denoise", {"noise_floor": -30}), ("concat", {})])
def test_audio_operations(media, job_factory, operation, options):
    inputs = [media["audio"]] * (2 if operation == "concat" else 1)
    job = job_factory(inputs, "audio", operation, **options)
    result = execute(job, quiet)
    information = probe(Path(result["output"]), job["options"])
    assert information["audio"]
    if operation == "speed":
        assert 7.5 < information["duration"] < 8.5
    if operation == "concat":
        assert 3.95 < information["duration"] < 4.1


@pytest.mark.parametrize("operation,options", [("convert", {"format": "jpg"}), ("compress", {"format": "webp", "image_quality": 65}), ("resize", {"width": 0, "height": 90}), ("crop", {"width": 101, "height": 99}), ("rotate", {"rotation": "hflip"})])
def test_image_operations(media, job_factory, operation, options):
    job = job_factory([media["image"]], "image", operation, **options)
    result = execute(job, quiet)
    assert probe(Path(result["output"]), job["options"])["video"]


@pytest.mark.parametrize("kind,target", [(kind, target) for kind in ("video", "audio", "image") for target in FORMATS[kind]])
def test_output_formats(media, job_factory, kind, target):
    job = job_factory([media[kind]], kind, format=target)
    result = execute(job, quiet)
    assert Path(result["output"]).suffix == "." + target
    assert Path(result["output"]).stat().st_size > 0


def test_collision_modes_and_source_guard(media, job_factory):
    job = job_factory([media["image"]], "image")
    first = execute(job, quiet)
    second_job = job_factory([media["image"]], "image")
    second = execute(second_job, quiet)
    assert first["output"] != second["output"]
    skipped_job = job_factory([media["image"]], "image", collision="skip")
    assert execute(skipped_job, quiet)["skipped"]
    overwrite_job = job_factory([media["image"]], "image", collision="overwrite")
    assert execute(overwrite_job, quiet)["output"] == first["output"]
    source_job = job_factory([media["image"]], "image", collision="overwrite", output_dir=str(media["image"].parent))
    before = media["image"].read_bytes()
    with pytest.raises(ValueError, match="原始"):
        execute(source_job, quiet)
    assert media["image"].read_bytes() == before


@pytest.mark.parametrize("kind,operation,options", [("video", "trim", {"start": 2, "end": 1}), ("video", "resize", {"width": 101, "height": 100}), ("image", "crop", {"width": 0, "height": 0}), ("audio", "speed", {"speed": 0}), ("video", "subtitle", {"asset": "not-found.srt"}), ("decrypt", "decrypt", {"format": "original", "decrypt_consent": False})])
def test_invalid_options(kind, operation, options):
    values = {"format": {"video": "mp4", "audio": "flac", "image": "png", "decrypt": "original"}[kind], **options}
    with pytest.raises(ValueError):
        validate_options(kind, operation, values)


def test_failed_input_leaves_no_result(tmp_path, job_factory):
    invalid = tmp_path / "bad.mp4"
    invalid.write_bytes(b"not a media file")
    job = job_factory([invalid], "video")
    with pytest.raises(ValueError):
        execute(job, quiet)
    assert not stage_path(job).exists()
    assert not list(Path(job["options"]["output_dir"]).glob("*.mp4"))


def test_cli_worker_protocol(media, job_factory, tmp_path):
    job = job_factory([media["audio"]], "audio")
    specification = tmp_path / "job.json"
    specification.write_text(json.dumps(job), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(ROOT / "app.py"), "--worker", str(specification)], capture_output=True, timeout=35, **HIDDEN)
    assert completed.returncode == 0, completed.stdout.decode(errors="replace") + completed.stderr.decode(errors="replace")
    events = [json.loads(line[8:]) for line in completed.stdout.decode().splitlines() if line.startswith("@@MEDIA ")]
    assert any(event["event"] == "progress" for event in events)
    assert events[-1]["event"] == "result"


def test_classification_and_platforms():
    assert classify("track.KGM.FLAC") == "decrypt"
    assert platform_for("track.KGM.FLAC") == "kugou"
    assert platform_for("track.mgg") == "qq"
    assert platform_for("track.kwm") == "kuwo"
    assert classify("file.exe") is None
    assert tempo_filters(0.25) == ["atempo=0.5", "atempo=0.5"]


def test_decrypt_real_adapter_rejects_bad_header(tmp_path, job_factory):
    source = tmp_path / "not-valid.kgm"
    source.write_bytes(b"invalid" * 200)
    job = job_factory([source], "decrypt", "decrypt", decrypt_consent=True)
    with pytest.raises(Exception, match="header"):
        execute(job, quiet)
    assert not stage_path(job).exists()


@pytest.mark.parametrize("target", ["original", "flac", "mp3"])
def test_kugou_synthetic_vector_through_real_adapter(media, tmp_path, job_factory, target):
    import lzma
    import struct
    from studio.engine import configure_decrypt

    configure_decrypt(defaults(), tmp_path / "vector-runtime")
    from src.Infrastructure.kugou_decoder import KGM_MAGIC, _build_own_transform_tables, _build_pub_transform_tables

    plaintext = media["audio"].read_bytes()
    public_key = bytes((index * 19 + 7) % 256 for index in range((len(plaintext) + 15) // 16))
    key_path = tmp_path / "synthetic-key.xz"
    key_path.write_bytes(lzma.compress(public_key))
    own_key = bytes(range(16)) + b"\x00"
    own_tables = _build_own_transform_tables(own_key)
    inverse_tables = [bytes(sorted(range(256), key=lambda value, table=table: table[value])) for table in own_tables]
    public_tables = _build_pub_transform_tables()
    encrypted = bytearray(len(plaintext))
    for position, value in enumerate(plaintext):
        mask = public_tables[position % len(public_tables)][public_key[position // 16]]
        encrypted[position] = inverse_tables[position % len(inverse_tables)][value ^ mask]
    header = bytearray(1024)
    header[:16] = KGM_MAGIC
    struct.pack_into("<III", header, 0x10, 1024, 3, 0)
    header[0x1C:0x2C] = own_key[:16]
    source = tmp_path / "合成测试向量.kgm"
    source.write_bytes(header + encrypted)
    job = job_factory([source], "decrypt", "decrypt", format=target, key_file=str(key_path), decrypt_consent=True)
    result = execute(job, quiet)
    output = Path(result["output"])
    if target == "original":
        assert output.read_bytes() == plaintext
    else:
        assert probe(output, job["options"])["audio"]["codec_name"] == target


def test_flac_extension_does_not_prove_decryption_success(tmp_path):
    from studio.engine import validate_decoded_audio
    fake = tmp_path / "fake.flac"
    fake.write_bytes(b"synthetic-invalid-test-input" * 100)
    assert probe(fake, defaults())["audio"]["sample_rate"] == "0"
    with pytest.raises(RuntimeError, match="验证"):
        validate_decoded_audio(fake, defaults(), tmp_path, quiet)
