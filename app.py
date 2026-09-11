from __future__ import annotations

import argparse
import json
import sys
import traceback

from studio import APP_TITLE


def restore_worker_streams():
    if sys.stdout is not None and sys.stderr is not None:
        return
    import ctypes
    import msvcrt
    import os

    get_handle = ctypes.windll.kernel32.GetStdHandle
    get_handle.argtypes = [ctypes.c_uint32]
    get_handle.restype = ctypes.c_void_p
    for name, identifier in (("stdout", -11), ("stderr", -12)):
        if getattr(sys, name) is None:
            handle = get_handle(identifier & 0xFFFFFFFF)
            if handle and handle != ctypes.c_void_p(-1).value:
                descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
                stream = os.fdopen(descriptor, "w", buffering=1, encoding="utf-8", errors="replace")
                setattr(sys, name, stream)
                setattr(sys, "__" + name + "__", stream)


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--worker")
    parser.add_argument("--screenshot")
    parser.add_argument("--diagnostics")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    if args.diagnostics:
        from pathlib import Path
        from studio.engine import diagnostics
        from studio.paths import write_json
        write_json(Path(args.diagnostics), diagnostics())
        return 0
    if args.worker:
        restore_worker_streams()
        from studio.engine import execute, emit
        from pathlib import Path

        try:
            job = json.loads(Path(args.worker).read_text(encoding="utf-8"))
            from studio.tasks_watchdog import watch_owner
            watch_owner(job)
            result = execute(job)
            emit("result", **result)
            return 0
        except Exception as error:
            emit("error", message=str(error), detail=traceback.format_exc())
            return 1
    from studio.ui import run

    return run(args.files, args.screenshot)


if __name__ == "__main__":
    raise SystemExit(main())
