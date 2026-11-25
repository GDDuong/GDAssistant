"""Workspace-bound file operations with snapshots, diffs, and undo."""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_IGNORED = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "dist", "build",
    "target", "out", "bin", "obj", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".idea", ".vscode", ".gradle", ".next", "coverage", ".gd-assistant",
}
SENSITIVE_NAMES = {
    "api.json", "credentials.json", "secrets.json", "service-account.json", "id_rsa",
    "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}
MAX_TEXT_BYTES = 2 * 1024 * 1024


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hash_bytes(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".gd-write-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


@dataclass
class ChangeRecord:
    id: str
    task_id: str
    path: str
    operation: str
    before_hash: str | None
    after_hash: str | None
    before_text: str
    after_text: str
    created_at: str
    status: str = "pending"
    snapshot: str | None = None
    group_id: str | None = None

    @property
    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before_text.splitlines(keepends=True),
                self.after_text.splitlines(keepends=True),
                fromfile=f"a/{self.path}",
                tofile=f"b/{self.path}",
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChangeRecord":
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})


class ChangeTracker:
    """Stores recoverable pre-change bytes outside the selected project."""

    def __init__(self, root: Path, task_id: str = "default") -> None:
        self.root = root.resolve()
        self.task_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)[:80] or "default"
        project_key = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        base = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant" / "code-backups"
        self.task_dir = base / project_key / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.changes: list[ChangeRecord] = []
        self._load()

    def _load(self) -> None:
        for path in sorted(self.task_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.changes.append(ChangeRecord.from_dict(data))
            except (OSError, ValueError, TypeError):
                continue

    def record(
        self,
        relative_path: str,
        before: bytes | None,
        after: bytes | None,
        operation: str,
        group_id: str | None = None,
    ) -> ChangeRecord:
        change_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_{os.urandom(2).hex()}"
        snapshot = None
        if before is not None:
            snapshot_path = self.task_dir / change_id / "before" / relative_path
            _atomic_write(snapshot_path, before)
            snapshot = str(snapshot_path)
        change = ChangeRecord(
            id=change_id,
            task_id=self.task_id,
            path=relative_path,
            operation=operation,
            before_hash=_hash_bytes(before),
            after_hash=_hash_bytes(after),
            before_text=self._text(before),
            after_text=self._text(after),
            created_at=_now(),
            snapshot=snapshot,
            group_id=group_id,
        )
        self.changes.append(change)
        self._save(change)
        return change

    @staticmethod
    def _text(data: bytes | None) -> str:
        if data is None:
            return ""
        if b"\x00" in data[:8192]:
            return f"[binary file: {len(data)} bytes]"
        return data.decode("utf-8", errors="replace")

    def _save(self, change: ChangeRecord) -> None:
        (self.task_dir / f"{change.id}.json").write_text(
            json.dumps(change.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, change_id: str) -> ChangeRecord | None:
        return next((change for change in self.changes if change.id == change_id), None)

    def current_bytes(self, relative_path: str) -> bytes | None:
        path = self.root / relative_path
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def undo(self, change_id: str) -> dict[str, Any]:
        change = self.get(change_id)
        if change is None:
            return {"status": "FAILURE", "message": f"Unknown change: {change_id}"}
        group = [item for item in self.changes if change.group_id and item.group_id == change.group_id] if change.group_id else [change]
        if any(item.status in {"rejected", "undone"} for item in group):
            return {"status": "FAILURE", "message": "That change was already undone."}
        for item in group:
            if _hash_bytes(self.current_bytes(item.path)) != item.after_hash:
                return {
                    "status": "FAILURE",
                    "message": "A file changed outside GD Assistant; undo was refused to avoid losing newer work.",
                }
        try:
            for item in reversed(group):
                if item.snapshot:
                    _atomic_write(self.root / item.path, Path(item.snapshot).read_bytes())
                else:
                    (self.root / item.path).unlink(missing_ok=True)
                item.status = "undone"
                self._save(item)
        except OSError as exc:
            return {"status": "FAILURE", "message": f"Undo failed: {exc}"}
        return {"status": "SUCCESS", "message": f"Undid {change.operation} on {change.path}.", "change_id": change.id}

    def accept(self, change_id: str) -> dict[str, Any]:
        change = self.get(change_id)
        if change is None:
            return {"status": "FAILURE", "message": f"Unknown change: {change_id}"}
        change.status = "accepted"
        self._save(change)
        return {"status": "SUCCESS", "message": f"Accepted change to {change.path}."}

    def pending(self) -> list[ChangeRecord]:
        return [change for change in self.changes if change.status == "pending"]


class Workspace:
    def __init__(
        self,
        root: str | os.PathLike[str],
        ignored_paths: list[str] | None = None,
        task_id: str = "default",
        reference_dirs: list[str] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.root}")
        self.reference_dirs = [Path(path).expanduser().resolve() for path in reference_dirs or [] if Path(path).expanduser().is_dir()]
        self.ignored = set(DEFAULT_IGNORED)
        self.ignored.update(str(item).strip().replace("\\", "/").strip("/") for item in ignored_paths or [] if str(item).strip())
        self.tracker = ChangeTracker(self.root, task_id)

    def relative(self, path: str | os.PathLike[str]) -> str:
        return str(Path(path).resolve().relative_to(self.root)).replace("\\", "/")

    def display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def safe_path(self, value: str | os.PathLike[str], allow_sensitive: bool = False, allow_reference: bool = False) -> Path:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Path cannot be empty.")
        candidate = Path(raw).expanduser()
        if not allow_sensitive and self.is_sensitive(candidate):
            raise ValueError("Sensitive files are blocked from model tools.")
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            if not allow_reference or not any(target == ref or ref in target.parents for ref in self.reference_dirs):
                raise ValueError("Path is outside the selected workspace and read-only reference directories.") from exc
        if target != self.root and not allow_sensitive and self.is_sensitive(target):
            raise ValueError("Sensitive files are blocked from model tools.")
        return target

    def is_sensitive(self, path: Path) -> bool:
        name = path.name.lower()
        return (
            name in SENSITIVE_NAMES
            or name.startswith(".env")
            or path.suffix.lower() in SENSITIVE_SUFFIXES
            or name.endswith((".tfvars", ".kdbx"))
        )

    def is_ignored(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            rel = Path(path.name)
        parts = rel.parts[:-1] if path.is_file() else rel.parts
        for part in parts:
            if part in self.ignored:
                return True
        rel_text = rel.as_posix()
        return any(fnmatch.fnmatch(rel_text, pattern) for pattern in self.ignored if "/" in pattern or "*" in pattern)

    def read_bytes(self, value: str, allow_sensitive: bool = False) -> bytes:
        path = self.safe_path(value, allow_sensitive=allow_sensitive, allow_reference=True)
        if not path.is_file():
            raise ValueError(f"File not found: {value}")
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("File is larger than the 2 MB model-read limit.")
        return path.read_bytes()

    def read_text(self, value: str, allow_sensitive: bool = False) -> str:
        data = self.read_bytes(value, allow_sensitive=allow_sensitive)
        if b"\x00" in data[:8192]:
            raise ValueError("Binary files cannot be sent as text.")
        return data.decode("utf-8", errors="replace")

    def list_directory(self, relative_path: str = ".", max_entries: int = 200) -> dict[str, Any]:
        try:
            target = self.safe_path(relative_path, allow_reference=True)
            if not target.is_dir():
                raise ValueError("Path is not a directory.")
            entries = []
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if self.is_ignored(item) or self.is_sensitive(item):
                    continue
                entries.append(
                    {
                        "path": self.display_path(item),
                        "type": "directory" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                )
                if len(entries) >= max(1, min(max_entries, 1000)):
                    break
            return {"status": "SUCCESS", "message": f"Listed {len(entries)} entries.", "entries": entries}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def list_files(self, relative_path: str = ".", pattern: str = "*", max_entries: int = 500) -> dict[str, Any]:
        try:
            target = self.safe_path(relative_path, allow_reference=True)
            if not target.is_dir():
                raise ValueError("Path is not a directory.")
            files: list[str] = []
            for root, dirs, names in os.walk(target):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if not self.is_ignored(root_path / d)]
                for name in names:
                    path = root_path / name
                    if self.is_ignored(path) or self.is_sensitive(path) or not fnmatch.fnmatch(name, pattern):
                        continue
                    files.append(self.display_path(path))
                    if len(files) >= max(1, min(max_entries, 5000)):
                        break
                if len(files) >= max(1, min(max_entries, 5000)):
                    break
            return {"status": "SUCCESS", "message": f"Found {len(files)} files.", "files": files}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def read_file(self, file_path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        try:
            text = self.read_text(file_path)
            lines = text.splitlines()
            start = max(1, int(start_line))
            end = min(len(lines), int(end_line)) if end_line is not None else len(lines)
            if start > len(lines) and lines:
                raise ValueError(f"Start line {start} exceeds {len(lines)} lines.")
            if not lines:
                return {"status": "SUCCESS", "message": f"File: {file_path} (empty)", "content": "", "total_lines": 0}
            numbered = [f"{index:5d} | {lines[index - 1]}" for index in range(start, max(start, end) + 1)]
            return {
                "status": "SUCCESS",
                "message": f"File: {file_path} (lines {start}-{max(start, end)} of {len(lines)})",
                "content": "\n".join(numbered),
                "total_lines": len(lines),
            }
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def read_multiple_files(self, file_paths: list[str], max_lines_each: int = 300) -> dict[str, Any]:
        results = []
        for file_path in file_paths[:30]:
            result = self.read_file(file_path, 1, max_lines_each)
            results.append({"path": file_path, **result})
        return {"status": "SUCCESS" if all(r["status"] == "SUCCESS" for r in results) else "FAILURE", "files": results}

    def search_files(self, query: str, relative_path: str = ".", max_results: int = 100) -> dict[str, Any]:
        try:
            target = self.safe_path(relative_path, allow_reference=True)
            matches = []
            regex = re.compile(query, re.IGNORECASE)
            for root, dirs, names in os.walk(target):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if not self.is_ignored(root_path / d)]
                for name in names:
                    path = root_path / name
                    if self.is_ignored(path) or self.is_sensitive(path):
                        continue
                    rel = self.relative(path)
                    if regex.search(rel):
                        matches.append(self.display_path(path))
                        if len(matches) >= max(1, min(max_results, 500)):
                            return {"status": "SUCCESS", "message": "\n".join(matches), "matches": matches}
            return {"status": "SUCCESS", "message": "\n".join(matches) if matches else "No filenames matched.", "matches": matches}
        except (OSError, ValueError, re.error) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def search_code(self, query: str, relative_path: str = ".", max_results: int = 80) -> dict[str, Any]:
        try:
            target = self.safe_path(relative_path, allow_reference=True)
            pattern = re.compile(query, re.IGNORECASE)
            matches = []
            scanned = 0
            for root, dirs, names in os.walk(target):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if not self.is_ignored(root_path / d)]
                for name in names:
                    path = root_path / name
                    if self.is_ignored(path) or self.is_sensitive(path) or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".exe", ".dll", ".pyc"}:
                        continue
                    if path.stat().st_size > MAX_TEXT_BYTES:
                        continue
                    scanned += 1
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    for line_no, line in enumerate(text.splitlines(), 1):
                        if pattern.search(line):
                            matches.append(f"{self.display_path(path)}:{line_no}: {line.strip()[:240]}")
                            if len(matches) >= max(1, min(max_results, 300)):
                                return {"status": "SUCCESS", "message": "\n".join(matches), "matches": matches}
            return {"status": "SUCCESS", "message": "\n".join(matches) if matches else "No code matched.", "matches": matches}
        except (OSError, ValueError, re.error) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def inspect_project(self) -> dict[str, Any]:
        try:
            from gd_core.project import inspect_project

            data = inspect_project(self.root)
            return {"status": "SUCCESS", "message": data["summary"], "project": data}
        except Exception as exc:
            return {"status": "FAILURE", "message": f"Project inspection failed: {exc}"}

    def create_directory(self, relative_path: str) -> dict[str, Any]:
        try:
            path = self.safe_path(relative_path)
            if path == self.root:
                raise ValueError("Cannot create the workspace root.")
            path.mkdir(parents=True, exist_ok=True)
            return {"status": "SUCCESS", "message": f"Created directory {relative_path}."}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def _write(self, file_path: str, content: str, operation: str, overwrite: bool) -> dict[str, Any]:
        try:
            path = self.safe_path(file_path)
            if path == self.root or path.is_dir():
                raise ValueError("Target must be a file inside the workspace.")
            before = path.read_bytes() if path.exists() else None
            if before is not None and not overwrite:
                raise ValueError("File already exists; use write_file or edit_file to change it.")
            current = path.read_bytes() if path.exists() else None
            if current != before:
                raise ValueError("File changed outside GD Assistant; write was refused.")
            after = content.encode("utf-8")
            _atomic_write(path, after)
            change = self.tracker.record(self.relative(path), before, after, operation)
            return {
                "status": "SUCCESS",
                "message": f"{operation} {self.relative(path)}.",
                "change_id": change.id,
                "diff": change.diff,
            }
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def create_file(self, file_path: str, content: str) -> dict[str, Any]:
        return self._write(file_path, content, "Created", overwrite=False)

    def write_file(self, file_path: str, content: str, expected_sha256: str | None = None) -> dict[str, Any]:
        try:
            path = self.safe_path(file_path)
            current = path.read_bytes() if path.exists() else None
            if expected_sha256 and _hash_bytes(current) != expected_sha256:
                return {"status": "FAILURE", "message": "File changed since it was read; write was refused."}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}
        return self._write(file_path, content, "Modified", overwrite=True)

    def edit_file(self, file_path: str, target_block: str, replacement_block: str) -> dict[str, Any]:
        try:
            path = self.safe_path(file_path)
            raw_bytes = path.read_bytes()
            raw = raw_bytes.decode("utf-8")
            normalized = raw.replace("\r\n", "\n")
            target = target_block.replace("\r\n", "\n")
            count = normalized.count(target)
            if not target or count != 1:
                raise ValueError(f"Target block must match exactly once (matched {count}).")
            updated = normalized.replace(target, replacement_block.replace("\r\n", "\n"), 1)
            if "\r\n" in raw:
                updated = updated.replace("\n", "\r\n")
            return self.write_file(file_path, updated, hashlib.sha256(raw_bytes).hexdigest())
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def delete_file(self, file_path: str) -> dict[str, Any]:
        try:
            path = self.safe_path(file_path)
            if not path.is_file():
                raise ValueError("File not found.")
            before = path.read_bytes()
            path.unlink()
            change = self.tracker.record(self.relative(path), before, None, "Deleted")
            return {"status": "SUCCESS", "message": f"Deleted {self.relative(path)}.", "change_id": change.id, "diff": change.diff}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def move_file(self, source_path: str, destination_path: str) -> dict[str, Any]:
        try:
            source = self.safe_path(source_path)
            destination = self.safe_path(destination_path)
            if not source.is_file():
                raise ValueError("Source file not found.")
            if destination.exists():
                raise ValueError("Destination already exists.")
            before = source.read_bytes()
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            group_id = os.urandom(6).hex()
            self.tracker.record(self.relative(source), before, None, "Moved from", group_id)
            self.tracker.record(self.relative(destination), None, before, "Moved to", group_id)
            return {"status": "SUCCESS", "message": f"Moved {source_path} to {destination_path}."}
        except (OSError, ValueError) as exc:
            return {"status": "FAILURE", "message": str(exc)}

    def rename_file(self, source_path: str, new_name: str) -> dict[str, Any]:
        return self.move_file(source_path, str(Path(source_path).with_name(new_name)))
