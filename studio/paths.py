from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
STATE = Path(os.environ.get("MEDIAWORKBENCH_STATE", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MediaWorkbench")))
ENGINES = ROOT / "engines"
VENDOR = ROOT / "vendor" / "qkk"
RESOURCE_PREFIX = "@app/"
BUNDLED_PATHS = {
    "ffmpeg_dir": Path("engines"),
    "key_file": Path("engines/kugou_key.xz"),
    "signature_file": Path("vendor/qkk/src/Infrastructure/platforms/kuwo/runtime_m/out/recovered_signature.json"),
}


def resource_path(value: str | Path) -> Path:
    text = str(value)
    if text.startswith(RESOURCE_PREFIX):
        relative = Path(text[len(RESOURCE_PREFIX):])
        if relative.anchor or ".." in relative.parts:
            raise ValueError("@app/ 路径必须位于软件资源目录内。")
        return ROOT / relative
    path = Path(text).expanduser()
    return path if path.is_absolute() else ROOT / path


def portable_resources(options: dict) -> dict:
    result = dict(options)
    candidates = {}
    for name, relative in BUNDLED_PATHS.items():
        value = options.get(name)
        if not value or str(value).startswith(RESOURCE_PREFIX):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            result[name] = RESOURCE_PREFIX + path.as_posix()
            continue
        try:
            within = path.resolve().relative_to(ROOT.resolve())
            result[name] = RESOURCE_PREFIX + within.as_posix()
            continue
        except ValueError:
            pass
        if tuple(part.casefold() for part in path.parts[-len(relative.parts):]) == tuple(part.casefold() for part in relative.parts):
            origin = path.parents[len(relative.parts) - 1]
            candidates.setdefault(origin, []).append(name)
    for origin, names in candidates.items():
        known_source = (origin / "app.py").is_file() and (origin / "studio/paths.py").is_file()
        known_package = origin.name.casefold() == "_internal" and any((origin.parent / binary).is_file() for binary in ("Flux.exe", "MediaWorkbench.exe"))
        matching_snapshot = len(names) >= 2 and origin.name.casefold() in ("_internal", "mediaworkbench")
        if known_source or known_package or matching_snapshot:
            for name in names:
                result[name] = RESOURCE_PREFIX + BUNDLED_PATHS[name].as_posix()
    return result


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def defaults() -> dict:
    return {
        "output_dir": str(Path.home() / "Downloads" / "MediaWorkbench"),
        "concurrency": 2,
        "collision": "rename",
        "recursive": True,
        "ffmpeg_dir": RESOURCE_PREFIX + BUNDLED_PATHS["ffmpeg_dir"].as_posix(),
        "kgg_db_path": "",
        "key_file": RESOURCE_PREFIX + BUNDLED_PATHS["key_file"].as_posix(),
        "kuwo_exe": "",
        "signature_file": RESOURCE_PREFIX + BUNDLED_PATHS["signature_file"].as_posix(),
        "decrypt_consent": False,
        "motion_enabled": True,
        "motion_halo": True,
        "motion_ripple": True,
        "motion_navigation": True,
        "motion_intensity": 100,
    }


def settings() -> dict:
    result = defaults()
    saved = read_json(STATE / "settings.json", {})
    if isinstance(saved, dict):
        result.update(saved)
    return portable_resources(result)


def engine_path(name: str, options: dict) -> Path:
    options = portable_resources(options)
    candidate = resource_path(options.get("ffmpeg_dir") or ENGINES) / (name + ".exe")
    if not candidate.is_file():
        raise ValueError(f"找不到 {name}.exe，请在设置中指定引擎目录：{candidate.parent}")
    return candidate


def worker_command(job_path: Path) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--worker", str(job_path)]
    return sys.executable, [str(ROOT / "app.py"), "--worker", str(job_path)]
