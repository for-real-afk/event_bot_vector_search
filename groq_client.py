import httpx
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

EXPANSION_PROMPT = """\
You are a search query expander for an event networking app.
Given a search query, return ONLY a space-separated list of related \
keywords: synonyms, related skills, job titles, and domain terms.
Output max 15 keywords. No explanations, no punctuation, no newlines.

Query: "{query}"
Keywords:"""


async def expand_query(query: str) -> Optional[str]:
    if not settings.groq_api_key or not settings.groq_query_expansion:
        return None

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                f"{settings.groq_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.groq_model,
                    "messages": [
                        {"role": "user", "content": EXPANSION_PROMPT.format(query=query)}
                    ],
                    "max_tokens": 60,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            expanded_terms = resp.json()["choices"][0]["message"]["content"].strip()
            return f"{query} {expanded_terms}"

    except Exception as e:
        logger.warning(f"Groq expansion failed ({e}) — using raw query")

    return None