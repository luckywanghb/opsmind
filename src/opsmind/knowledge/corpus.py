"""Fail-closed local corpus loading, deterministic cleaning and chunking."""

import json
import re
import unicodedata
from pathlib import Path, PureWindowsPath

from opsmind.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeManifest,
    KnowledgeMetadata,
)

DEFAULT_CORPUS = Path(__file__).parent / "data"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


class CorpusValidationError(ValueError):
    """Safe error with no source path or document content."""

    def __init__(self) -> None:
        super().__init__("KNOWLEDGE_CORPUS_INVALID")


def clean_content(content: str) -> str:
    if not isinstance(content, str):
        raise CorpusValidationError()
    content = unicodedata.normalize(
        "NFKC", content.replace("\r\n", "\n").replace("\r", "\n")
    )
    if any(
        unicodedata.category(c) in {"Cs", "Cc"} and c not in "\n\t" for c in content
    ):
        raise CorpusValidationError()
    content = "\n".join(line.rstrip() for line in content.split("\n"))
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    if not content or len(content) > 1_000_000:
        raise CorpusValidationError()
    return content


def chunk_document(document: KnowledgeDocument) -> tuple[KnowledgeChunk, ...]:
    content = clean_content(document.content)
    metadata = document.model_dump(include=set(KnowledgeMetadata.model_fields))
    chunks = []
    headings = list(re.finditer(r"(?m)^#{1,6}\s+(.+)$", content))
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        preceding = [h.group(1) for h in headings if h.start() <= start]
        section = (preceding[-1] if preceding else document.title)[:256]
        chunks.append(
            KnowledgeChunk(
                **metadata,
                chunk_id=f"{document.document_id}.{document.version}.{start:07d}",
                section=section,
                content=content[start:end],
            )
        )
        if end == len(content):
            break
        start = end - CHUNK_OVERLAP
    return tuple(chunks)


def load_corpus(
    root: Path = DEFAULT_CORPUS,
) -> tuple[KnowledgeManifest, tuple[KnowledgeDocument, ...]]:
    try:
        root = root.resolve(strict=True)
        manifest_path = (root / "manifest.json").resolve(strict=True)
        if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
            raise CorpusValidationError()
        if manifest_path.stat().st_size > 1_000_000:
            raise CorpusValidationError()
        manifest = KnowledgeManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        ids: set[str] = set()
        documents = []
        for source in manifest.documents:
            if source.document_id in ids:
                raise CorpusValidationError()
            ids.add(source.document_id)
            relative = Path(source.source_file)
            windows_path = PureWindowsPath(source.source_file)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in source.source_file
                or windows_path.is_absolute()
                or bool(windows_path.drive)
            ):
                raise CorpusValidationError()
            path = (root / relative).resolve(strict=True)
            if not path.is_relative_to(root) or path.stat().st_size > 4_000_000:
                raise CorpusValidationError()
            content = clean_content(path.read_text(encoding="utf-8"))
            documents.append(
                KnowledgeDocument(
                    **source.model_dump(exclude={"source_file", "tags"}),
                    content=content,
                )
            )
        return manifest, tuple(documents)
    except (OSError, ValueError, TypeError, RecursionError):
        raise CorpusValidationError() from None
