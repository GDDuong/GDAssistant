"""Permission-aware, streaming terminal sessions for Code Mode."""

from __future__ import annotations

import fnmatch
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


PRIVILEGED_PATTERNS = (
    r"\bsudo\b", r"\brunas\b", r"-verb\s+runas", r"\bnet\s+user\b", r"\bnetsh\b",
    r"\bbcdedit\b", r"\bdiskpart\b", r"\bsc\s+create\b", r"\bschtasks\b.*\/create",
    r"\btakeown\b", r"\bicacls\b", r"start-process.*-credential",
)
DESTRUCTIVE_PATTERNS = (
    r"\brm\s+-[a-z]*r", r"\brm\s+-f\b", r"\bdel\s+/[fs]", r"\brd\s+/s", r"\brmdir\s+/s",
    r"remove-item.*-recurse", r"\bgit\s+reset\s+--hard", r"\bgit\s+clean\b", r"\bgit\s+push\b",
    r"\bdrop\s+(table|database)\b", r"\btruncate\s+table\b", r"\bkubectl\s+delete\b",
    r"\bdocker\s+(rm|system\s+prune)\b", r"\bformat\b", r"\bshutdown\b",
)
DEPENDENCY_PATTERNS = (
    r"\bnpm\s+(install|ci|i|add)\b", r"\byarn\s+(install|add)\b", r"\bpnpm\s+(install|add)\b",
    r"\bpip\d*\s+install\b", r"\bpython\s+-m\s+pip\s+install\b", r"\bcomposer\s+(install|require)\b",
    r"\bdotnet\s+add\s+.*package", r"\bcargo\s+add\b", r"\bbundle\s+install\b",
)
SAFE_EXECUTABLES = {
    "python", "python3", "py", "node", "npm", "npx", "pnpm", "yarn", "pytest", "tox",
    "cargo", "rustc", "go", "dotnet", "msbuild", "gradle", "gradlew", "mvn", "mvnw",
    "cmake", "ctest", "ninja", "make", "mingw32-make", "java", "javac", "kotlinc",
    "ruby", "bundle", "php", "composer", "flutter", "dart", "swift", "tsc", "eslint",
    "prettier", "ruff", "black", "mypy", "git", "echo", "dir", "where", "type",
}
SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
SHELL_META = re.compile(r"[|&;<>]|%[A-Za-z_][A-Za-z0-9_]*%|\$\(|`")
SECRET_ENV = re.compile(r"(api[_-]?key|token|secret|password|credential|private[_-]?key)", re.I)
ENV_PREFIXES = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "VIRTUAL_ENV", "CONDA_PREFIX", "LANG", "LC_", "PYTHON", "NODE", "JAVA_HOME", "GRADLE_USER_HOME", "CARGO_HOME", "RUSTUP_HOME")


@dataclass
class ExecutionPolicy:
    mode: str = "project_autonomous"
    allow_dependency_install: bool = True
    approval_callback: Callable[[str, str], bool] | None = None
    approved_patterns: list[str] = field(default_factory=list)

    def is_preapproved(self, permission: str, target: str) -> bool:
        return any(fnmatch.fnmatch(target.casefold(), pattern.casefold()) for pattern in self.approved_patterns)

    def approve(self, title: str, details: str) -> bool:
        if self.approval_callback is None:
            return False
        try:
            return bool(self.approval_callback(title, details))
        except Exception:
            return False

    def authorize_command(self, command: str, structured: bool = False) -> tuple[bool, str]:
        clean = command.strip()
        if any(re.search(pattern, clean, re.I) for pattern in PRIVILEGED_PATTERNS):
            if self.mode == "advanced":
                return False, "Privileged/system commands are never auto-approved."
            return self.approve("Privileged command", clean), "Privileged command requires approval."
        if self.is_preapproved("execute", clean):
            return True, "pre-approved"
        destructive = any(re.search(pattern, clean, re.I) for pattern in DESTRUCTIVE_PATTERNS)
        if destructive and not self.is_preapproved("destructive", clean):
            return self.approve("Destructive command", clean), "Destructive command requires approval."
        if self.mode == "supervised":
            return self.approve("Run command", clean), "Supervised mode requires approval."
        dependency = any(re.search(pattern, clean, re.I) for pattern in DEPENDENCY_PATTERNS)
        if dependency:
            if not self.allow_dependency_install:
                return self.approve("Install dependency", clean), "Dependency installation is disabled."
            if re.search(r"\bpip\d*\s+install\b|\bpython\s+-m\s+pip\s+install\b", clean, re.I) and not os.environ.get("VIRTUAL_ENV"):
                return self.approve("Install Python dependency", clean), "pip install outside a virtual environment requires approval."
        executable = _executable_name(clean)
        if SHELL_META.search(clean) and not structured and not self.is_preapproved("execute", clean):
            return self.approve("Shell command", clean), "Shell syntax requires approval."
        if executable == "git":
            words = _split_command(clean)
            subcommand = words[1].casefold() if len(words) > 1 else ""
            if subcommand not in SAFE_GIT_SUBCOMMANDS:
                return self.approve("Git command", clean), "This Git command requires approval."
        elif executable not in SAFE_EXECUTABLES and self.mode != "advanced":
            return self.approve("Project command", clean), "Unrecognized project command requires approval."
        return True, "Allowed by execution policy."


def _split_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        parts = command.split()
    return [part.strip('"') for part in parts]


def _executable_name(command: str) -> str:
    parts = _split_command(command)
    if not parts:
        return ""
    return Path(parts[0]).name.casefold().removesuffix(".exe")


def _clean_environment() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if SECRET_ENV.search(key):
            continue
        if any(upper.startswith(prefix) for prefix in ENV_PREFIXES):
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    return env


@dataclass
class TerminalSession:
    id: str
    command: str
    cwd: str
    process: subprocess.Popen
    timeout_sec: int
    output: str = ""
    exit_code: int | None = None
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    _readers_done: int = 0
    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class TerminalManager:
    MAX_OUTPUT = 200_000

    def __init__(self) -> None:
        self.sessions: dict[str, TerminalSession] = {}

    def start(
        self,
        command: str,
        cwd: str | os.PathLike[str],
        timeout_sec: int = 120,
        args: list[str] | None = None,
        policy: ExecutionPolicy | None = None,
        on_output: Callable[[str, str], None] | None = None,
        shell: bool | None = None,
    ) -> dict[str, Any]:
        command = str(command).strip()
        if not command and not args:
            return {"status": "FAILURE", "message": "Command cannot be empty."}
        policy = policy or ExecutionPolicy()
        display = command or " ".join(args or [])
        allowed, reason = policy.authorize_command(" ".join([command, *(args or [])]).strip() if command else display, structured=args is not None)
        if not allowed:
            return {"status": "FAILURE", "message": reason, "permission_denied": True}
        root = Path(cwd).expanduser().resolve()
        if not root.is_dir():
            return {"status": "FAILURE", "message": f"Working directory does not exist: {root}"}
        timeout = max(1, min(int(timeout_sec or 120), 3600))
        use_shell = shell if shell is not None else bool(args is None and (SHELL_META.search(display) or _executable_name(display) in {"echo", "dir", "where", "type"}))
        if args is not None:
            argv = [command, *[str(item) for item in args]]
            use_shell = False
        elif use_shell:
            argv = display
        else:
            argv = _split_command(display)
            if not argv:
                return {"status": "FAILURE", "message": "Could not parse command."}
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(root),
                shell=use_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_clean_environment(),
                creationflags=creationflags,
            )
        except OSError as exc:
            return {"status": "FAILURE", "message": f"Could not start command: {exc}"}
        session_id = f"term_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
        session = TerminalSession(session_id, display, str(root), process, timeout)
        self.sessions[session_id] = session
        threading.Thread(target=self._reader, args=(session, process.stdout, "stdout", on_output), daemon=True).start()
        threading.Thread(target=self._reader, args=(session, process.stderr, "stderr", on_output), daemon=True).start()
        threading.Thread(target=self._watch, args=(session,), daemon=True).start()
        return {"status": "SUCCESS", "message": f"Started: {display}", "session_id": session_id, "cwd": str(root)}

    def _reader(self, session: TerminalSession, pipe, stream: str, callback) -> None:
        try:
            for line in iter(pipe.readline, ""):
                text = f"[stderr] {line}" if stream == "stderr" else line
                self.append_output(session.id, text)
                session._queue.put(text)
                if callback:
                    callback(session.id, text)
        finally:
            try:
                pipe.close()
            except Exception:
                pass
            with session._lock:
                session._readers_done += 1
            session._queue.put(None)

    def _watch(self, session: TerminalSession) -> None:
        deadline = session.started_at + session.timeout_sec
        while session.process.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if session.process.poll() is None:
            self.stop(session.id)
            session.status = "timeout"
        else:
            session.status = "completed"
        session.exit_code = session.process.returncode
        session.ended_at = time.time()
        try:
            if session.process.stdin:
                session.process.stdin.close()
        except OSError:
            pass

    def append_output(self, session_id: str, text: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        with session._lock:
            session.output = (session.output + text)[-self.MAX_OUTPUT:]

    def wait(self, session_id: str, timeout_sec: float | None = None) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            return {"status": "FAILURE", "message": f"Unknown terminal session: {session_id}"}
        deadline = time.time() + (timeout_sec if timeout_sec is not None else session.timeout_sec + 2)
        while session.exit_code is None and time.time() < deadline:
            time.sleep(0.05)
        while session._readers_done < 2 and time.time() < deadline:
            time.sleep(0.02)
        while True:
            try:
                session._queue.get_nowait()
            except queue.Empty:
                break
        output = session.output
        code = session.exit_code
        if code is None:
            return {"status": "SUCCESS", "message": "Command is still running.", "session_id": session_id, "output": output, "running": True}
        return {
            "status": "SUCCESS" if code == 0 else "FAILURE",
            "message": f"Exit code: {code}",
            "session_id": session_id,
            "output": output[-self.MAX_OUTPUT:],
            "returncode": code,
            "running": False,
        }

    def run(self, command: str, cwd: str | os.PathLike[str], timeout_sec: int = 120, **kwargs) -> dict[str, Any]:
        chunks: list[str] = []
        external_callback = kwargs.pop("on_output", None)

        def collect(session_id: str, text: str) -> None:
            chunks.append(text)
            if external_callback:
                external_callback(session_id, text)

        started = self.start(command, cwd, timeout_sec, on_output=collect, **kwargs)
        if started["status"] != "SUCCESS":
            return started
        result = self.wait(started["session_id"], timeout_sec + 2)
        result["output"] = "".join(chunks)[-self.MAX_OUTPUT:]
        return result

    def read_output(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            return {"status": "FAILURE", "message": f"Unknown terminal session: {session_id}"}
        while True:
            try:
                session._queue.get_nowait()
            except queue.Empty:
                break
        return {
            "status": "SUCCESS",
            "message": session.status,
            "session_id": session_id,
            "output": session.output,
            "running": session.exit_code is None,
            "returncode": session.exit_code,
        }

    def stop(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            return {"status": "FAILURE", "message": f"Unknown terminal session: {session_id}"}
        if session.process.poll() is not None:
            return {"status": "SUCCESS", "message": "Process already finished."}
        try:
            import psutil

            parent = psutil.Process(session.process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            try:
                parent.terminate()
            except psutil.Error:
                pass
            gone, alive = psutil.wait_procs([*children, parent], timeout=2)
            for proc in alive:
                try:
                    proc.kill()
                except psutil.Error:
                    pass
        except Exception:
            session.process.terminate()
            try:
                session.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                session.process.kill()
        session.status = "stopped"
        return {"status": "SUCCESS", "message": f"Stopped terminal session {session_id}."}

    def stop_all(self) -> None:
        for session_id in list(self.sessions):
            if self.sessions[session_id].exit_code is None:
                self.stop(session_id)

    def close(self) -> None:
        self.stop_all()
        for session in self.sessions.values():
            try:
                if session.process.stdin:
                    session.process.stdin.close()
            except OSError:
                pass
