"""Storage boundary; retrieval and Agent policy are deliberately separate."""

from pathlib import Path
from typing import Protocol

from opsmind.knowledge.corpus import (
    DEFAULT_CORPUS,
    CorpusValidationError,
    chunk_document,
    load_corpus,
)
from opsmind.knowledge.models import DocumentStatus, KnowledgeChunk, KnowledgeDocument


class KnowledgeRepository(Protocol):
    def list_active_documents(self) -> tuple[KnowledgeDocument, ...]: ...
    def get_document(self, document_id: str) -> KnowledgeDocument | None: ...
    def list_chunks(
        self, system_id: str | None = None
    ) -> tuple[KnowledgeChunk, ...]: ...


class LocalKnowledgeRepository:
    def __init__(self, root: Path = DEFAULT_CORPUS) -> None:
        self.manifest, self._documents = load_corpus(root)
        try:
            self._chunks = tuple(
                chunk
                for doc in self.list_active_documents()
                for chunk in chunk_document(doc)
            )
            ids = [chunk.chunk_id for chunk in self._chunks]
            if len(ids) != len(set(ids)):
                raise CorpusValidationError()
        except (CorpusValidationError, ValueError, TypeError, RecursionError):
            # Generated chunk identities and sections are also untrusted
            # consequences of manifest metadata. Keep malformed corpora on
            # the same safe error boundary as malformed source files.
            raise CorpusValidationError() from None

    def list_active_documents(self) -> tuple[KnowledgeDocument, ...]:
        return tuple(
            doc.model_copy(deep=True)
            for doc in self._documents
            if doc.status == DocumentStatus.ACTIVE
        )

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        return next(
            (
                doc
                for doc in self.list_active_documents()
                if doc.document_id == document_id
            ),
            None,
        )

    def list_chunks(self, system_id: str | None = None) -> tuple[KnowledgeChunk, ...]:
        return tuple(
            chunk.model_copy(deep=True)
            for chunk in self._chunks
            if system_id is None or chunk.system_id == system_id
        )
