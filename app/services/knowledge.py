from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeDocument
from app.schemas import KnowledgeSnippet


IGNORED_DIRS = {".obsidian", ".git", ".trash", "node_modules", "__pycache__"}
WORD_RE = re.compile(r"[\w\u0400-\u04ff]+", re.UNICODE)
HASHTAG_RE = re.compile(r"(?<!\w)#([\w\u0400-\u04ff][\w\u0400-\u04ff_-]*)", re.UNICODE)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

VECTOR_DIMS = 512
CHUNK_MAX_CHARS = 1700
CHUNK_OVERLAP_CHARS = 240
INDEX_VERSION = 2

CORE_PATH_HINTS = {
    "brand",
    "бренд",
    "tone",
    "voice",
    "offer",
    "оффер",
    "audience",
    "persona",
    "аудитор",
    "целевая",
    "product",
    "продукт",
    "competitor",
    "конкурент",
    "memory",
    "память",
    "facts",
    "profile",
    "followups",
}

QUERY_EXPANSIONS = {
    "бренд": ["brand", "позиционирование", "миссия", "тон", "tone"],
    "аудитория": ["ца", "persona", "personas", "клиент", "сегмент", "боли", "возражения"],
    "ца": ["аудитория", "клиент", "persona", "боли", "возражения"],
    "оффер": ["offer", "предложение", "услуга", "продукт", "цена", "пакет", "cta"],
    "контент": ["content", "рубрика", "hook", "хук", "пост", "reels", "telegram"],
    "стиль": ["tone", "voice", "тон", "голос", "коммуникация"],
    "память": ["memory", "facts", "profile", "workflow", "followups"],
    "конкурент": ["competitor", "рынок", "отличие", "позиционирование"],
}


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_path: str
    title: str
    heading: str
    text: str
    tokens: list[str]
    tags: list[str]
    links: list[str]
    metadata: dict[str, str]
    vector: list[float]


@dataclass
class KnowledgeIndex:
    vault_path: str
    indexed_at: str
    chunks: list[KnowledgeChunk]


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\ufeff", "").split())


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in WORD_RE.finditer(text) if len(match.group(0)) > 1]


def read_markdown(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.DOTALL)
    if not match:
        return {}, text

    metadata: dict[str, str] = {}
    current_key = ""
    current_items: list[str] = []
    for raw_line in match.group(1).splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("-") and current_key:
            current_items.append(line.lstrip()[1:].strip())
            metadata[current_key] = ", ".join(item for item in current_items if item)
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip().lower()
        current_items = []
        metadata[current_key] = value.strip().strip("\"'")
    return metadata, text[match.end() :]


def split_tag_value(value: str) -> list[str]:
    cleaned = value.strip().strip("[]")
    pieces = re.split(r"[,\s]+", cleaned)
    return [piece.strip().strip("\"'#") for piece in pieces if piece.strip().strip("\"'#")]


def extract_tags(text: str, metadata: dict[str, str]) -> list[str]:
    tags: set[str] = set()
    for key in ("tag", "tags"):
        if key in metadata:
            tags.update(split_tag_value(metadata[key]))
    tags.update(match.group(1).strip() for match in HASHTAG_RE.finditer(text))
    return sorted(tag.lower() for tag in tags if tag)


def extract_links(text: str) -> list[str]:
    links = {match.group(1).strip() for match in WIKILINK_RE.finditer(text)}
    return sorted(link for link in links if link)


def extract_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").strip().title()


def markdown_sections(text: str, title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_heading = title

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, body))

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading = match.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(heading)
            current_heading = " > ".join(heading_stack)
            current_lines = [heading]
            continue
        current_lines.append(line)
    flush()

    if not sections and text.strip():
        sections.append((title, text.strip()))
    return sections


def chunk_with_overlap(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap_chars: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            soft_cut = text.rfind(" ", start + max_chars - 280, end)
            if soft_cut > start:
                end = soft_cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def split_into_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    return chunk_with_overlap(text, max_chars=max_chars)


def vector_features(text: str) -> list[tuple[str, float]]:
    tokens = tokenize(text)
    features: list[tuple[str, float]] = [(f"w:{token}", 1.0) for token in tokens]
    features.extend((f"b:{left}_{right}", 1.25) for left, right in zip(tokens, tokens[1:]))
    for token in tokens:
        if len(token) >= 5:
            features.extend((f"c:{token[index:index + 3]}", 0.35) for index in range(len(token) - 2))
    return features


def stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def hashed_vector(text: str, dims: int = VECTOR_DIMS) -> list[float]:
    buckets: dict[int, float] = {}
    for feature, weight in vector_features(text):
        hashed = stable_hash(feature)
        index = hashed % dims
        sign = 1.0 if hashed & (1 << 63) else -1.0
        buckets[index] = buckets.get(index, 0.0) + sign * weight
    norm = math.sqrt(sum(value * value for value in buckets.values()))
    if not norm:
        return []
    return [round(buckets.get(index, 0.0) / norm, 6) for index in range(dims)]


def dot(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def expand_query_tokens(query: str) -> list[str]:
    tokens = tokenize(query)
    expanded: list[str] = list(tokens)
    token_set = set(tokens)
    for key, values in QUERY_EXPANSIONS.items():
        group = {key, *values}
        if token_set & group:
            expanded.extend(group)
    return sorted(set(expanded))


def is_core_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return any(hint in lowered for hint in CORE_PATH_HINTS)


def path_boost(path: str, query_tokens: set[str]) -> float:
    lowered = path.lower().replace("\\", "/")
    score = 0.0
    if is_core_path(lowered):
        score += 0.75
    if any(token in lowered for token in query_tokens):
        score += 0.45
    if "06_ai_memory" in lowered or "memory" in lowered or "память" in lowered:
        score += 0.25
    return score


def chunk_from_payload(item: dict[str, object]) -> KnowledgeChunk:
    raw_metadata = item.get("metadata") or {}
    if not isinstance(raw_metadata, dict):
        raw_metadata = {}
    return KnowledgeChunk(
        chunk_id=str(item.get("chunk_id") or f"{item.get('source_path', '')}#legacy"),
        source_path=str(item.get("source_path", "")),
        title=str(item.get("title", "")),
        heading=str(item.get("heading") or item.get("title", "")),
        text=str(item.get("text", "")),
        tokens=[str(token) for token in item.get("tokens", [])],
        tags=[str(tag) for tag in item.get("tags", [])],
        links=[str(link) for link in item.get("links", [])],
        metadata={str(key): str(value) for key, value in raw_metadata.items()},
        vector=[float(value) for value in item.get("vector", [])],
    )


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

        markdown_files = self.markdown_files()
        for path in markdown_files:
            raw = read_markdown(path)
            metadata, body = parse_frontmatter(raw)
            title = metadata.get("title") or extract_title(path, body)
            relative = str(path.relative_to(self.vault_path)).replace("\\", "/")
            tags = extract_tags(body, metadata)
            links = extract_links(body)
            body_chunks: list[tuple[str, str]] = []
            for heading, section_text in markdown_sections(body, title):
                body_chunks.extend((heading, chunk) for chunk in chunk_with_overlap(section_text))
            content_hash = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

            for index, (heading, chunk) in enumerate(body_chunks, start=1):
                chunk_id = f"{relative}#chunk-{index}"
                indexed_text = f"{title}\n{heading}\n{relative}\n{' '.join(tags)}\n{chunk}"
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=chunk_id,
                        source_path=relative,
                        title=title,
                        heading=heading,
                        text=chunk,
                        tokens=tokenize(indexed_text),
                        tags=tags,
                        links=links,
                        metadata={key: str(value) for key, value in metadata.items()},
                        vector=hashed_vector(indexed_text),
                    )
                )

            session.add(
                KnowledgeDocument(
                    path=relative,
                    title=title,
                    content_hash=content_hash,
                    chunk_count=len(body_chunks),
                )
            )

        payload = {
            "version": INDEX_VERSION,
            "retrieval": "hybrid_bm25_hash_vector",
            "vault_path": str(self.vault_path),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "chunks": [asdict(chunk) for chunk in chunks],
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        await session.commit()
        return {"documents": len(markdown_files), "chunks": len(chunks), "index_path": str(self.index_path)}

    def load_index(self) -> KnowledgeIndex:
        if not self.index_path.exists():
            return KnowledgeIndex(vault_path=str(self.vault_path), indexed_at="", chunks=[])
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        chunks = [chunk_from_payload(item) for item in payload.get("chunks", [])]
        return KnowledgeIndex(
            vault_path=payload.get("vault_path", str(self.vault_path)),
            indexed_at=payload.get("indexed_at", ""),
            chunks=chunks,
        )

    def needs_rebuild(self) -> bool:
        if not self.index_path.exists():
            return True
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        try:
            version = int(payload.get("version", 1))
        except (TypeError, ValueError):
            return True
        if version < INDEX_VERSION:
            return True
        indexed_vault = str(payload.get("vault_path", ""))
        return bool(indexed_vault and indexed_vault != str(self.vault_path))

    def search(self, query: str, limit: int = 10) -> list[KnowledgeSnippet]:
        index = self.load_index()
        query_tokens = expand_query_tokens(query)
        if not query_tokens:
            return []
        query_set = set(query_tokens)
        query_vector = hashed_vector(query)
        chunk_count = max(1, len(index.chunks))
        avgdl = sum(len(chunk.tokens) for chunk in index.chunks) / chunk_count if index.chunks else 1
        df: Counter[str] = Counter()
        for chunk in index.chunks:
            df.update(set(chunk.tokens))

        scored: list[KnowledgeSnippet] = []
        for chunk in index.chunks:
            if not chunk.tokens:
                continue
            tf = Counter(chunk.tokens)
            bm25 = 0.0
            dl = max(1, len(chunk.tokens))
            for token in query_set:
                frequency = tf.get(token, 0)
                if not frequency:
                    continue
                idf = math.log(1 + (chunk_count - df[token] + 0.5) / (df[token] + 0.5))
                bm25 += idf * (frequency * 2.2) / (frequency + 1.2 * (0.25 + 0.75 * dl / max(avgdl, 1)))

            vector_score = dot(query_vector, chunk.vector) * 4.0
            lower_query = query.lower().strip()
            lower_text = f"{chunk.title}\n{chunk.heading}\n{chunk.text}".lower()
            phrase_bonus = 2.2 if lower_query and lower_query in lower_text else 0.0
            title_bonus = 0.7 * len(query_set & set(tokenize(f"{chunk.title} {chunk.heading}")))
            tag_bonus = 0.8 * len(query_set & set(chunk.tags))
            structure_bonus = path_boost(chunk.source_path, query_set)
            score = bm25 + vector_score + phrase_bonus + title_bonus + tag_bonus + structure_bonus
            if score <= 0:
                continue
            scored.append(
                KnowledgeSnippet(
                    source_path=chunk.source_path,
                    title=chunk.title,
                    chunk_id=chunk.chunk_id,
                    heading=chunk.heading,
                    text=chunk.text[:1800],
                    score=float(score),
                    tags=chunk.tags,
                    links=chunk.links,
                    metadata=chunk.metadata,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def save_markdown_report(self, title: str, markdown: str) -> str:
        if not self.vault_path.exists():
            return ""
        reports_dir = self.vault_path / "05_Reports" / "generated_plans"
        reports_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9\u0400-\u04ff_-]+", "_", title).strip("_")[:80] or "content_plan"
        filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{slug}.md"
        target = reports_dir / filename
        target.write_text(markdown, encoding="utf-8")
        return str(target)
