from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirectoryInfo:
    name: str
    path: str
    has_obsidian: bool
    markdown_count: int
    is_candidate: bool


@dataclass(frozen=True)
class VaultCandidate:
    name: str
    path: str
    score: int
    reason: str
    markdown_count: int
    has_obsidian: bool


def list_windows_drives() -> list[dict[str, str]]:
    drives: list[dict[str, str]] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if root.exists():
            drives.append({"name": f"{letter}:\\", "path": str(root)})
    return drives


def safe_path(value: str | None) -> Path:
    if not value:
        return Path.home()
    return Path(value).expanduser().resolve()


def nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current if current.exists() else Path.home()


def markdown_count(path: Path, limit: int = 200, max_depth: int = 2, max_dirs: int = 120) -> int:
    count = 0
    visited_dirs = 0
    stack: list[tuple[Path, int]] = [(path, 0)]
    try:
        while stack:
            current, depth = stack.pop()
            visited_dirs += 1
            if visited_dirs > max_dirs:
                return count
            try:
                children = list(current.iterdir())
            except (OSError, PermissionError):
                continue
            for child in children:
                if child.name.startswith(".") and child.name != ".obsidian":
                    continue
                if child.is_file() and child.suffix.lower() == ".md":
                    count += 1
                    if count >= limit:
                        return count
                elif child.is_dir() and depth < max_depth and child.name.lower() not in {"node_modules", ".git", ".obsidian"}:
                    stack.append((child, depth + 1))
    except (OSError, PermissionError):
        return 0
    return count


def directory_info(path: Path) -> DirectoryInfo:
    count = 0
    try:
        for child in path.iterdir():
            if child.is_file() and child.suffix.lower() == ".md":
                count += 1
                if count >= 50:
                    break
    except (OSError, PermissionError):
        count = 0
    has_obsidian = (path / ".obsidian").exists()
    return DirectoryInfo(
        name=path.name or str(path),
        path=str(path),
        has_obsidian=has_obsidian,
        markdown_count=count,
        is_candidate=has_obsidian or count > 0,
    )


def list_directories(path_value: str | None) -> dict[str, object]:
    if not path_value:
        return {"path": "", "parent": "", "drives": list_windows_drives(), "directories": []}

    requested_path = safe_path(path_value)
    path = nearest_existing(requested_path)
    directories: list[DirectoryInfo] = []
    try:
        children = sorted(
            [child for child in path.iterdir() if child.is_dir()],
            key=lambda item: (not ((item / ".obsidian").exists()), item.name.lower()),
        )
    except (OSError, PermissionError):
        children = []

    for child in children[:300]:
        if child.name.lower() in {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)"}:
            continue
        try:
            directories.append(directory_info(child))
        except (OSError, PermissionError):
            continue

    parent = str(path.parent) if path.parent != path else ""
    return {
        "path": str(path),
        "requested_path": str(requested_path),
        "parent": parent,
        "drives": list_windows_drives(),
        "directories": [item.__dict__ for item in directories],
        "current": directory_info(path).__dict__ if path.exists() else None,
    }


def candidate_roots() -> list[Path]:
    roots = [
        Path.cwd(),
        Path.cwd().parent,
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path.home() / "OneDrive",
        Path.home() / "OneDrive" / "Documents",
        Path("C:/Obsidian"),
        Path("C:/ObsidianVaults"),
        Path("C:/Project"),
    ]
    for key, value in os.environ.items():
        if key.upper().startswith("ONEDRIVE") and value:
            roots.append(Path(value))
            roots.append(Path(value) / "Documents")
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen and resolved.exists() and resolved.is_dir():
            seen.add(key)
            unique.append(resolved)
    return unique


def score_candidate(path: Path) -> VaultCandidate | None:
    has_obsidian = (path / ".obsidian").exists()
    count = markdown_count(path, limit=200)
    name = path.name or str(path)
    score = 0
    reasons: list[str] = []
    if has_obsidian:
        score += 100
        reasons.append(".obsidian")
    if count:
        score += min(count, 80)
        reasons.append(f"{count} markdown")
    lowered = name.lower()
    if any(token in lowered for token in ("obsidian", "vault", "marketing", "knowledge", "base")):
        score += 15
        reasons.append("name match")
    if score < 15:
        return None
    return VaultCandidate(
        name=name,
        path=str(path),
        score=score,
        reason=", ".join(reasons),
        markdown_count=count,
        has_obsidian=has_obsidian,
    )


def discover_vaults(max_depth: int = 3, max_results: int = 20) -> list[dict[str, object]]:
    candidates: dict[str, VaultCandidate] = {}

    def visit(path: Path, depth: int) -> None:
        if len(candidates) >= max_results * 3:
            return
        candidate = score_candidate(path)
        if candidate:
            candidates[str(path).lower()] = candidate
        if depth >= max_depth:
            return
        try:
            children = [child for child in path.iterdir() if child.is_dir()]
        except (OSError, PermissionError):
            return
        for child in children[:80]:
            if child.name.lower() in {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "node_modules", ".git"}:
                continue
            visit(child, depth + 1)

    for root in candidate_roots():
        visit(root, 0)

    ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    return [item.__dict__ for item in ranked[:max_results]]
