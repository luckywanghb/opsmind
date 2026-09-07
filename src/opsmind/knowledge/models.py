"""Bounded, provider-neutral knowledge domain records."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator

from opsmind.state import StateModel

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w.-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=256)]


def validate_updated_at(value: str) -> str:
    """Accept a bounded ISO date or datetime without exposing source details."""

    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            # Normalize the standard UTC suffix for Python 3.11.
            datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("updated_at must be an ISO date or datetime") from exc
    return value


class DocumentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class KnowledgeMetadata(StateModel):
    document_id: Identifier
    title: Text
    system_id: Identifier
    document_type: Text
    version: Identifier
    updated_at: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("updated_at")
    @classmethod
    def valid_date(cls, value: str) -> str:
        return validate_updated_at(value)

    @field_validator("title", "document_type")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("invalid knowledge metadata")
        return value


class KnowledgeSource(KnowledgeMetadata):
    status: DocumentStatus
    source_file: Annotated[str, Field(min_length=1, max_length=256)]
    tags: list[Text] = Field(max_length=32)

    @field_validator("source_file")
    @classmethod
    def valid_source_file(cls, value: str) -> str:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("invalid knowledge source file")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("knowledge tags must not be blank")
        return value


class KnowledgeManifest(StateModel):
    schema_version: Literal[1]
    corpus_id: Identifier
    corpus_version: Identifier
    documents: list[KnowledgeSource] = Field(min_length=1, max_length=1000)


class KnowledgeDocument(KnowledgeMetadata):
    status: DocumentStatus
    content: str = Field(min_length=1, max_length=1_000_000)


class KnowledgeChunk(KnowledgeMetadata):
    chunk_id: Identifier
    section: Text
    content: str = Field(min_length=1, max_length=1200)


class KnowledgeSearchMatch(StateModel):
    chunk: KnowledgeChunk
    score: float = Field(gt=0, allow_inf_nan=False)
