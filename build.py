from __future__ import annotations

import argparse
import importlib.metadata
import shutil
from pathlib import Path

import PyInstaller.__main__
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo

from studio import APP_ENGLISH_NAME, APP_TITLE, VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    parser.add_argument("--work", required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parent
    build_dir = Path(arguments.work).resolve()
    dist_dir = Path(arguments.dist).resolve()
    destination = (dist_dir / APP_ENGLISH_NAME).resolve()
    if destination == root or root.is_relative_to(destination) or build_dir.is_relative_to(destination):
        raise ValueError("成品目录不能覆盖源码目录或构建工作目录。")
    if destination.exists() and not ((destination / f"{APP_ENGLISH_NAME}.exe").is_file() and (destination / "_internal").is_dir()):
        raise ValueError("目标目录已存在且不是可识别的旧成品；请选择新的成品目录。")
    build_dir.mkdir(parents=True, exist_ok=True)
    version_tuple = tuple(int(part) for part in VERSION.split(".")) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3F, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("080404B0", [StringStruct(key, value) for key, value in (
                ("FileDescription", APP_TITLE), ("ProductName", APP_TITLE), ("FileVersion", VERSION),
                ("ProductVersion", VERSION), ("InternalName", APP_ENGLISH_NAME), ("OriginalFilename", f"{APP_ENGLISH_NAME}.exe"),
            )])]),
            VarFileInfo([VarStruct("Translation", [0x0804, 1200])]),
        ],
    )
    version_path = build_dir / "version-info.txt"
    version_path.write_text(str(version_info), encoding="utf-8")
    for package in ("PySide6-Essentials", "shiboken6", "frida", "psutil", "Pillow"):
        distribution = importlib.metadata.distribution(package)
        destination = root / "licenses" / package
        destination.mkdir(parents=True, exist_ok=True)
        for relative in distribution.files or []:
            if "dist-info" in str(relative) and any(token in str(relative).upper() for token in ("LICENSE", "COPYING", "NOTICE", "METADATA")):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    shutil.copy2(source, destination / source.name)
    args = [str(root / "app.py"), "--name", APP_ENGLISH_NAME, "--version-file", str(version_path), "--windowed", "--onedir", "--noconfirm", "--noupx", "--distpath", str(dist_dir), "--workpath", str(build_dir / "build"), "--specpath", str(build_dir), "--paths", str(root), "--paths", str(root / "vendor" / "qkk"), "--collect-all", "frida", "--hidden-import", "src.Infrastructure.platforms.qq.runtime.frida_decrypt_gateway", "--hidden-import", "src.Infrastructure.platforms.kuwo.runtime_m.kwm_decrypt_mvp", "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick", "--exclude-module", "pytest"]
    for directory in ("engines", "vendor", "assets", "licenses"):
        args += ["--add-data", f"{root / directory};{directory}"]
    args += ["--add-data", f"{root / 'vendor' / 'qkk' / 'src'};src"]
    if (root / "assets" / "app.ico").exists():
        args += ["--icon", str(root / "assets" / "app.ico")]
    PyInstaller.__main__.run(args)
    for name in ("README.md", "使用说明.md"):
        if (root / name).exists():
            shutil.copy2(root / name, dist_dir / APP_ENGLISH_NAME / name)


if __name__ == "__main__":
    main()
