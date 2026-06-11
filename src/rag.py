"""Deterministic hybrid retrieval with RRF and an optional Qdrant adapter."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from src.config import Settings
from src.schemas import Citation


@dataclass(frozen=True)
class SyntheticDocument:
    document_id: str
    title: str
    text: str
    tags: tuple[str, ...]


SYNTHETIC_DOCUMENTS = (
    SyntheticDocument(
        document_id="broadband-rf-001",
        title="Synthetic DOCSIS RF Health Guide",
        text=(
            "Healthy downstream power is generally between -10 and +10 dBmV. "
            "SNR below 30 dB or rapidly increasing uncorrectable codewords may indicate "
            "an RF impairment. Inspect connectors and escalate persistent RF faults."
        ),
        tags=(
            "slow",
            "drops",
            "intermittent",
            "buffering",
            "streaming",
            "rf",
            "snr",
            "codewords",
            "ranging",
        ),
    ),
    SyntheticDocument(
        document_id="broadband-reset-002",
        title="Synthetic Modem Reset Procedure",
        text=(
            "A remote reset may be attempted for an online or degraded modem after customer "
            "consent. Re-read telemetry after the reset. Do not claim resolution unless the "
            "post-reset snapshot returns to healthy thresholds."
        ),
        tags=("reset", "slow", "degraded", "consent"),
    ),
    SyntheticDocument(
        document_id="broadband-offline-003",
        title="Synthetic Offline Modem Playbook",
        text=(
            "A modem that has not checked in for several minutes should be treated as offline. "
            "Confirm power and coax connections. If remote telemetry remains unavailable, "
            "escalate for line or premise investigation rather than reporting a remote fix."
        ),
        tags=("offline", "no internet", "connection", "escalate"),
    ),
    SyntheticDocument(
        document_id="broadband-healthy-004",
        title="Synthetic Healthy Telemetry Reference",
        text=(
            "Healthy telemetry with normal power, SNR above 35 dB, and no uncorrectable "
            "codewords does not establish an RF fault. Continue symptom isolation before "
            "dispatching or changing network settings."
        ),
        tags=("healthy", "online", "normal"),
    ),
    SyntheticDocument(
        document_id="broadband-error-005",
        title="Synthetic Modem Error Code Reference",
        text=(
            "Synthetic error code RDK-BB-104 indicates repeated upstream ranging timeouts. "
            "Collect RF telemetry, inspect upstream power, and escalate if the code persists."
        ),
        tags=("rdk-bb-104", "error", "code", "ranging", "timeout", "upstream"),
    ),
    SyntheticDocument(
        document_id="broadband-firmware-006",
        title="Synthetic Firmware Compatibility Guide",
        text=(
            "Synthetic firmware version FW-7.4.2 resolves a lab-only modem stability issue. "
            "Verify the reported version before recommending a controlled firmware review."
        ),
        tags=("fw-7.4.2", "firmware", "version", "stability", "upgrade"),
    ),
)


class Retriever(Protocol):
    def search(self, query: str, *, limit: int) -> list[Citation]:
        """Return ranked support passages."""


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _token_list(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


SEMANTIC_CONCEPTS = {
    "buffering": {"buffer", "buffering", "streaming", "slow", "latency"},
    "offline": {"offline", "unavailable", "disconnected", "connection"},
    "firmware": {"firmware", "version", "upgrade", "software"},
    "rf": {"rf", "signal", "snr", "power", "ranging", "codewords"},
    "healthy": {"healthy", "normal", "online", "stable"},
}


class LocalSyntheticRetriever:
    """Hybrid lexical and semantic retriever with reciprocal rank fusion."""

    def __init__(self, documents: tuple[SyntheticDocument, ...] = SYNTHETIC_DOCUMENTS):
        self._documents = documents

    def search(self, query: str, *, limit: int) -> list[Citation]:
        lexical = self._lexical_rank(query)
        semantic = self._semantic_rank(query)
        lexical_positions = {
            document.document_id: rank
            for rank, (_, document) in enumerate(lexical, 1)
        }
        semantic_positions = {
            document.document_id: rank for rank, (_, document) in enumerate(semantic, 1)
        }
        query_tokens = _tokens(query)
        fused: list[tuple[float, float, SyntheticDocument, int, int]] = []

        for document in self._documents:
            lexical_rank = lexical_positions[document.document_id]
            semantic_rank = semantic_positions[document.document_id]
            rrf_score = (1 / (60 + lexical_rank)) + (1 / (60 + semantic_rank))
            document_tokens = _tokens(
                f"{document.title} {document.text} {' '.join(document.tags)}"
            )
            exact_coverage = len(query_tokens & document_tokens) / max(len(query_tokens), 1)
            phrase_bonus = 0.2 if any(tag in query.lower() for tag in document.tags) else 0.0
            rerank_score = min(1.0, (rrf_score * 15) + exact_coverage + phrase_bonus)
            fused.append(
                (
                    rerank_score,
                    rrf_score,
                    document,
                    len(query_tokens & document_tokens),
                    self._semantic_hits(query_tokens, document_tokens),
                )
            )

        fused.sort(key=lambda item: (item[0], item[1], item[2].document_id), reverse=True)
        citations: list[Citation] = []
        for fused_rank, (rerank, rrf_score, document, lexical_hits, semantic_hits) in enumerate(
            fused[:limit],
            1,
        ):
            citations.append(
                Citation(
                    document_id=document.document_id,
                    title=document.title,
                    excerpt=document.text,
                    score=min(1.0, round(rrf_score * 30, 3)),
                    lexical_hits=lexical_hits,
                    semantic_hits=semantic_hits,
                    fused_rank=fused_rank,
                    rerank_score=round(rerank, 3),
                )
            )
        return citations

    def _lexical_rank(self, query: str) -> list[tuple[float, SyntheticDocument]]:
        query_terms = _token_list(query)
        document_terms = [
            _token_list(f"{document.title} {document.text} {' '.join(document.tags)}")
            for document in self._documents
        ]
        average_length = sum(map(len, document_terms)) / len(document_terms)
        document_frequency = Counter(
            term for terms in document_terms for term in set(terms)
        )
        ranked: list[tuple[float, SyntheticDocument]] = []
        for document, terms in zip(self._documents, document_terms, strict=True):
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if frequency == 0:
                    continue
                inverse_frequency = math.log(
                    1 + (len(self._documents) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                denominator = frequency + 1.5 * (
                    0.25 + 0.75 * len(terms) / average_length
                )
                score += inverse_frequency * (frequency * 2.5) / denominator
            ranked.append((score, document))
        return sorted(ranked, key=lambda item: (item[0], item[1].document_id), reverse=True)

    def _semantic_rank(self, query: str) -> list[tuple[float, SyntheticDocument]]:
        query_tokens = _tokens(query)
        ranked = []
        for document in self._documents:
            document_tokens = _tokens(
                f"{document.title} {document.text} {' '.join(document.tags)}"
            )
            hits = self._semantic_hits(query_tokens, document_tokens)
            ranked.append((float(hits), document))
        return sorted(ranked, key=lambda item: (item[0], item[1].document_id), reverse=True)

    @staticmethod
    def _semantic_hits(query_tokens: set[str], document_tokens: set[str]) -> int:
        hits = len(query_tokens & document_tokens)
        for concept_terms in SEMANTIC_CONCEPTS.values():
            if query_tokens & concept_terms and document_tokens & concept_terms:
                hits += 1
        return hits


class QdrantRetriever:
    """Adapter for a Qdrant collection populated with synthetic manual payloads.

    This demo uses Qdrant's text search interface when configured. Local retrieval
    remains the default so no database or embedding service is required.
    """

    def __init__(self, settings: Settings):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "Qdrant mode requires qdrant-client. Install the project dependencies first."
            ) from exc

        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )
        self._collection = settings.qdrant_collection

    def search(self, query: str, *, limit: int) -> list[Citation]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        # Payload filtering keeps the adapter restricted to synthetic demo content.
        points, _ = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="tags",
                        match=MatchAny(any=list(_tokens(query))),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        citations: list[Citation] = []
        for point in points:
            payload = point.payload or {}
            citations.append(
                Citation(
                    document_id=str(payload.get("document_id", point.id)),
                    title=str(payload.get("title", "Synthetic broadband manual")),
                    excerpt=str(payload.get("text", "")),
                    score=1.0,
                )
            )
        return citations


def build_retriever(settings: Settings) -> Retriever:
    if settings.rag_backend == "qdrant":
        return QdrantRetriever(settings)
    return LocalSyntheticRetriever()
