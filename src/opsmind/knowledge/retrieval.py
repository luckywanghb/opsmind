"""Deterministic lexical retrieval with scoped BM25 and stable tie breaking."""

import math
import re
import unicodedata
from collections import Counter
from typing import Protocol

from opsmind.knowledge.models import KnowledgeSearchMatch
from opsmind.knowledge.repository import KnowledgeRepository


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens = re.findall(r"[a-z0-9_]+", text)
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            tokens.append(run)
    return tokens


class KnowledgeSearchService(Protocol):
    def search(
        self, query: str, system_id: str | None = None
    ) -> KnowledgeSearchMatch | None: ...


class LexicalKnowledgeSearchService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def search(
        self, query: str, system_id: str | None = None
    ) -> KnowledgeSearchMatch | None:
        if not isinstance(query, str) or len(query) > 512:
            return None
        if system_id is not None and (
            not isinstance(system_id, str) or len(system_id) > 128
        ):
            return None
        terms = set(tokenize(query))
        chunks = self.repository.list_chunks(system_id)
        if not terms or not chunks:
            return None
        counts = [
            Counter(tokenize(f"{c.title} {c.section} {c.content}")) for c in chunks
        ]
        average = sum(sum(count.values()) for count in counts) / len(counts)
        frequencies = {term: sum(term in count for count in counts) for term in terms}
        matches = []
        for chunk, count in zip(chunks, counts, strict=True):
            score = 0.0
            for term in sorted(terms):
                frequency = count[term]
                if frequency:
                    idf = math.log(
                        1
                        + (len(chunks) - frequencies[term] + 0.5)
                        / (frequencies[term] + 0.5)
                    )
                    score += (
                        idf
                        * frequency
                        * 2.2
                        / (
                            frequency
                            + 1.2 * (0.25 + 0.75 * sum(count.values()) / average)
                        )
                    )
            # Require lexical support beyond an incidental single shared bigram.
            overlap = len(terms & count.keys())
            if score > 0 and (overlap >= 2 or len(terms) == 1):
                matches.append(KnowledgeSearchMatch(chunk=chunk, score=score))
        return min(
            matches,
            key=lambda m: (-m.score, m.chunk.document_id, m.chunk.chunk_id),
            default=None,
        )
