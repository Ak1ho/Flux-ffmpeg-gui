from __future__ import annotations

import contextlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path

from studio.catalog import FORMATS, OPERATIONS, platform_for
from studio.paths import ENGINES, STATE, VENDOR, engine_path, portable_resources, resource_path


HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def emit(event: str, **payload) -> None:
    stream = sys.stdout or sys.__stdout__
    if stream:
        stream.write("@@MEDIA " + json.dumps({"event": event, **payload}, ensure_ascii=True) + "\n")
        stream.flush()


def probe(path: Path, options: dict) -> dict:
    command = [str(engine_path("ffprobe", options)), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=35, **HIDDEN)
    except subprocess.TimeoutExpired as error:
        raise ValueError("读取媒体信息超时，文件可能损坏或位于慢速网络磁盘。") from error
    if result.returncode:
        raise ValueError("无法读取媒体文件：" + result.stderr.decode("utf-8", errors="replace")[-1600:])
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = payload.get("format", {}).get("duration") or next((stream.get("duration") for stream in streams if stream.get("duration")), 0)
    return {"duration": float(duration or 0), "video": video, "audio": audio, "raw": payload}


def number(options: dict, name: str, default: float = 0) -> float:
    value = float(options.get(name, default))
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须为有限数值。")
    return value


def output_kind(kind: str, operation: str) -> str:
    if operation == "extract" or kind == "decrypt":
        return "audio"
    if operation in {"snapshot", "gif"}:
        return "image"
    return kind


def validate_options(kind: str, operation: str, options: dict) -> None:
    if operation not in dict(OPERATIONS.get(kind, [])):
        raise ValueError("媒体类型与处理操作不匹配。")
    target = options.get("format", "mp4")
    allowed = FORMATS["decrypt" if kind == "decrypt" else output_kind(kind, operation)]
    if target not in allowed:
        raise ValueError("此操作不支持选择的输出格式。")
    start, end = number(options, "start"), number(options, "end")
    if start < 0 or end < 0 or end and end <= start:
        raise ValueError("结束时间必须大于开始时间；0 表示直到结尾。")
    if not 0.25 <= number(options, "speed", 1) <= 4:
        raise ValueError("速度范围为 0.25–4 倍。")
    if operation in {"resize", "crop"}:
        width, height = int(number(options, "width")), int(number(options, "height"))
        if min(width, height) < 0 or max(width, height) > 16384:
            raise ValueError("尺寸必须介于 0–16384 像素。")
        if (operation == "crop" and min(width, height) == 0) or max(width, height) == 0:
            raise ValueError("裁剪需要正数宽高；缩放至少需要一个非零尺寸。")
        if kind == "video" and any(value % 2 for value in (width, height)):
            raise ValueError("视频宽高请使用偶数，以兼容编码器。")
    if operation in {"watermark", "subtitle"}:
        asset = Path(options.get("asset", ""))
        if not asset.is_file():
            raise ValueError("请选择有效的水印图片或字幕文件。")
        allowed_asset = {".srt", ".ass", ".ssa"} if operation == "subtitle" else {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        if asset.suffix.lower() not in allowed_asset:
            raise ValueError("附件格式不受此操作支持。")
    if kind == "decrypt" and not options.get("decrypt_consent"):
        raise ValueError("请先确认你对待处理音频拥有合法使用权限。")
    if operation == "gif" and target != "gif":
        raise ValueError("生成 GIF 操作必须选择 GIF 格式。")


def audio_codec(target: str, options: dict) -> list[str]:
    bitrate = int(number(options, "bitrate", 192))
    mapping = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"],
        "flac": ["-c:a", "flac", "-compression_level", "8"],
        "wav": ["-c:a", "pcm_s16le"],
        "aiff": ["-c:a", "pcm_s16be"],
        "m4a": ["-c:a", "aac", "-b:a", f"{bitrate}k"],
        "aac": ["-c:a", "aac", "-b:a", f"{bitrate}k"],
        "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
        "opus": ["-c:a", "libopus", "-b:a", f"{min(bitrate, 256)}k"],
    }
    result = list(mapping[target])
    rate = int(number(options, "sample_rate"))
    channels = int(number(options, "channels"))
    if rate:
        if target == "opus" and rate not in {8000, 12000, 16000, 24000, 48000}:
            raise ValueError("Opus 不支持此采样率，请选择自动或 48000 Hz。")
        result += ["-ar", str(rate)]
    if channels:
        result += ["-ac", str(channels)]
    return result


def video_codec(target: str, options: dict) -> list[str]:
    quality = int(number(options, "quality", 23))
    encoder = options.get("encoder", "auto")
    if target == "webm":
        if encoder not in {"auto", "libvpx-vp9"}:
            raise ValueError("WebM 请使用自动编码器。")
        return ["-c:v", "libvpx-vp9", "-crf", str(quality), "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"]
    if encoder == "auto":
        encoder = "mpeg4" if target == "avi" else "libx264"
    if encoder not in {"libx264", "libx265", "h264_nvenc", "h264_qsv", "h264_amf", "mpeg4"}:
        raise ValueError("不支持的编码器。")
    result = ["-c:v", encoder]
    if encoder in {"libx264", "libx265"}:
        result += ["-crf", str(quality), "-preset", "medium"]
    elif encoder == "h264_nvenc":
        result += ["-cq", str(quality), "-b:v", "0"]
    elif encoder == "h264_qsv":
        result += ["-global_quality", str(quality)]
    elif encoder == "h264_amf":
        result += ["-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality)]
    else:
        result += ["-q:v", str(max(2, min(12, quality // 4))) ]
    result += ["-pix_fmt", "yuv420p", "-c:a", "libmp3lame" if target == "avi" else "aac", "-b:a", f"{int(number(options, 'bitrate', 192))}k"]
    if target in {"mp4", "mov"}:
        result += ["-movflags", "+faststart"]
        if encoder == "libx265":
            result += ["-tag:v", "hvc1"]
    return result


def image_codec(target: str, options: dict) -> list[str]:
    quality = int(number(options, "image_quality", 85))
    result = ["-frames:v", "1"]
    if target == "jpg":
        result += ["-c:v", "mjpeg", "-q:v", str(max(2, round((100 - quality) * 0.29 + 2))), "-pix_fmt", "yuvj420p"]
    elif target == "webp":
        result += ["-c:v", "libwebp", "-quality", str(quality)]
    elif target == "avif":
        result += ["-c:v", "libaom-av1", "-still-picture", "1", "-crf", str(round((100 - quality) * 0.55)), "-cpu-used", "6"]
    elif target in {"png", "bmp", "tiff"}:
        result += ["-c:v", target]
    return result


def tempo_filters(speed: float) -> list[str]:
    result = []
    while speed < 0.5:
        result.append("atempo=0.5")
        speed /= 0.5
    while speed > 2:
        result.append("atempo=2")
        speed /= 2
    result.append(f"atempo={speed:g}")
    return result


def build_command(inputs: list[Path], kind: str, operation: str, options: dict, destination: Path, infos: list[dict], stage: Path) -> tuple[list[str], float]:
    validate_options(kind, operation, options)
    target = options["format"]
    start, end = number(options, "start"), number(options, "end")
    duration = infos[0]["duration"]
    if operation in {"trim", "gif", "snapshot"} and duration > 0 and start >= duration:
        raise ValueError("开始时间超出源文件时长。")
    expected = max(0, (min(end, duration) if end else duration) - start) if operation in {"trim", "gif"} else duration
    command = [str(engine_path("ffmpeg", options)), "-hide_banner", "-nostdin", "-y", "-loglevel", "warning", "-progress", "pipe:1", "-nostats"]
    if operation in {"trim", "gif", "snapshot"} and start:
        command += ["-ss", str(start)]
    for source in inputs:
        command += ["-i", str(source)]
    if operation == "watermark":
        command += ["-i", str(Path(options["asset"]).resolve())]
    if operation in {"trim", "gif"} and end:
        command += ["-t", str(end - start)]
    if operation == "remux":
        return command + ["-map", "0:v?", "-map", "0:a?", "-map_metadata", "0", "-c", "copy", str(destination)], expected
    has_video, has_audio = infos[0]["video"] is not None, infos[0]["audio"] is not None
    if kind == "video" and not has_video:
        raise ValueError("源文件不包含可处理的视频流。")
    if (kind == "audio" or operation == "extract") and not has_audio:
        raise ValueError("源文件不包含音轨。")
    video_filters, audio_filters = [], []
    if operation == "resize":
        width, height = int(number(options, "width")), int(number(options, "height"))
        automatic = -2 if kind == "video" else -1
        video_filters += [f"scale={width or automatic}:{height or automatic}:flags=lanczos", "setsar=1"]
    if operation == "crop":
        width, height = int(number(options, "width")), int(number(options, "height"))
        left, top = int(number(options, "crop_x")), int(number(options, "crop_y"))
        video = infos[0]["video"] or {}
        if left < 0 or top < 0 or left + width > video.get("width", 0) or top + height > video.get("height", 0):
            raise ValueError("裁剪区域超出原始画面边界。")
        video_filters += [f"crop={width}:{height}:{left}:{top}"]
    if operation == "rotate":
        rotation = options.get("rotation", "90")
        mappings = {"90": ["transpose=1"], "180": ["hflip", "vflip"], "270": ["transpose=2"], "hflip": ["hflip"], "vflip": ["vflip"]}
        if rotation not in mappings:
            raise ValueError("无效的旋转方向。")
        video_filters += mappings[rotation]
    if operation == "speed":
        speed = number(options, "speed", 1)
        video_filters += [f"setpts=(PTS-STARTPTS)/{speed:g}"] if kind == "video" else []
        audio_filters += tempo_filters(speed)
        expected = duration / speed
    if operation == "normalize":
        rate = int(number(options, "sample_rate")) or int((infos[0]["audio"] or {}).get("sample_rate", 48000))
        audio_filters += [f"loudnorm=I={number(options, 'loudness', -16)}:TP=-1.5:LRA=11", f"aresample={rate}", "asetnsamples=n=4096:p=0"]
    if operation == "volume":
        audio_filters += [f"volume={number(options, 'gain')}dB"]
    if operation == "fade":
        fade_in, fade_out = number(options, "fade_in", 1), number(options, "fade_out", 1)
        if fade_in < 0 or fade_out < 0 or fade_in + fade_out > duration:
            raise ValueError("淡入与淡出时长之和不能超过音频时长。")
        audio_filters += [f"afade=t=in:d={fade_in}", f"afade=t=out:st={max(0, duration - fade_out)}:d={fade_out}"]
    if operation == "denoise":
        audio_filters += [f"afftdn=nf={number(options, 'noise_floor', -25)}"]
    complex_filter = None
    if operation == "concat":
        if len(inputs) < 2:
            raise ValueError("合并操作至少需要两个同类文件。")
        expected = sum(info["duration"] for info in infos)
        chains, labels = [], []
        if kind == "audio":
            for index, info in enumerate(infos):
                if not info["audio"]:
                    raise ValueError("合并列表中存在不含音轨的文件。")
                chains.append(f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}]")
                labels.append(f"[a{index}]")
            chains.append("".join(labels) + f"concat=n={len(inputs)}:v=0:a=1[outa]")
            command += ["-filter_complex", ";".join(chains), "-map", "[outa]"]
        else:
            width = int(infos[0]["video"]["width"]) // 2 * 2
            height = int(infos[0]["video"]["height"]) // 2 * 2
            fps = int(number(options, "fps", 30)) or 30
            for index, info in enumerate(infos):
                if not info["video"] or info["duration"] <= 0:
                    raise ValueError("合并视频需要每个文件都有视频流和有效时长。")
                chains.append(f"[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS[v{index}]")
                if info["audio"]:
                    chains.append(f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={info['duration']},asetpts=PTS-STARTPTS[a{index}]")
                else:
                    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={info['duration']},asetpts=PTS-STARTPTS[a{index}]")
                labels.append(f"[v{index}][a{index}]")
            chains.append("".join(labels) + f"concat=n={len(inputs)}:v=1:a=1[outv][outa]")
            command += ["-filter_complex", ";".join(chains), "-map", "[outv]", "-map", "[outa]"]
    else:
        if operation == "subtitle":
            asset = Path(options["asset"])
            local_name = "subtitle" + asset.suffix.lower()
            shutil.copy2(asset, stage / local_name)
            video_filters += [f"subtitles=filename={local_name}"]
        if operation == "watermark":
            complex_filter = "[0:v:0][1:v:0]overlay=W-w-20:H-h-20:eof_action=repeat[outv]"
        if operation == "gif":
            width = int(number(options, "width", 640)) or 640
            fps = int(number(options, "fps", 12)) or 12
            complex_filter = f"[0:v:0]fps={fps},scale={width}:-1:flags=lanczos,split[base][pal];[pal]palettegen=stats_mode=diff[palette];[base][palette]paletteuse=dither=sierra2_4a[outv]"
        destination_kind = output_kind(kind, operation)
        if complex_filter:
            command += ["-filter_complex", complex_filter, "-map", "[outv]"]
        elif destination_kind != "audio":
            command += ["-map", "0:v:0"]
        if destination_kind == "audio":
            command += ["-map", "0:a:0", "-vn"]
        elif destination_kind == "video" and operation != "mute":
            command += ["-map", "0:a:0?"]
        else:
            command += ["-an"]
        if destination_kind == "video" and not complex_filter:
            video_filters += ["pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        if video_filters:
            command += ["-vf", ",".join(video_filters)]
        if audio_filters and has_audio:
            command += ["-af", ",".join(audio_filters)]
    destination_kind = output_kind(kind, operation)
    if destination_kind == "audio":
        command += audio_codec(target, options)
    elif destination_kind == "video":
        command += video_codec(target, options)
        fps = int(number(options, "fps"))
        if fps and operation != "concat":
            command += ["-r", str(fps)]
    elif operation == "gif":
        command += ["-loop", "0"]
    else:
        command += image_codec(target, options)
    command += ["-map_metadata", "-1" if options.get("strip_metadata") else "0", "-threads", "2", str(destination)]
    return command, expected


def run_ffmpeg(command: list[str], duration: float, cwd: Path, callback=emit) -> None:
    callback("command", command=subprocess.list2cmdline(command))
    errors = deque(maxlen=70)
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **HIDDEN)
    try:
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("out_time_us="):
                try:
                    seconds = float(line.split("=", 1)[1]) / 1_000_000
                    callback("progress", progress=min(99, max(0, seconds / duration * 100)) if duration > 0 else -1)
                except ValueError:
                    pass
            elif line and not re.match(r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time|dup_frames|drop_frames|speed|progress)=", line):
                errors.append(line)
                callback("log", message=line)
        code = process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
    if code:
        raise RuntimeError("FFmpeg 处理失败。若使用硬件编码，请检查驱动或改为自动编码。\n" + "\n".join(errors)[-5000:])


def configure_decrypt(options: dict, stage: Path):
    vendor_text = str(VENDOR)
    if vendor_text not in sys.path:
        sys.path.insert(0, vendor_text)
    from src.Infrastructure.runtime_paths import RuntimePaths

    runtime = RuntimePaths(root_dir=stage, bundle_dir=VENDOR, assets_dir=ENGINES, plugins_dir=stage / "plugins", log_dir=stage / "log", output_dir=stage / "decoded", docs_dir=stage / "docs", plugins_config=stage / "plugins/config.json", output_manifest=stage / "plugins/manifest.json")
    RuntimePaths.discover = classmethod(lambda cls: runtime)
    runtime.ensure_runtime_dirs()
    from src.Infrastructure import transcoder

    transcoder.resolve_ffmpeg_path = lambda paths=None: engine_path("ffmpeg", options)
    return runtime


def diagnostics() -> dict:
    from studio.paths import defaults
    options = defaults()
    report = {"engines": {}, "decrypt": {}}
    for name in ("ffmpeg", "ffprobe", "ffplay"):
        try:
            binary = engine_path(name, options)
            result = subprocess.run([str(binary), "-version"], capture_output=True, timeout=10, **HIDDEN)
            report["engines"][name] = {"ok": result.returncode == 0, "path": str(binary), "version": result.stdout.decode("utf-8", errors="replace").splitlines()[0]}
        except Exception as error:
            report["engines"][name] = {"ok": False, "error": str(error)}
    try:
        configure_decrypt(options, STATE / "diagnostics")
        import frida
        from src.Infrastructure.native_backend import get_native_backend
        from src.Infrastructure.platforms.qq.runtime.frida_decrypt_gateway import FridaDecryptGateway
        from src.Infrastructure.platforms.kuwo.runtime_m import kwm_decrypt_mvp
        report["decrypt"] = {"frida_version": frida.__version__, "qq_import_ok": FridaDecryptGateway is not None, "kuwo_agent_exists": kwm_decrypt_mvp.AGENT_PATH.is_file(), "kuwo_agent_path": str(kwm_decrypt_mvp.AGENT_PATH), "kugou_native_available": get_native_backend().available, "kugou_key_exists": resource_path(options["key_file"]).is_file(), "kuwo_signature_exists": resource_path(options["signature_file"]).is_file()}
    except Exception as error:
        report["decrypt"] = {"error": str(error)}
    return report


def validate_decoded_audio(output: Path, options: dict, stage: Path, callback=emit) -> dict:
    information = probe(output, options)
    audio = information.get("audio")
    if not audio or int(audio.get("sample_rate", 0)) <= 0 or int(audio.get("channels", 0)) <= 0:
        raise RuntimeError("解密结果未通过音频验证：缺少有效音频参数；不会发布未识别的文件。")
    callback("progress", progress=0, phase="校验解密结果")
    command = [str(engine_path("ffmpeg", options)), "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-progress", "pipe:1", "-nostats", "-i", str(output), "-map", "0:a:0", "-vn", "-sn", "-dn", "-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
    run_ffmpeg(command, information["duration"], stage, callback)
    return information


def decrypt_file(source: Path, options: dict, stage: Path, callback=emit) -> Path:
    options = portable_resources(options)
    options = {**options, **{name: str(resource_path(options[name])) for name in ("key_file", "signature_file") if options.get(name)}}
    if not options.get("decrypt_consent"):
        raise ValueError("未确认音频使用权限。")
    runtime = configure_decrypt(options, stage)
    from src.Infrastructure.platforms.qq.adapter import QQPlatformAdapter
    from src.Infrastructure.platforms.kuwo.adapter import KuwoPlatformAdapter
    from src.Infrastructure.platforms.kugou.adapter import KugouPlatformAdapter

    platform = platform_for(source)
    adapter = {"qq": QQPlatformAdapter, "kuwo": KuwoPlatformAdapter, "kugou": KugouPlatformAdapter}[platform]()
    adapter_options = {"key_file": options.get("key_file", ""), "kgg_db_path": options.get("kgg_db_path", ""), "exe_path": options.get("kuwo_exe", ""), "signature_file": options.get("signature_file", ""), "process_match": "qqmusic", "process_name": "kwmusic.exe", "timeout_sec": 30}
    ready, reason = adapter.validate_runtime(adapter_options)
    if not ready:
        raise ValueError(f"{adapter.display_name}尚未就绪：{reason}。请检查设置后重试。")
    if platform == "qq":
        from src.Infrastructure.platforms.qq.runtime import qqmusic_decrypt
        temporary = STATE / "qq-temp" / stage.name
        if not str(temporary).isascii():
            raise ValueError("QQ 解密需要英文临时路径，请使用 MEDIAWORKBENCH_STATE 指定英文数据目录。")
        temporary.mkdir(parents=True, exist_ok=True)
        qqmusic_decrypt.pick_safe_tmp_dir = lambda output_dir: str(temporary)
    callback("progress", progress=-1, phase="解密中")
    with contextlib.redirect_stdout(sys.stderr):
        result = adapter.decrypt_one(source, runtime.output_dir, adapter_options, log_dir=runtime.log_dir)
    output = Path(result.get("output_path", ""))
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("解密引擎未生成有效输出。")
    validate_decoded_audio(output, options, stage, callback)
    return output


def stage_path(job: dict) -> Path:
    job_id = job["id"]
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("任务编号无效。")
    return Path(job["options"]["output_dir"]).resolve() / (".media-" + job_id)


def cleanup_stage(job: dict) -> None:
    candidate = stage_path(job)
    parent = Path(job["options"]["output_dir"]).resolve()
    if candidate.is_symlink() or candidate.resolve().parent != parent or candidate.name != ".media-" + job["id"]:
        return
    if candidate.is_dir():
        shutil.rmtree(candidate, ignore_errors=True)
    temporary = STATE / "qq-temp" / candidate.name
    temporary_parent = (STATE / "qq-temp").resolve()
    if not temporary.is_symlink() and temporary.resolve().parent == temporary_parent and temporary.name == ".media-" + job["id"] and temporary.is_dir():
        shutil.rmtree(temporary, ignore_errors=True)


def publish(staged: Path, destination: Path, sources: list[Path], policy: str) -> tuple[Path, bool]:
    source_set = {path.resolve() for path in sources}
    if destination.resolve() in source_set and policy == "overwrite":
        raise ValueError("拒绝覆盖原始输入文件，请更换输出目录或使用自动重命名。")
    if policy == "skip" and destination.exists():
        return destination, True
    if policy == "overwrite":
        os.replace(staged, destination)
        return destination, False
    candidate = destination
    index = 1
    while True:
        if candidate.resolve() not in source_set:
            try:
                if os.name != "nt" and candidate.exists():
                    raise FileExistsError(str(candidate))
                os.rename(staged, candidate)
                return candidate, False
            except FileExistsError:
                if policy == "skip":
                    return candidate, True
        candidate = destination.with_name(f"{destination.stem} ({index}){destination.suffix}")
        index += 1


def execute(job: dict, callback=emit) -> dict:
    options = job["options"]
    kind, operation = job["kind"], job["operation"]
    validate_options(kind, operation, options)
    sources = [Path(source).resolve() for source in job["inputs"]]
    if not sources or any(not source.is_file() for source in sources):
        raise ValueError("输入文件不存在，可能已被移动或删除。")
    output_dir = Path(options["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = stage_path(job)
    stage.mkdir(exist_ok=False)
    try:
        callback("progress", progress=-1, phase="检查文件")
        if kind == "decrypt":
            decrypted = decrypt_file(sources[0], options, stage, callback)
            if options["format"] == "original":
                staged_output = decrypted
                extension = decrypted.suffix.lstrip(".")
            else:
                extension = options["format"]
                staged_output = stage / ("result." + extension)
                information = probe(decrypted, options)
                command, duration = build_command([decrypted], "audio", "convert", options, staged_output, [information], stage)
                callback("progress", progress=0, phase="解密后转码")
                run_ffmpeg(command, duration, stage, callback)
        else:
            extension = options["format"]
            staged_output = stage / ("result." + extension)
            infos = [probe(source, options) for source in sources]
            command, duration = build_command(sources, kind, operation, options, staged_output, infos, stage)
            callback("progress", progress=0, phase="处理中")
            run_ffmpeg(command, duration, stage, callback)
        if not staged_output.is_file() or staged_output.stat().st_size == 0:
            raise RuntimeError("任务没有生成有效文件。")
        probe(staged_output, options)
        base = sources[0].stem
        if base.lower().endswith((".kgm", ".vpr")):
            base = Path(base).stem
        suffix = "_merged" if operation == "concat" else ""
        destination = output_dir / f"{base}{suffix}.{extension}"
        result, skipped = publish(staged_output, destination, sources, options.get("collision", "rename"))
        return {"output": str(result), "size": result.stat().st_size, "skipped": skipped, "progress": 100}
    finally:
        cleanup_stage(job)
