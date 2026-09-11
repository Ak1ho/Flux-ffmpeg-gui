from __future__ import annotations

import os
import threading
import time

import psutil


def watch_owner(job: dict):
    identifier = job.get("owner_pid")
    if not identifier:
        return
    def monitor():
        while True:
            time.sleep(0.75)
            try:
                owner = psutil.Process(identifier)
                if abs(owner.create_time() - job["owner_started"]) < 0.01 and owner.is_running():
                    continue
            except psutil.Error:
                pass
            try:
                for child in reversed(psutil.Process().children(recursive=True)):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
            finally:
                os._exit(2)
    threading.Thread(target=monitor, daemon=True).start()
