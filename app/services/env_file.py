from __future__ import annotations

from pathlib import Path


def _clean_value(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def update_env_file(values: dict[str, str], env_path: str | Path = ".env") -> None:
    path = Path(env_path)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = {key: _clean_value(value) for key, value in values.items() if value is not None}
    seen: set[str] = set()
    output: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in pending:
            output.append(f"{key}={pending[key]}")
            seen.add(key)
        else:
            output.append(line)

    missing = [key for key in pending if key not in seen]
    if missing and output and output[-1].strip():
        output.append("")
    for key in missing:
        output.append(f"{key}={pending[key]}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")

