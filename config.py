from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── Pinecone ──────────────────────────────────────────────────────
    pinecone_api_key: str
    pinecone_index: str = "attendees"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"     # free tier default region

    # ── Embedding model (fastembed, runs locally — no API key needed) ─
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    vector_size: int = 384
    score_threshold: float = 0.25          # drop results below this cosine sim

    # ── Groq — query expansion only (not embeddings) ──────────────────
    groq_api_key: Optional[str] = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"
    groq_query_expansion: bool = True

    # ── App ───────────────────────────────────────────────────────────
    api_title: str = "Event Attendee Search"
    api_version: str = "1.0.0"
    debug: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
