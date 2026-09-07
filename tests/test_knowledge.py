"""Developer boundary tests for provider-free knowledge retrieval."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opsmind.knowledge.corpus import (
    CorpusValidationError,
    chunk_document,
    clean_content,
)
from opsmind.knowledge.models import KnowledgeDocument
from opsmind.knowledge.repository import LocalKnowledgeRepository
from opsmind.knowledge.retrieval import LexicalKnowledgeSearchService
from opsmind.knowledge.tool import KnowledgeSearchRequest, KnowledgeSearchResponse


def corpus(tmp_path: Path, content: str, **metadata: object) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = dict(
        document_id="TEST",
        title="测试手册",
        system_id="TestSystem",
        document_type="SOP",
        version="1",
        updated_at="2026-09-07",
        status="ACTIVE",
        source_file="source.md",
        tags=[],
    )
    source.update(metadata)
    (tmp_path / "source.md").write_text(content)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            dict(
                schema_version=1,
                corpus_id="test",
                corpus_version="1",
                documents=[source],
            )
        )
    )
    return tmp_path


@pytest.mark.parametrize("query,expected", [
    ("故障工单应该怎么关闭？", "K001"), ("关闭故障工单前的验收要求", "K001"),
    ("设备台账怎么导出？", "K002"), ("设备台账权限怎么申请？", "K003"),
    ("Quality inspection report export", "K004"), ("EF-WO-CLOSE", "K001"),
    ("EQUIPMENT_LEDGER_EXPORT", "K002"), ("equipment_ledger_export", "K002"),
    ("ＥＱＵＩＰＭＥＮＴ＿ＬＥＤＧＥＲ＿ＥＸＰＯＲＴ", "K002"),
    ("故障，工单；关闭！", "K001"),
])
def test_generic_retrieval(query: str, expected: str) -> None:
    search = LexicalKnowledgeSearchService(LocalKnowledgeRepository())
    match = search.search(query)
    assert match is not None and match.chunk.document_id == expected
    assert search.search(query) == match


def test_scope_no_match_and_retired(tmp_path: Path) -> None:
    search = LexicalKnowledgeSearchService(LocalKnowledgeRepository())
    assert search.search("quantumphotosynthesis") is None
    assert search.search("设备台账导出", "unknown") is None
    match = search.search("报告导出", "QualityHub")
    assert match is not None and match.chunk.system_id == "QualityHub"
    retired = LexicalKnowledgeSearchService(
        LocalKnowledgeRepository(corpus(tmp_path, "needle needle", status="RETIRED"))
    )
    assert retired.search("needle") is None


def test_clean_chunk_overlap_stability(tmp_path: Path) -> None:
    assert clean_content("  Ａ\r\n\r\n\r\nＢ  \r\n") == "A\n\nB"
    content = "# 开头\n" + "确认验收事项。" * 350
    repo = LocalKnowledgeRepository(corpus(tmp_path, content))
    chunks = repo.list_chunks()
    assert chunks == LocalKnowledgeRepository(tmp_path).list_chunks()
    assert all(0 < len(c.content) <= 1000 for c in chunks)
    assert chunks[0].content[-200:] == chunks[1].content[:200]
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert "注意事项" in clean_content("注意事项\n不得关闭")


@pytest.mark.parametrize("change", [
    {"document_id": "x" * 129}, {"title": " "}, {"title": "x" * 257},
    {"status": "BROKEN"}, {"source_file": "../outside.md"},
    {"source_file": "/private/internal/knowledge/source.md"},
    {"source_file": "missing.md"}, {"updated_at": "2026-99-99"},
])
def test_invalid_corpus_safe_error(tmp_path: Path, change: dict) -> None:
    with pytest.raises(CorpusValidationError, match="^KNOWLEDGE_CORPUS_INVALID$"):
        LocalKnowledgeRepository(corpus(tmp_path, "valid", **change))


def test_generated_chunk_metadata_bounds_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(CorpusValidationError, match="^KNOWLEDGE_CORPUS_INVALID$"):
        LocalKnowledgeRepository(
            corpus(tmp_path, "valid", document_id="x" * 128, version="y" * 128)
        )


@pytest.mark.parametrize("content", ["", "   \n", "bad\x00content"])
def test_empty_invalid_content(tmp_path: Path, content: str) -> None:
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(corpus(tmp_path, content))


def test_invalid_utf8_duplicate_and_schema(tmp_path: Path) -> None:
    root = corpus(tmp_path, "valid")
    (root / "source.md").write_bytes(b"\xff")
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(root)
    (root / "source.md").write_text("valid")
    path = root / "manifest.json"
    data = json.loads(path.read_text())
    data["documents"] *= 2
    path.write_text(json.dumps(data))
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(root)
    data["documents"] = data["documents"][:1]
    data["schema_version"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(root)


def test_tie_break_and_symlink_escape(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus", "needle")
    data = json.loads((root / "manifest.json").read_text())
    other = dict(data["documents"][0], document_id="AAA")
    data["documents"].append(other)
    (root / "manifest.json").write_text(json.dumps(data))
    search = LexicalKnowledgeSearchService(LocalKnowledgeRepository(root))
    assert search.search("needle").chunk.document_id == "AAA"
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (root / "source.md").unlink()
    (root / "source.md").symlink_to(outside)
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(root)


@pytest.mark.parametrize("query", ["", " ", "x" * 513])
def test_request_bounds(query: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeSearchRequest(query=query)


def test_response_status_contract() -> None:
    with pytest.raises(ValidationError):
        KnowledgeSearchResponse(result_status="found")
    with pytest.raises(ValidationError):
        KnowledgeSearchResponse(result_status="not_found", document_id="K001")
    assert KnowledgeSearchResponse(result_status="not_found").excerpt is None


def test_chunk_identity_for_long_version() -> None:
    doc = KnowledgeDocument(
        document_id="K",
        title="Title",
        system_id="System",
        document_type="SOP",
        version="1",
        updated_at="2026-09-07",
        status="ACTIVE",
        content="needle",
    )
    assert chunk_document(doc)[0].chunk_id == chunk_document(doc)[0].chunk_id
