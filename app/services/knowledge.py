from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeDocument
from app.schemas import KnowledgeSnippet


IGNORED_DIRS = {".obsidian", ".git", ".trash", "node_modules", "__pycache__"}
WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)


@dataclass
class KnowledgeChunk:
    source_path: str
    title: str
    text: str
    tokens: list[str]


@dataclass
class KnowledgeIndex:
    vault_path: str
    indexed_at: str
    chunks: list[KnowledgeChunk]


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\ufeff", "").split())


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in WORD_RE.finditer(text)]


def read_markdown(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def extract_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").strip().title()


def split_into_chunks(text: str, max_chars: int = 1800) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    paragraphs = re.split(r"\n\s*\n|(?<=\.)\s+(?=[А-ЯA-Z0-9])", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = f"{current} {paragraph}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


class KnowledgeBase:
    def __init__(self, vault_path: str, index_path: Path):
        self.vault_path = Path(vault_path).expanduser()
        self.index_path = index_path

    def markdown_files(self) -> list[Path]:
        if not self.vault_path.exists():
            return []
        files: list[Path] = []
        for path in self.vault_path.rglob("*.md"):
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            files.append(path)
        return sorted(files)

    async def rebuild_index(self, session: AsyncSession) -> dict[str, int | str]:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        chunks: list[KnowledgeChunk] = []
        await session.execute(delete(KnowledgeDocument))

        for path in self.markdown_files():
            raw = read_markdown(path)
            title = extract_title(path, raw)
            relative = str(path.relative_to(self.vault_path)).replace("\\", "/")
            body_chunks = split_into_chunks(raw)
            content_hash = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
            for chunk in body_chunks:
                tokens = tokenize(f"{title} {chunk}")
                chunks.append(KnowledgeChunk(source_path=relative, title=title, text=chunk, tokens=tokens))
            session.add(
                KnowledgeDocument(
                    path=relative,
                    title=title,
                    content_hash=content_hash,
                    chunk_count=len(body_chunks),
                )
            )

        payload = {
            "vault_path": str(self.vault_path),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "chunks": [asdict(chunk) for chunk in chunks],
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        await session.commit()
        return {"documents": len(self.markdown_files()), "chunks": len(chunks), "index_path": str(self.index_path)}

    def load_index(self) -> KnowledgeIndex:
        if not self.index_path.exists():
            return KnowledgeIndex(vault_path=str(self.vault_path), indexed_at="", chunks=[])
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        chunks = [KnowledgeChunk(**item) for item in payload.get("chunks", [])]
        return KnowledgeIndex(
            vault_path=payload.get("vault_path", str(self.vault_path)),
            indexed_at=payload.get("indexed_at", ""),
            chunks=chunks,
        )

    def search(self, query: str, limit: int = 10) -> list[KnowledgeSnippet]:
        index = self.load_index()
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_set = set(query_tokens)
        scored: list[KnowledgeSnippet] = []
        for chunk in index.chunks:
            if not chunk.tokens:
                continue
            token_counts = sum(1 for token in chunk.tokens if token in query_set)
            phrase_bonus = 1.5 if query.lower() in chunk.text.lower() else 0.0
            title_bonus = 1.0 if any(token in tokenize(chunk.title) for token in query_tokens) else 0.0
            score = token_counts + phrase_bonus + title_bonus
            if score <= 0:
                continue
            scored.append(
                KnowledgeSnippet(
                    source_path=chunk.source_path,
                    title=chunk.title,
                    text=chunk.text[:1800],
                    score=float(score),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def save_markdown_report(self, title: str, markdown: str) -> str:
        if not self.vault_path.exists():
            return ""
        reports_dir = self.vault_path / "05_Reports" / "generated_plans"
        reports_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9А-Яа-яЁё_-]+", "_", title).strip("_")[:80] or "content_plan"
        filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{slug}.md"
        target = reports_dir / filename
        target.write_text(markdown, encoding="utf-8")
        return str(target)

