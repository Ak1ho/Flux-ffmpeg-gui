from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from studio.engine import cleanup_stage
from studio.paths import STATE, portable_resources, read_json, worker_command, write_json


STATUS_NAMES = {"pending": "等待中", "running": "处理中", "success": "已完成", "failed": "失败", "cancelled": "已取消", "interrupted": "已中断", "skipped": "已跳过"}


class TaskQueue(QObject):
    changed = Signal()
    notification = Signal(str)

    def __init__(self, preferences: dict, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        loaded = read_json(STATE / "queue.json", [])
        self.jobs = [job for job in loaded if isinstance(job, dict) and all(key in job for key in ("id", "inputs", "options", "status", "kind", "operation"))] if isinstance(loaded, list) else []
        for job in self.jobs:
            job["options"] = portable_resources(job["options"])
            if job["status"] == "running":
                job["status"] = "interrupted"
                job["message"] = "上次运行意外结束；可手动重试。"
        self.active: dict[str, QProcess] = {}
        self.buffers: dict[str, bytes] = {}
        self.enabled = False
        self.pump_timer = QTimer(self)
        self.pump_timer.setInterval(250)
        self.pump_timer.timeout.connect(self.pump)
        self.pump_timer.start()

    def save(self):
        try:
            write_json(STATE / "queue.json", [{**job, "options": portable_resources(job["options"])} for job in self.jobs])
        except OSError as error:
            self.notification.emit(f"保存任务记录失败：{error}")

    def add(self, inputs: list[str], kind: str, operation: str, options: dict):
        job = {"id": uuid.uuid4().hex, "inputs": list(inputs), "kind": kind, "operation": operation, "options": portable_resources(options), "status": "pending", "progress": 0, "message": "", "output": "", "logs": [], "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.jobs.append(job)
        self.save()
        self.changed.emit()
        return job

    def start(self):
        self.enabled = True
        self.pump()
        self.changed.emit()

    def pause(self):
        self.enabled = False
        self.changed.emit()

    def pump(self):
        if not self.enabled:
            return
        limit = max(1, min(4, int(self.preferences.get("concurrency", 2))))
        running_decrypt = any(job["kind"] == "decrypt" and job["id"] in self.active for job in self.jobs)
        for job in self.jobs:
            if len(self.active) >= limit:
                break
            if job["status"] != "pending" or job["kind"] == "decrypt" and running_decrypt:
                continue
            self.launch(job)
            running_decrypt = running_decrypt or job["kind"] == "decrypt"
        if not self.active and not any(job["status"] == "pending" for job in self.jobs):
            self.enabled = False
            self.changed.emit()

    def launch(self, job: dict):
        identifier = job["id"]
        try:
            job_path = STATE / "jobs" / (identifier + ".json")
            job["options"] = portable_resources(job["options"])
            job["owner_pid"] = os.getpid()
            job["owner_started"] = psutil.Process().create_time()
            write_json(job_path, job)
            command, arguments = worker_command(job_path)
        except Exception as error:
            job.update(status="failed", message=str(error))
            self.save()
            self.changed.emit()
            return
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(lambda: self.receive(identifier))
        process.finished.connect(lambda code, status: self.finish(identifier, code))
        process.errorOccurred.connect(lambda error: self.process_error(identifier, error))
        self.active[identifier] = process
        self.buffers[identifier] = b""
        job.update(status="running", progress=-1, message="启动任务", started=time.time())
        self.save()
        process.start(command, arguments)
        self.changed.emit()

    def find(self, identifier: str) -> dict | None:
        return next((job for job in self.jobs if job["id"] == identifier), None)

    def receive(self, identifier: str):
        process = self.active.get(identifier)
        job = self.find(identifier)
        if not process or not job:
            return
        buffer = self.buffers.get(identifier, b"") + bytes(process.readAllStandardOutput())
        lines = buffer.split(b"\n")
        self.buffers[identifier] = lines.pop()
        for raw in lines:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            if not text.startswith("@@MEDIA "):
                self.append_log(job, text)
                continue
            try:
                event = json.loads(text[8:])
            except ValueError:
                self.append_log(job, text)
                continue
            event_name = event.get("event")
            if event_name == "progress":
                job["progress"] = event.get("progress", -1)
                if "phase" in event:
                    job["message"] = event["phase"]
            elif event_name == "result":
                job.update(output=event["output"], size=event["size"], progress=100, result_received=True, result_skipped=event["skipped"])
            elif event_name == "error":
                job["message"] = event["message"]
                self.append_log(job, event.get("detail", event["message"]))
            elif event_name in {"command", "log"}:
                self.append_log(job, event.get("command", event.get("message", "")))
        self.changed.emit()

    def append_log(self, job: dict, text: str):
        job.setdefault("logs", []).append(text)
        job["logs"] = job["logs"][-200:]
        try:
            folder = STATE / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / (job["id"] + ".log")).open("a", encoding="utf-8") as stream:
                stream.write(text + "\n")
        except OSError:
            pass

    def process_error(self, identifier: str, error):
        if error == QProcess.ProcessError.FailedToStart:
            job = self.find(identifier)
            if job:
                job["message"] = "无法启动任务进程；请检查程序文件是否完整。"
            self.finish(identifier, -1)

    def finish(self, identifier: str, code: int):
        if identifier not in self.active:
            return
        self.receive(identifier)
        process = self.active.pop(identifier)
        self.buffers.pop(identifier, None)
        job = self.find(identifier)
        if job:
            if job["status"] != "cancelled":
                if code == 0 and job.get("result_received"):
                    job["status"] = "skipped" if job.get("result_skipped") else "success"
                    job["message"] = "同名文件已存在，跳过" if job.get("result_skipped") else "处理完成"
                else:
                    job["status"] = "failed"
                    if job["message"] in {"启动任务", "检查文件", "处理中", "解密中", "解密后转码"}:
                        job["message"] = f"任务进程退出（{code}），请查看日志。"
            job["elapsed"] = round(time.time() - job.get("started", time.time()), 1)
            try:
                cleanup_stage(job)
            except (OSError, ValueError):
                pass
        process.deleteLater()
        self.save()
        self.changed.emit()

    def cancel(self, identifier: str):
        job = self.find(identifier)
        if not job or job["status"] not in {"running", "pending"}:
            return
        job.update(status="cancelled", message="已取消；原始文件不受影响。")
        process = self.active.get(identifier)
        if process:
            try:
                root = psutil.Process(int(process.processId()))
                children = root.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                process.kill()
                psutil.wait_procs(children, timeout=2)
            except psutil.Error:
                process.kill()
        self.save()
        self.changed.emit()

    def retry(self, identifier: str):
        job = self.find(identifier)
        if not job or job["status"] not in {"failed", "cancelled", "interrupted"} or identifier in self.active:
            return
        try:
            cleanup_stage(job)
        except (ValueError, OSError):
            pass
        job["id"] = uuid.uuid4().hex
        job.update(status="pending", progress=0, message="", result_received=False, result_skipped=False, output="")
        for name in ("key_file", "kgg_db_path", "kuwo_exe", "signature_file", "ffmpeg_dir", "decrypt_consent"):
            job["options"][name] = self.preferences.get(name)
        self.save()
        self.changed.emit()

    def clear_finished(self):
        self.jobs = [job for job in self.jobs if job["status"] in {"pending", "running", "failed", "interrupted"} or job["id"] in self.active]
        self.save()
        self.changed.emit()

    def shutdown(self):
        self.enabled = False
        self.pump_timer.stop()
        for identifier in list(self.active):
            self.cancel(identifier)
        for process in list(self.active.values()):
            process.waitForFinished(5000)
        self.save()
