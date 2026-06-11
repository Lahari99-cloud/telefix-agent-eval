"""Hybrid lexical, semantic, RRF, and reranking regression tests."""

from src.rag import LocalSyntheticRetriever


def test_exact_error_code_query_prefers_error_reference() -> None:
    results = LocalSyntheticRetriever().search(
        "What does synthetic error RDK-BB-104 mean?",
        limit=3,
    )

    assert results[0].document_id == "broadband-error-005"
    assert results[0].lexical_hits >= 3
    assert results[0].fused_rank == 1


def test_natural_language_buffering_query_finds_rf_guidance() -> None:
    results = LocalSyntheticRetriever().search(
        "Movies keep pausing while streaming in the evening",
        limit=3,
    )

    assert any(result.document_id == "broadband-rf-001" for result in results[:2])
    assert results[0].semantic_hits > 0
    assert results[0].rerank_score > 0


def test_firmware_version_query_prefers_compatibility_guide() -> None:
    results = LocalSyntheticRetriever().search(
        "Is modem firmware FW-7.4.2 the expected version?",
        limit=3,
    )

    assert results[0].document_id == "broadband-firmware-006"
    assert results[0].lexical_hits > 0
    assert results[0].rerank_score >= results[1].rerank_score
