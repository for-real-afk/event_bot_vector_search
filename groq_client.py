import base64
import httpx
import json
import logging
from typing import Optional
from app.config import settings


def _build_auth_header(api_key: str) -> str:
    # "user:pass" format → Basic auth (nginx-proxied Ollama)
    # plain token → Bearer auth (Groq / raw Ollama)
    if ":" in api_key:
        encoded = base64.b64encode(api_key.encode()).decode()
        return f"Basic {encoded}"
    return f"Bearer {api_key}"

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
You are a search assistant for a professional directory of event attendees.
Given a natural language query, produce a compact keyword-rich search phrase \
that would retrieve the most relevant professional profiles from a semantic vector database.

Rules:
- Strip conversational filler ("people who", "find me", "show me", "I want", "give me").
- Preserve the full intent of the query — domain, role, industry, activity, specialty.
- Expand with synonyms, related job titles, and adjacent terms a professional profile \
  would actually contain. Stay on-topic; do not drift into unrelated fields.
- 6-10 words total.

Also extract optional hard filters:
- "experience_level": "junior" | "mid" | "senior" | "expert" — only if explicitly mentioned
    junior = 0-2 yrs / fresher; mid = 3-5 yrs; senior = 5-8 yrs; expert = 10+ yrs / lead
- "organization": exact company name — only if explicitly mentioned

Return ONLY valid JSON, no markdown, no explanation:
{{"semantic_query": "...", "filters": {{}}}}

Example:
Query: "senior data scientists at Google"
{{"semantic_query": "data scientist machine learning analytics Python statistics", "filters": {{"experience_level": "senior", "organization": "Google"}}}}

Now parse this query:
Query: "{query}"
"""


async def _call_groq(prompt: str, max_tokens: int = 150) -> Optional[str]:
    """Shared LLM API call — supports Groq, OpenAI-compat, and native Ollama."""
    if not settings.groq_api_key:
        return None
    headers = {
        "Authorization": _build_auth_header(settings.groq_api_key),
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers=headers,
                json={
                    "model": settings.groq_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
            )
            if resp.status_code == 404:
                # Proxy blocks /v1/chat/completions → fall back to native Ollama /api/chat
                base = settings.groq_base_url.rstrip("/").removesuffix("/v1")
                resp = await client.post(
                    f"{base}/api/chat",
                    headers=headers,
                    json={
                        "model": settings.groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": max_tokens},
                    },
                )
                resp.raise_for_status()
                # Ollama may return newline-delimited JSON chunks even with stream=false
                decoder = json.JSONDecoder()
                text = resp.text.strip()
                parts, pos = [], 0
                while pos < len(text):
                    try:
                        chunk, end = decoder.raw_decode(text, pos)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            parts.append(token)
                        pos = end
                        while pos < len(text) and text[pos] in " \t\n\r":
                            pos += 1
                    except json.JSONDecodeError:
                        break
                return "".join(parts).strip() or None
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
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
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        # raw_decode stops at end of first valid JSON object, ignoring extra text
        parsed, _ = json.JSONDecoder().raw_decode(cleaned)

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