from __future__ import annotations

from pathlib import Path


VIDEO_EXTS = {"mp4", "mkv", "mov", "avi", "webm", "wmv", "flv", "m4v", "ts", "mts", "m2ts", "mpeg", "mpg", "3gp", "ogv", "vob"}
AUDIO_EXTS = {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma", "aiff", "aif", "ape", "ac3", "mka", "amr", "alac", "aifc"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif", "avif", "heic", "heif", "ico", "exr", "dpx", "tga", "ppm", "pgm"}
DECRYPT_EXTS = {"mflac", "mgg", "mmp4", "kwm", "kgm", "kgma", "kgg", "vpr"}
KINDS = {"all": "全部素材", "video": "视频处理", "audio": "音频处理", "image": "图片处理", "decrypt": "音乐解密"}
FORMATS = {
    "video": ["mp4", "mkv", "mov", "webm", "avi", "ts"],
    "audio": ["mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "aiff"],
    "image": ["png", "jpg", "webp", "bmp", "tiff", "avif", "gif"],
    "decrypt": ["original", "mp3", "flac", "wav", "m4a", "ogg", "opus"],
}
OPERATIONS = {
    "video": [("convert", "格式转换"), ("compress", "压缩视频"), ("trim", "截取片段"), ("resize", "调整分辨率"), ("crop", "画面裁剪"), ("rotate", "旋转 / 翻转"), ("speed", "调整速度"), ("mute", "去除音轨"), ("extract", "提取音频"), ("gif", "生成 GIF"), ("snapshot", "提取封面帧"), ("concat", "合并视频"), ("watermark", "添加图片水印"), ("subtitle", "烧录字幕"), ("remux", "无损封装转换")],
    "audio": [("convert", "格式转换"), ("trim", "截取片段"), ("normalize", "响度标准化"), ("volume", "调整音量"), ("speed", "调整速度"), ("fade", "淡入 / 淡出"), ("denoise", "音频降噪"), ("concat", "合并音频")],
    "image": [("convert", "格式转换"), ("compress", "压缩图片"), ("resize", "调整尺寸"), ("crop", "画面裁剪"), ("rotate", "旋转 / 翻转")],
    "decrypt": [("decrypt", "解密 / 解密后转码")],
}
OP_NAMES = {kind: dict(options) for kind, options in OPERATIONS.items()}
OP_HINTS = {
    "convert": "保留源文件，批量转换为目标格式。",
    "compress": "质量值越大，通常体积越小；不会提升源文件质量。",
    "trim": "精确重编码截取。结束时间为 0 时处理至结尾。",
    "resize": "宽或高设为 0 可按原始比例自动计算。",
    "crop": "以左上角为原点，按像素裁剪画面。",
    "rotate": "旋转或翻转画面，不更改源文件。",
    "speed": "音频采用保音调变速；视频同时调整音画速度。",
    "mute": "生成不含音轨的视频。",
    "extract": "从视频中提取首条音轨并转换格式。",
    "gif": "使用调色板优化动图；建议截取短片段。",
    "snapshot": "提取指定时间的一帧，保存为图片。",
    "concat": "按素材列表顺序合并所选文件；视频统一尺寸、帧率和音频格式。",
    "watermark": "将图片叠加到视频右下角，保持原水印像素大小。",
    "subtitle": "将 SRT / ASS 字幕永久烧录到画面中。",
    "remux": "只更换容器，不重编码；源编码必须被目标容器支持。",
    "normalize": "单遍动态响度标准化，不作为两遍母带级精确测量。",
    "volume": "以分贝调整增益；过大的增益可能造成削波。",
    "fade": "为音频增加平滑淡入和淡出。",
    "denoise": "使用频域降噪；较强设置可能损失细节。",
    "decrypt": "复用 QKKDecrypt 引擎。QQ / 酷我需要客户端运行，KGG 需要本机数据库。",
}


def classify(path: str | Path) -> str | None:
    name = Path(path).name.lower()
    extension = Path(path).suffix.lower().lstrip(".")
    if extension in DECRYPT_EXTS or name.endswith((".kgm.flac", ".vpr.flac")):
        return "decrypt"
    if extension in VIDEO_EXTS:
        return "video"
    if extension in AUDIO_EXTS:
        return "audio"
    if extension in IMAGE_EXTS:
        return "image"
    return None


def platform_for(path: str | Path) -> str:
    name = Path(path).name.lower()
    extension = Path(path).suffix.lower().lstrip(".")
    if extension in {"mflac", "mgg", "mmp4"}:
        return "qq"
    if extension == "kwm":
        return "kuwo"
    if extension in {"kgm", "kgma", "kgg", "vpr"} or name.endswith((".kgm.flac", ".vpr.flac")):
        return "kugou"
    raise ValueError("此文件不属于当前解密引擎支持的格式。")


def human_size(value: int | float) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "—"


def human_time(value: float | None) -> str:
    if value is None:
        return "—"
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
