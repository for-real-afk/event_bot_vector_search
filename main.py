import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import AttendeeCreate, SearchResponse, BulkUpsertResponse
from app.search_engine import SearchEngine
from app.groq_client import expand_query

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
    engine = SearchEngine()   # loads embedding model + ensures Qdrant collection
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
    allow_origins=["*"],    # tighten per-domain in prod
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "version": settings.api_version}


# ── Indexing (called by your main backend) ─────────────────────────────

@app.post("/attendees", status_code=201, tags=["indexing"])
def add_attendee(attendee: AttendeeCreate):
    """
    Index a single attendee. Call this from your main backend
    on new registration or profile update.
    """
    engine.upsert(attendee)
    return {"indexed": 1, "id": attendee.id}


@app.post("/attendees/bulk", response_model=BulkUpsertResponse, status_code=201, tags=["indexing"])
def bulk_add(attendees: List[AttendeeCreate]):
    """
    Bulk import — use this to seed from your DB at event setup.
    fastembed batches all embeddings in one forward pass, so this is
    much faster than calling /attendees in a loop.
    """
    count = engine.upsert_bulk(attendees)
    return BulkUpsertResponse(indexed=count, message=f"{count} attendee(s) indexed")


@app.delete("/attendees/{attendee_id}", tags=["indexing"])
def remove_attendee(attendee_id: str):
    engine.delete(attendee_id)
    return {"deleted": attendee_id}


@app.delete("/attendees", tags=["indexing"])
def wipe_index():
    """Wipe and recreate the collection. Use when re-seeding for a new event."""
    engine.delete_all()
    return {"message": "Index wiped and recreated"}


# ── Search (called by your frontend / event bot) ───────────────────────

@app.get("/search", response_model=SearchResponse, tags=["search"])
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    limit: int = Query(10, ge=1, le=50),
    # Hard filters — applied before vector scoring
    experience_level: Optional[str] = Query(
        None, description="junior | mid | senior | expert"
    ),
    organization: Optional[str] = Query(
        None, description="Exact org name filter"
    ),
):
    """
    Semantic vector search over attendee profiles.

    How it works:
    1. (Optional) Groq expands your query with synonyms
    2. The query is embedded using BAAI/bge-small-en-v1.5
    3. Qdrant finds the closest attendee vectors by cosine similarity
    4. Results with score < 0.25 are filtered out automatically

    Example queries:
    - /search?q=machine learning healthcare
    - /search?q=founders in agriculture&experience_level=senior
    - /search?q=open source developer looking to collaborate
    - /search?q=investor interested in deep tech
    """
    # Step 1: Groq query expansion (gracefully skipped if key not set)
    expanded = await expand_query(q)
    search_query = expanded or q

    # Step 2: Build hard pre-filters
    filters = {}
    if experience_level:
        filters["experience_level"] = experience_level
    if organization:
        filters["organization"] = organization

    # Step 3: Vector search
    results = engine.search(
        query=search_query,
        limit=limit,
        filters=filters or None,
    )

    return SearchResponse(
        query=q,
        expanded_query=expanded,
        total=len(results),
        results=results,
    )
