"""Language-agnostic project detection, indexing, and Minecraft profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None


LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".java": "Java", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".hpp": "C++", ".cs": "C#", ".rs": "Rust", ".go": "Go", ".kt": "Kotlin", ".kts": "Kotlin",
    ".swift": "Swift", ".php": "PHP", ".rb": "Ruby", ".lua": "Lua", ".dart": "Dart", ".html": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".xml": "XML", ".md": "Markdown",
}
SYMBOL_PATTERNS = {
    "Python": r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)",
    "Java": r"\b(?:class|interface|enum|record)\s+([A-Za-z_$]\w*)",
    "Kotlin": r"\b(?:class|object|interface|fun)\s+([A-Za-z_]\w*)",
    "JavaScript": r"\b(?:function|class)\s+([A-Za-z_$]\w*)|\b(?:const|let)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s*)?\(",
    "TypeScript": r"\b(?:function|class|interface|type|enum)\s+([A-Za-z_$]\w*)|\b(?:const|let)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s*)?\(",
    "C++": r"\b(?:class|struct|enum)\s+([A-Za-z_]\w*)|\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{",
    "C": r"\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{",
    "C#": r"\b(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)",
    "Rust": r"\b(?:fn|struct|enum|trait|mod)\s+([A-Za-z_]\w*)",
    "Go": r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)|\btype\s+([A-Za-z_]\w*)",
    "Ruby": r"\b(?:class|module|def)\s+([A-Za-z_]\w*[!?=]?)",
    "PHP": r"\b(?:class|interface|trait|function)\s+([A-Za-z_]\w*)",
    "Swift": r"\b(?:class|struct|enum|protocol|func)\s+([A-Za-z_]\w*)",
    "Dart": r"\b(?:class|enum|mixin)\s+([A-Za-z_]\w*)|\b[A-Za-z_<>, ]+\s+([A-Za-z_]\w*)\s*\(",
    "Lua": r"\b(?:function)\s+([A-Za-z_][\w.:]*)",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        if tomllib is not None:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _property(text: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*([^\r\n#]+)", text, re.M)
    return match.group(1).strip().strip('"\'') if match else ""


def _existing(root: Path, *names: str) -> list[str]:
    return [name for name in names if (root / name).is_file()]


def detect_minecraft(root: Path) -> dict[str, Any] | None:
    fabric_path = root / "fabric.mod.json"
    quilt_path = root / "quilt.mod.json"
    neo_path = root / "neoforge.mods.toml"
    forge_path = root / "mods.toml"
    metadata_path = fabric_path if fabric_path.is_file() else quilt_path if quilt_path.is_file() else neo_path if neo_path.is_file() else forge_path if forge_path.is_file() else None
    if metadata_path is None:
        return None
    metadata = _read_json(metadata_path) if metadata_path.suffix == ".json" else _read_toml(metadata_path)
    gradle_props = _read_toml(root / "gradle.properties")
    prop_text = (root / "gradle.properties").read_text(encoding="utf-8", errors="replace") if (root / "gradle.properties").is_file() else ""
    build_gradle = (root / "build.gradle").read_text(encoding="utf-8", errors="replace") if (root / "build.gradle").is_file() else ""
    build_gradle_kts = (root / "build.gradle.kts").read_text(encoding="utf-8", errors="replace") if (root / "build.gradle.kts").is_file() else ""
    gradle_text = build_gradle + "\n" + build_gradle_kts
    if fabric_path.is_file():
        loader = "Fabric"
    elif quilt_path.is_file():
        loader = "Quilt"
    elif neo_path.is_file() or "neoforge" in gradle_text.casefold():
        loader = "NeoForge"
    else:
        loader = "Forge"
    if metadata_path.suffix == ".json":
        mod_id = str(metadata.get("id") or "")
        entrypoints = metadata.get("entrypoints") or {}
        dependencies = metadata.get("depends") or metadata.get("recommends") or {}
        loader_key = {"Fabric": "fabricloader", "Quilt": "quilt_loader", "NeoForge": "neoforge", "Forge": "forge"}[loader]
        loader_version = str((metadata.get("depends") or {}).get(loader_key) or (metadata.get("dependencies") or {}).get(loader_key) or gradle_props.get("loader_version") or _property(prop_text, "loader_version") or "")
    else:
        mods = metadata.get("mods") or []
        first_mod = mods[0] if isinstance(mods, list) and mods else {}
        mod_id = str(first_mod.get("modId") or "")
        entrypoints = {"main": first_mod.get("main")} if first_mod.get("main") else {}
        dependencies = metadata.get("dependencies") or {}
        loader_version = str((metadata.get("dependencies") or {}).get(loader.casefold()) or "")
    minecraft_version = str(gradle_props.get("minecraft_version") or _property(prop_text, "minecraft_version"))
    mappings = str(gradle_props.get("mappings") or _property(prop_text, "mappings") or gradle_props.get("yarn_mappings") or _property(prop_text, "yarn_mappings"))
    mapping_system = "Yarn" if "yarn" in mappings.casefold() or "yarn_mappings" in gradle_props or _property(prop_text, "yarn_mappings") else "Mojang" if "mojmap" in mappings.casefold() or "mojang" in mappings.casefold() else "Official" if "official" in mappings.casefold() else mappings or "Unknown"
    java_version = str(gradle_props.get("java_version") or _property(prop_text, "java_version"))
    toolchain = re.search(r"(?:JavaLanguageVersion\.of|languageVersion\.set|jvmToolchain\s*\()\s*\(?\s*(\d+)", gradle_text)
    if toolchain:
        java_version = toolchain.group(1)
    source_dirs = [name for name in ("src/main/java", "src/main/kotlin", "src/client/java", "src/main/resources", "src/client/resources", "src/test/java", "src/test/kotlin") if (root / name).is_dir()]
    wrapper = "gradlew.bat" if (root / "gradlew.bat").is_file() else "gradlew" if (root / "gradlew").is_file() else "gradle" if (root / "gradle.bat").is_file() else "gradle"
    commands = {
        "build": f"{wrapper} build",
        "test": f"{wrapper} test",
        "run_client": f"{wrapper} runClient",
        "run_server": f"{wrapper} runServer",
        "sources": f"{wrapper} genSources",
    }
    return {
        "kind": "minecraft",
        "loader": loader,
        "loader_version": loader_version,
        "minecraft_version": minecraft_version,
        "mapping_system": mapping_system,
        "mappings": mappings,
        "java_version": java_version,
        "mod_id": mod_id,
        "entrypoints": entrypoints,
        "dependencies": dependencies,
        "source_dirs": source_dirs,
        "metadata_file": metadata_path.name,
        "gradle_wrapper": wrapper,
        "commands": commands,
        "profile": _minecraft_profile(loader, minecraft_version, java_version, mapping_system, mod_id, source_dirs),
    }


def _minecraft_profile(loader: str, minecraft: str, java: str, mappings: str, mod_id: str, source_dirs: list[str]) -> str:
    return (
        f"Minecraft project profile (verified from project files):\n"
        f"- Loader: {loader}; Minecraft: {minecraft or 'not declared'}; Java: {java or 'not declared'}.\n"
        f"- Mappings: {mappings}; Mod ID: {mod_id or 'not declared'}.\n"
        f"- Existing source/resource directories: {', '.join(source_dirs) or 'none detected'}.\n"
        f"- Use {loader}-specific APIs and the project's declared mappings. Do not invent APIs or upgrade versions.\n"
        f"- Inspect actual Gradle tasks before choosing build/run commands. Preserve wrapper, mod ID, packages, and licenses."
    )


def inspect_project(root: Path) -> dict[str, Any]:
    root = root.resolve()
    minecraft = detect_minecraft(root)
    languages: dict[str, int] = {}
    manifests: list[str] = []
    dependencies: list[str] = []
    frameworks: list[str] = []
    entrypoints: list[str] = []
    commands: list[dict[str, str]] = []
    kind = "generic"

    for child in root.iterdir():
        if child.is_file():
            language = LANGUAGE_EXTENSIONS.get(child.suffix.lower())
            if language:
                languages[language] = languages.get(language, 0) + 1

    def add_command(label: str, command: str) -> None:
        if command and not any(item["command"] == command for item in commands):
            commands.append({"label": label, "command": command})

    package = _read_json(root / "package.json")
    pyproject = _read_toml(root / "pyproject.toml")
    cargo = _read_toml(root / "Cargo.toml")
    if package:
        kind = "node"
        manifests.append("package.json")
        scripts = package.get("scripts") or {}
        for script_name in ("build", "test", "dev", "start", "lint", "format"):
            if script_name in scripts:
                add_command(script_name.title(), f"npm run {script_name}")
        dependencies.extend(list((package.get("dependencies") or {}).keys()))
        dependencies.extend(list((package.get("devDependencies") or {}).keys()))
        if any(name in dependencies for name in ("react", "react-dom")):
            frameworks.append("React")
        if "next" in dependencies:
            frameworks.append("Next.js")
        if "vue" in dependencies:
            frameworks.append("Vue")
    if (root / "requirements.txt").is_file() or pyproject:
        kind = "python"
        manifests.extend(_existing(root, "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"))
        if (root / "manage.py").is_file():
            frameworks.append("Django")
            add_command("Test", "python manage.py test")
        if any((root / name).exists() for name in ("pytest.ini", "tests", "test")):
            add_command("Test", "python -m pytest")
        dependencies.extend(str(item) for item in (pyproject.get("project", {}).get("dependencies") or [])[:50])
    if (root / "Cargo.toml").is_file():
        kind = "rust"
        manifests.append("Cargo.toml")
        add_command("Build", "cargo build")
        add_command("Test", "cargo test")
        add_command("Lint", "cargo clippy")
        dependencies.extend(list((cargo.get("dependencies") or {}).keys()))
    if (root / "go.mod").is_file():
        kind = "go"
        manifests.append("go.mod")
        add_command("Build", "go build ./...")
        add_command("Test", "go test ./...")
        add_command("Vet", "go vet ./...")
    if (root / "pom.xml").is_file():
        kind = "java-maven"
        manifests.append("pom.xml")
        wrapper = "mvnw.cmd" if (root / "mvnw.cmd").is_file() else "mvnw" if (root / "mvnw").is_file() else "mvn"
        add_command("Build", f"{wrapper} package")
        add_command("Test", f"{wrapper} test")
    elif (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        kind = "java-gradle"
        manifests.extend(_existing(root, "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"))
        wrapper = "gradlew.bat" if (root / "gradlew.bat").is_file() else "gradlew" if (root / "gradlew").is_file() else "gradle"
        add_command("Build", f"{wrapper} build")
        add_command("Test", f"{wrapper} test")
    if (root / "CMakeLists.txt").is_file():
        kind = "cmake"
        manifests.append("CMakeLists.txt")
        add_command("Configure", "cmake -S . -B build")
        add_command("Build", "cmake --build build")
        add_command("Test", "ctest --test-dir build")
    if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
        kind = "dotnet"
        manifests.extend(path.name for path in list(root.glob("*.csproj")) + list(root.glob("*.sln")))
        add_command("Restore", "dotnet restore")
        add_command("Build", "dotnet build")
        add_command("Test", "dotnet test")
        frameworks.append(".NET")
    if (root / "pubspec.yaml").is_file():
        kind = "flutter"
        manifests.append("pubspec.yaml")
        add_command("Test", "flutter test")
        add_command("Build", "flutter build")
        frameworks.append("Flutter")
    if (root / "composer.json").is_file():
        kind = "php"
        manifests.append("composer.json")
        add_command("Test", "composer test")
    if (root / "Gemfile").is_file():
        kind = "ruby"
        manifests.append("Gemfile")
        add_command("Test", "bundle exec rake test")
    if (root / "Makefile").is_file():
        manifests.append("Makefile")
        add_command("Build", "make")
        add_command("Test", "make test")
    config_text = "\n".join(
        (root / name).read_text(encoding="utf-8", errors="ignore")
        for name in ("requirements.txt", "pyproject.toml", "package.json", "build.gradle", "build.gradle.kts")
        if (root / name).is_file()
    )
    if re.search(r"\b(PySide6|PyQt6|PyQt5)\b", config_text):
        frameworks.append("Qt")
    if "spring-boot" in config_text.casefold():
        frameworks.append("Spring Boot")
    if "usewpf" in "\n".join((root / path.name).read_text(encoding="utf-8", errors="ignore") for path in root.glob("*.csproj")).casefold():
        frameworks.append("WPF")
    if minecraft:
        kind = "minecraft"
        manifests.append(minecraft["metadata_file"])
        frameworks.append(f"Minecraft {minecraft['loader']}")
        dependencies.extend(str(key) for key in minecraft["dependencies"])
        entrypoints.extend(str(value) for value in minecraft["entrypoints"].values() if isinstance(value, str))
        commands = [{"label": key.replace("_", " ").title(), "command": value} for key, value in minecraft["commands"].items()]
    else:
        for name in ("main.py", "app.py", "manage.py", "index.js", "src/main.ts", "src/main.tsx", "src/main.rs", "main.go", "Program.cs"):
            if (root / name).is_file():
                entrypoints.append(name)

    instructions = ""
    for name in ("GD_ASSISTANT.md", "AGENTS.md"):
        path = root / name
        if path.is_file():
            instructions += f"\nProject instructions from {name}:\n{path.read_text(encoding='utf-8', errors='replace')[:12000]}\n"

    language_counts: dict[str, int] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "__pycache__"}]
        for name in files:
            language = LANGUAGE_EXTENSIONS.get(Path(name).suffix.lower())
            if language:
                language_counts[language] = language_counts.get(language, 0) + 1
        if sum(language_counts.values()) >= 5000:
            break
    if kind == "generic" and language_counts:
        dominant = max(language_counts, key=language_counts.get)
        kind = dominant.casefold().replace("+", "p").replace("#", "sharp")
    summary = (
        f"Project: {root.name}\nType: {kind}\nLanguages: {', '.join(language_counts) or 'unknown'}\n"
        f"Frameworks: {', '.join(frameworks) or 'none detected'}\nManifests: {', '.join(manifests) or 'none detected'}\n"
        f"Entrypoints: {', '.join(entrypoints) or 'none detected'}\n"
        f"Dependencies: {len(dependencies)}\nSuggested commands: {len(commands)}"
    )
    if minecraft:
        summary += (
            f"\nMinecraft: {minecraft['minecraft_version'] or 'unknown'}; loader: {minecraft['loader']} "
            f"{minecraft['loader_version']}; Java: {minecraft['java_version'] or 'unknown'}; mappings: {minecraft['mapping_system']}"
        )
    return {
        "name": root.name,
        "root": str(root),
        "kind": kind,
        "languages": language_counts,
        "frameworks": frameworks,
        "manifests": manifests,
        "dependencies": dependencies,
        "entrypoints": entrypoints,
        "commands": commands,
        "instructions": instructions.strip(),
        "minecraft": minecraft,
        "summary": summary,
    }


def minecraft_audit(root: Path) -> dict[str, Any]:
    info = detect_minecraft(root)
    if not info:
        return {"status": "FAILURE", "message": "No Minecraft mod metadata found in this project."}
    issues: list[str] = []
    if not info["minecraft_version"]:
        issues.append("Minecraft version is not declared in gradle.properties.")
    if not info["java_version"]:
        issues.append("Java toolchain version is not declared.")
    if not info["mod_id"]:
        issues.append("Mod ID is missing from mod metadata.")
    if not info["entrypoints"]:
        issues.append("No mod entrypoint is declared.")
    if info["mod_id"] and not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", info["mod_id"]):
        issues.append("Mod ID should use lowercase letters, numbers, underscores, or hyphens.")
    if info["mapping_system"] == "Unknown":
        issues.append("Mapping system could not be determined.")
    if not info["source_dirs"]:
        issues.append("Expected Minecraft source/resource directories were not found.")
    if not (root / info["gradle_wrapper"]).is_file() and info["gradle_wrapper"] not in {"gradle", "gradle.bat"}:
        issues.append("The detected Gradle wrapper is missing.")
    metadata_path = root / info["metadata_file"]
    metadata = _read_json(metadata_path) if metadata_path.suffix == ".json" else _read_toml(metadata_path)
    for mixin in metadata.get("mixins") or []:
        config_name = mixin if isinstance(mixin, str) else str(mixin.get("config") or "")
        if config_name and not (root / "src/main/resources" / config_name).is_file():
            issues.append(f"Mixin config is missing: {config_name}")
    for entrypoint in info["entrypoints"].values():
        if isinstance(entrypoint, str) and "." in entrypoint:
            relative = Path(*entrypoint.split(".")).with_suffix(".java")
            if not any((root / source / relative).is_file() for source in ("src/main/java", "src/client/java")):
                issues.append(f"Entrypoint source was not found: {entrypoint}")
    return {
        "status": "SUCCESS",
        "message": "Minecraft audit complete.",
        "project": info,
        "issues": issues,
        "compatible": not issues,
    }


class ProjectIndex:
    """Small persistent symbol/path index; full-text search stays on demand."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace
        key = hashlib.sha256(str(workspace.root).encode("utf-8")).hexdigest()[:20]
        base = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant" / "code-index"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"{key}.json"
        self.files: dict[str, dict[str, Any]] = {}

    def refresh(self, incremental: bool = True) -> dict[str, Any]:
        previous = self.files
        if incremental:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.files = data.get("files", {}) if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self.files = {}
        else:
            self.files = {}
        seen: set[str] = set()
        for dirpath, dirs, names in os.walk(self.workspace.root):
            root_path = Path(dirpath)
            dirs[:] = [d for d in dirs if not self.workspace.is_ignored(root_path / d)]
            for name in names:
                path = root_path / name
                if self.workspace.is_ignored(path) or self.workspace.is_sensitive(path):
                    continue
                language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
                if not language or path.stat().st_size > 512 * 1024:
                    continue
                rel = self.workspace.relative(path)
                seen.add(rel)
                stat = path.stat()
                old = previous.get(rel) or self.files.get(rel) or {}
                signature = f"{stat.st_mtime_ns}:{stat.st_size}"
                if incremental and old.get("signature") == signature:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                pattern = SYMBOL_PATTERNS.get(language)
                symbols: list[str] = []
                if pattern:
                    for match in re.finditer(pattern, text, re.M):
                        symbol = next((group for group in match.groups() if group), "")
                        if symbol and symbol not in symbols:
                            symbols.append(symbol)
                        if len(symbols) >= 80:
                            break
                self.files[rel] = {"signature": signature, "language": language, "symbols": symbols}
                if len(seen) >= 5000:
                    break
            if len(seen) >= 5000:
                break
        self.files = {path: data for path, data in self.files.items() if path in seen}
        self.path.write_text(json.dumps({"files": self.files}, ensure_ascii=False), encoding="utf-8")
        return {"status": "SUCCESS", "message": f"Indexed {len(self.files)} source files.", "files": len(self.files)}

    def relevant_files(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        terms = {term.casefold() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)}
        scored = []
        for path, data in self.files.items():
            haystack = (path + " " + " ".join(data.get("symbols", []))).casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append({"path": path, "score": score, "symbols": data.get("symbols", [])})
        scored.sort(key=lambda item: (-item["score"], item["path"]))
        return scored[:limit]

    def summary(self) -> dict[str, Any]:
        languages: dict[str, int] = {}
        for data in self.files.values():
            language = data.get("language", "unknown")
            languages[language] = languages.get(language, 0) + 1
        return {"files": len(self.files), "languages": languages, "symbols": sum(len(data.get("symbols", [])) for data in self.files.values())}
