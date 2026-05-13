import httpx
import json
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

# ── Query expansion only (kept for backward compat) ───────────────────────────
EXPANSION_PROMPT = """\
You are a search query expander for an event networking app.
Given a search query, return ONLY a space-separated list of related \
keywords: synonyms, related skills, job titles, and domain terms.
Output max 15 keywords. No explanations, no punctuation, no newlines.

Query: "{query}"
Keywords:"""

# ── Full query parser — extracts semantic query + hard filters ────────────────
PARSE_PROMPT = """\
You are a search query parser for an event attendee search system.
Extract two things from the user query and return ONLY valid JSON, nothing else.

1. "semantic_query": the core topic to search — remove experience/seniority words, \
keep skills, domains, roles. Also expand with 5-8 related synonyms and skills.

2. "filters": a JSON object with optional keys:
   - "experience_level": one of "junior" | "mid" | "senior" | "expert" — or omit if not mentioned
     Mapping rules:
       junior  → fresher, entry level, graduate, 0-2 years, 1 year, 2 years
       mid     → 3-5 years, intermediate, associate, 3 years, 4 years, 5 years or less
       senior  → 5-8 years, experienced, 6 years, 7 years, 8 years
       expert  → 10+ years, principal, staff, lead, veteran, distinguished
   - "organization": exact org name if mentioned — or omit

Return ONLY this JSON format, no markdown, no explanation:
{{"semantic_query": "...", "filters": {{}}}}

Examples:
Query: "AI engineers with 5 years or less experience"
{{"semantic_query": "AI engineers machine learning deep learning NLP data science", "filters": {{"experience_level": "mid"}}}}

Query: "senior NLP researchers"
{{"semantic_query": "NLP researchers natural language processing text mining computational linguistics", "filters": {{"experience_level": "senior"}}}}

Query: "founders working in agriculture"
{{"semantic_query": "founders entrepreneurs agriculture agritech farming startup food tech", "filters": {{}}}}

Query: "ML engineers at IIT Bombay"
{{"semantic_query": "machine learning engineers deep learning AI researchers", "filters": {{"organization": "IIT Bombay AI Lab"}}}}

Query: "junior data scientists"
{{"semantic_query": "data scientists analysts machine learning entry level", "filters": {{"experience_level": "junior"}}}}

Now parse this query:
Query: "{query}"
"""


async def _call_groq(prompt: str, max_tokens: int = 120) -> Optional[str]:
    """Shared Groq API call."""
    if not settings.groq_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.groq_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Groq call failed: {e}")
        return None


async def expand_query(query: str) -> Optional[str]:
    """Simple keyword expansion — kept for backward compat."""
    if not settings.groq_query_expansion:
        return None
    result = await _call_groq(EXPANSION_PROMPT.format(query=query), max_tokens=60)
    if result:
        return f"{query} {result}"
    return None


async def parse_query(query: str) -> dict:
    """
    Parse a natural language query into:
      - semantic_query: expanded query for vector search
      - filters: dict of hard filters to apply (experience_level, organization)

    Falls back to raw query with no filters if Groq is unavailable.
    """
    if not settings.groq_api_key or not settings.groq_query_expansion:
        return {"semantic_query": query, "filters": {}}

    raw = await _call_groq(PARSE_PROMPT.format(query=query), max_tokens=150)
    if not raw:
        return {"semantic_query": query, "filters": {}}

    try:
        # Strip markdown fences if model adds them
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)

        semantic = parsed.get("semantic_query", query).strip() or query
        filters = {
            k: v for k, v in parsed.get("filters", {}).items()
            if v and isinstance(v, str)
        }

        logger.info(f"Parsed '{query}' → semantic='{semantic[:60]}' filters={filters}")
        return {"semantic_query": semantic, "filters": filters}

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse Groq response '{raw}': {e}")
        return {"semantic_query": query, "filters": {}}