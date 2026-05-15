import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import AttendeeCreate, AttendeeProfile, AttendeeResult, SearchResponse, BulkUpsertResponse
from app.search_engine import SearchEngine
from app.groq_client import parse_query

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

engine: SearchEngine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    logger.info("Starting Event Search Service…")
    engine = SearchEngine()
    logger.info("Ready — vector search active.")
    yield
    logger.info("Shutdown.")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Semantic vector search over event attendee profiles.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "version": settings.api_version}


# ── Indexing ───────────────────────────────────────────────────────────────────

@app.post("/attendees", status_code=201, tags=["indexing"])
def add_attendee(attendee: AttendeeCreate):
    engine.upsert(attendee)
    return {"indexed": 1, "id": attendee.id}


@app.post("/attendees/bulk", response_model=BulkUpsertResponse, status_code=201, tags=["indexing"])
def bulk_add(attendees: List[AttendeeCreate]):
    count = engine.upsert_bulk(attendees)
    return BulkUpsertResponse(indexed=count, message=f"{count} attendee(s) indexed")


def _normalize_url(url: str | None) -> str | None:
    """Ensure URL has a scheme so it is a valid clickable link."""
    if not url:
        return None
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


@app.get("/attendees/{attendee_id}", response_model=AttendeeProfile, tags=["search"])
def get_attendee(attendee_id: str):
    """
    Fetch full profile for a single attendee by ID.
    Called when a user clicks a search result to view complete contact details.
    Reads directly from Pinecone metadata — no separate database needed.
    """
    result = engine.index.fetch(ids=[attendee_id])
    vectors = result.get("vectors", {})
    if attendee_id not in vectors:
        raise HTTPException(status_code=404, detail="Attendee not found.")
    meta = vectors[attendee_id].get("metadata", {})
    return AttendeeProfile(
        id=meta.get("_original_id", attendee_id),
        full_name=meta.get("full_name", ""),
        email=meta.get("email"),
        phone=meta.get("phone"),
        organization=meta.get("organization", ""),
        role=meta.get("role", ""),
        experience_level=meta.get("experience_level"),
        detailed_profile=meta.get("detailed_profile"),
        linkedin_url=_normalize_url(meta.get("linkedin_url")),
    )


@app.delete("/attendees/{attendee_id}", tags=["indexing"])
def remove_attendee(attendee_id: str):
    engine.delete(attendee_id)
    return {"deleted": attendee_id}


@app.delete("/attendees", tags=["indexing"])
def wipe_index():
    engine.delete_all()
    return {"message": "Index wiped and recreated"}


# ── Search ─────────────────────────────────────────────────────────────────────

@app.get("/search", response_model=SearchResponse, tags=["search"])
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    limit: int = Query(10, ge=1, le=50),
    # Manual overrides — these take priority over LLM-extracted filters
    experience_level: Optional[str] = Query(None, description="Override: junior | mid | senior | expert"),
    organization: Optional[str] = Query(None, description="Override: exact org name"),
):
    """
    Semantic search with automatic query understanding.

    The query is parsed by an LLM (Groq) which:
    1. Extracts experience level  — "5 years experience" → mid filter
    2. Extracts organization      — "people at IIT Bombay" → org filter
    3. Expands the semantic query — "ML" → "machine learning deep learning NLP PyTorch"

    Manual filter params override LLM-extracted ones if both are provided.

    Example queries:
    - ai engineers with less than 5 years experience
    - senior NLP researchers
    - founders working in agriculture
    - junior data scientists at IIT Bombay
    """
    # Step 1: Parse query with LLM
    parsed = await parse_query(q)
    semantic_query = parsed["semantic_query"]
    extracted_filters = parsed["filters"]

    # Step 2: Manual params override LLM-extracted filters
    if experience_level:
        extracted_filters["experience_level"] = experience_level
    if organization:
        extracted_filters["organization"] = organization

    # Step 3: Vector search
    results = engine.search(
        query=semantic_query,
        limit=limit,
        filters=extracted_filters or None,
    )

    return SearchResponse(
        query=q,
        expanded_query=semantic_query if semantic_query != q else None,
        total=len(results),
        results=results,
    )