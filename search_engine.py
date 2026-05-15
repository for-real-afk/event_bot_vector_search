import re
import time
import logging
from typing import Optional, List, Dict, Any

from pinecone import Pinecone, ServerlessSpec
from fastembed import TextEmbedding

from config import settings
from models import AttendeeCreate, AttendeeResult

logger = logging.getLogger(__name__)


def _strip_noise(text: str) -> str:
    """Remove emoji, non-ASCII symbols, and collapse whitespace."""
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s.,&@()\-/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_embed_text(a: AttendeeCreate) -> str:
    parts = [
        a.role,
        a.organization,
        (a.experience_level.value if a.experience_level else ""),
        a.detailed_profile or "",
    ]
    raw = " ".join(p for p in parts if p).strip()
    return _strip_noise(raw)


def _clean_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {}
    for k, v in payload.items():
        if v is None:
            continue
        if isinstance(v, list):
            cleaned[k] = [str(i) for i in v if i is not None]
        elif isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        else:
            cleaned[k] = str(v)
    return cleaned


class SearchEngine:
    def __init__(self):
        pc = Pinecone(api_key=settings.pinecone_api_key)
        self._ensure_index(pc)
        self.index = pc.Index(settings.pinecone_index)

        logger.info(f"Loading embedding model: {settings.embedding_model}")
        self.embedder = TextEmbedding(model_name=settings.embedding_model)
        logger.info("Search engine ready — Pinecone + fastembed")

    def _ensure_index(self, pc: Pinecone):
        existing = {idx.name for idx in pc.list_indexes()}
        if settings.pinecone_index in existing:
            logger.info(f"Pinecone index '{settings.pinecone_index}' ready")
            return

        logger.info(f"Creating Pinecone index '{settings.pinecone_index}'...")
        pc.create_index(
            name=settings.pinecone_index,
            dimension=settings.vector_size,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.pinecone_cloud,
                region=settings.pinecone_region,
            ),
        )
        self._wait_for_index(pc)

    def _wait_for_index(self, pc: Pinecone, timeout: int = 60):
        start = time.time()
        while time.time() - start < timeout:
            status = pc.describe_index(settings.pinecone_index).status
            if status.get("ready"):
                return
            logger.info("Waiting for index to be ready...")
            time.sleep(2)
        raise TimeoutError("Pinecone index did not become ready in time")

    def _embed_one(self, text: str) -> List[float]:
        return list(self.embedder.embed([text]))[0].tolist()

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [v.tolist() for v in self.embedder.embed(texts)]

    def upsert(self, attendee: AttendeeCreate) -> None:
        text = _build_embed_text(attendee)
        if not text:
            return
        metadata = _clean_metadata(
            {**attendee.model_dump(mode="json"), "_original_id": attendee.id}
        )
        self.index.upsert(vectors=[{
            "id": attendee.id,
            "values": self._embed_one(text),
            "metadata": metadata,
        }])
        logger.debug(f"Upserted {attendee.id} — {attendee.full_name}")

    def upsert_bulk(self, attendees: List[AttendeeCreate]) -> int:
        pairs = [(a, _build_embed_text(a)) for a in attendees]
        pairs = [(a, t) for a, t in pairs if t]   # skip empty profiles
        if not pairs:
            return 0
        attendees_filtered, texts = zip(*pairs)
        vectors = self._embed_batch(list(texts))

        batch_size = 100
        records = [
            {
                "id": a.id,
                "values": v,
                "metadata": _clean_metadata(
                    {**a.model_dump(mode="json"), "_original_id": a.id}
                ),
            }
            for a, v in zip(attendees_filtered, vectors)
        ]
        for i in range(0, len(records), batch_size):
            self.index.upsert(vectors=records[i: i + batch_size])

        logger.info(f"Bulk upserted {len(records)} attendees")
        return len(records)

    def delete(self, attendee_id: str) -> None:
        self.index.delete(ids=[attendee_id])

    def delete_all(self) -> None:
        self.index.delete(delete_all=True)
        logger.info("All vectors deleted from index")

    def search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, str]] = None,
    ) -> List[AttendeeResult]:
        query_vector = self._embed_one(query)

        pinecone_filter = None
        if filters:
            pinecone_filter = {k: {"$eq": v} for k, v in filters.items() if v}

        response = self.index.query(
            vector=query_vector,
            top_k=limit,
            include_metadata=True,
            filter=pinecone_filter,
        )

        results = [
            AttendeeResult(
                id=m["metadata"].get("_original_id", m["id"]),
                full_name=m["metadata"].get("full_name", ""),
                role=m["metadata"].get("role", ""),
                organization=m["metadata"].get("organization", ""),
                experience_level=m["metadata"].get("experience_level"),
                detailed_profile=m["metadata"].get("detailed_profile"),
                linkedin_url=m["metadata"].get("linkedin_url"),
                score=round(min(m["score"], 1.0), 4),
            )
            for m in response["matches"]
            if m["score"] >= settings.score_threshold
        ]
        return sorted(results, key=lambda r: r.score, reverse=True)

    def reindex_by_ids(self, ids: List[str]) -> int:
        """Re-embed specific vectors using their existing Pinecone metadata."""
        fetch_result = self.index.fetch(ids=ids)
        vectors = fetch_result.get("vectors", {})
        batch = []
        for vid, vdata in vectors.items():
            meta = vdata.get("metadata", {})
            # Reconstruct an AttendeeCreate-compatible dict for text building
            role = meta.get("role", "")
            org  = meta.get("organization", "")
            prof = meta.get("detailed_profile", "")
            text = _strip_noise(" ".join(p for p in [role, org, prof] if p).strip())
            if not text:
                continue
            batch.append({"id": vid, "values": self._embed_one(text), "metadata": meta})
        if batch:
            self.index.upsert(vectors=batch)
        logger.info(f"Reindexed {len(batch)} vectors")
        return len(batch)