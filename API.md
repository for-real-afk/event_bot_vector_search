# Event Attendee Search — API Reference

Base URL: `http://<host>:8001`

---

## GET /health

Health check.

**Response**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## GET /search

Semantic search over attendee profiles. Query is automatically expanded by LLM.

**Query Parameters**

| Param | Type | Required | Description |
|---|---|---|---|
| `q` | string | yes | Natural language search query |
| `limit` | int | no | Max results (1–50, default 10) |
| `experience_level` | string | no | Override filter: `junior` \| `mid` \| `senior` \| `expert` |
| `organization` | string | no | Override filter: exact org name |

**Example**
```
GET /search?q=people who work in plywood industry&limit=5
```

**Response**
```json
{
  "query": "people who work in plywood industry",
  "expanded_query": "plywood wood timber lumber panel building materials wholesale",
  "total": 3,
  "results": [
    {
      "id": "20",
      "full_name": "Apurv Malpani",
      "role": "Wood Merchants",
      "organization": "Malpani plywood traders",
      "experience_level": null,
      "detailed_profile": "plywood, veneers, laminates, doors...",
      "linkedin_url": "https://example.com",
      "score": 0.7689
    }
  ]
}
```

> `expanded_query` is `null` if the query was used as-is.
> `score` is cosine similarity (0.0–1.0). Only results above 0.55 are returned.
> Use the `id` from a result to call `GET /attendees/{id}` for full contact details.

---

## GET /attendees/{attendee_id}

Fetch full profile for a single attendee by ID. Returns contact details not included in search results.

**Path Parameter**

| Param | Type | Required | Description |
|---|---|---|---|
| `attendee_id` | string | yes | ID from a search result |

**Example**
```
GET /attendees/20
```

**Response**
```json
{
  "id": "20",
  "full_name": "Apurv Malpani",
  "email": "Mpt_09@rediffmail.com",
  "phone": "9885132911",
  "organization": "Malpani plywood traders",
  "role": "Wood Merchants",
  "experience_level": null,
  "detailed_profile": "plywood, veneers, laminates, doors, Wpvc, lockers...",
  "linkedin_url": "https://www.example.com"
}
```

> `linkedin_url` always includes `https://` prefix — safe to use as a redirect link.
> Returns `404` if the ID does not exist.

---

## POST /attendees

Index a single attendee.

**Request Body**
```json
{
  "id": "string",
  "full_name": "string",
  "email": "string",
  "phone": "string | null",
  "organization": "string",
  "role": "string",
  "experience_level": "junior | mid | senior | expert | null",
  "detailed_profile": "string | null",
  "linkedin_url": "string | null"
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique identifier (string) |
| `full_name` | yes | |
| `email` | yes | |
| `phone` | no | |
| `organization` | yes | Company or org name |
| `role` | yes | Job title or industry |
| `experience_level` | no | `junior` / `mid` / `senior` / `expert` |
| `detailed_profile` | no | Free-text bio — main semantic search signal |
| `linkedin_url` | no | LinkedIn or website URL |

**Response**
```json
{
  "indexed": 1,
  "id": "Apurv_Malpani"
}
```

---

## POST /attendees/bulk

Index multiple attendees in one request.

**Request Body**

Array of the same object as `POST /attendees`:
```json
[
  {
    "id": "string",
    "full_name": "string",
    "email": "string",
    "phone": "string | null",
    "organization": "string",
    "role": "string",
    "experience_level": "junior | mid | senior | expert | null",
    "detailed_profile": "string | null",
    "linkedin_url": "string | null"
  }
]
```

**Response**
```json
{
  "indexed": 49,
  "message": "49 attendee(s) indexed"
}
```

---

## DELETE /attendees/{attendee_id}

Remove a single attendee from the index.

**Path Parameter**

| Param | Type | Required | Description |
|---|---|---|---|
| `attendee_id` | string | yes | ID of the attendee to remove |

**Response**
```json
{
  "deleted": "20"
}
```

---

## DELETE /attendees

Wipe the entire index. Removes all vectors.

**Response**
```json
{
  "message": "Index wiped and recreated"
}
```

---

## Experience Level Mapping

| Value | Meaning |
|---|---|
| `junior` | 0–2 years, fresher, entry level |
| `mid` | 3–5 years, intermediate |
| `senior` | 5–8 years, experienced |
| `expert` | 10+ years, lead, principal, veteran |

---

## Interactive Docs

Full Swagger UI available at: `http://<host>:8001/docs`
OpenAPI JSON at: `http://<host>:8001/openapi.json`
