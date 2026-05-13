# Event Attendee Search Service

A standalone semantic search microservice for event networking platforms. Attendees describe themselves in plain text — the service makes them discoverable through natural language queries like *"ML engineers in healthcare"* or *"founders working in agriculture with less than 5 years experience"*.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Query Examples](#query-examples)
- [Deployment](#deployment)
- [GitHub Actions CI/CD](#github-actions-cicd)
- [Frontend Integration](#frontend-integration)
- [Calling from Your Main Backend](#calling-from-your-main-backend)

---

## How It Works

The service runs two pipelines — one for indexing attendees, one for searching them.

### Indexing Pipeline (runs on registration)

```
Attendee fills registration form
         ↓
POST /attendees  (called by your main backend)
         ↓
Build embed text: role + organization + experience + detailed_profile
         ↓
fastembed (BAAI/bge-small-en-v1.5) converts text → 384-dim vector
         ↓
Upsert vector + full profile metadata into Pinecone
```

### Search Pipeline (runs on every query)

```
User types: "AI engineers with less than 5 years experience"
         ↓
Groq LLM parses the query in one call:
  semantic_query → "AI engineers machine learning deep learning NLP"
  filters        → {"experience_level": "mid"}
         ↓
semantic_query → fastembed → 384-dim query vector
         ↓
Pinecone ANN search: top-K by cosine similarity + experience_level=mid pre-filter
         ↓
Sort by score, drop results below 0.25 threshold
         ↓
Return ranked attendee list with scores
```

### Why This Approach

**Vector search** finds semantic matches — a query for *"ML"* finds profiles mentioning *"PyTorch, transformers, deep learning"* even without the exact word ML. Traditional keyword search misses this.

**LLM query parsing** handles intent — *"less than 5 years"* becomes a hard `experience_level=mid` filter rather than polluting the semantic query. The frontend doesn't need to send structured params — plain English works.

**fastembed runs locally** — no external API call for embeddings. The model (~130 MB ONNX) downloads once and runs on CPU. Zero embedding cost, fast inference.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         EC2 Instance                             │
│                                                                  │
│  ┌──────────────┐    ┌────────────────────────────────────────┐  │
│  │ Main Backend │    │   Event Search Service  (port 8003)   │  │
│  │  (any port)  │───►│                                        │  │
│  │              │    │   FastAPI + uvicorn + systemd          │  │
│  │ on register  │    │                                        │  │
│  │ → POST /att. │    │  ┌─────────────┐  ┌────────────────┐  │  │
│  └──────────────┘    │  │  Groq API   │  │   fastembed    │  │  │
│                      │  │ (LLM query  │  │  bge-small     │  │  │
│  ┌──────────────┐    │  │  parsing)   │  │  (embeddings)  │  │  │
│  │  Frontend /  │───►│  └─────────────┘  └────────────────┘  │  │
│  │  Event Bot   │    │                                        │  │
│  │ GET /search  │    └────────────────────────────────────────┘  │
│  └──────────────┘                      │                         │
│                                        │ upsert / query          │
└────────────────────────────────────────┼─────────────────────────┘
                                         ▼
                               ┌──────────────────┐
                               │    Pinecone       │
                               │ (managed cloud)   │
                               │ 384-dim cosine    │
                               └──────────────────┘
```

### Component Roles

| Component | Role |
|---|---|
| **FastAPI** | HTTP server, request validation, routing |
| **fastembed** | Local ONNX model — converts text to 384-dim vectors |
| **Pinecone** | Managed vector DB — stores and searches embeddings |
| **Groq** | LLM — parses natural language queries into semantic text + hard filters |
| **systemd** | Keeps the service alive, auto-restarts on crash |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API framework | FastAPI | Async, fast, auto Swagger docs at /docs |
| Embedding model | BAAI/bge-small-en-v1.5 via fastembed | Free, local, 384 dims, excellent quality |
| Vector DB | Pinecone serverless | Managed, zero ops, free tier covers dev |
| Query parsing | Groq (llama-3.1-8b-instant) | Fast ~200ms, cheap, OpenAI-compatible API |
| Process manager | uvicorn + systemd | Production-grade, auto-restart on EC2 |
| Language | Python 3.12 | |

---

## Project Structure

```
event_bot_vector_search/
│
├── main.py                   # FastAPI app — all routes
├── models.py                 # Pydantic schemas — request/response shapes
├── search_engine.py          # Pinecone client — embed, upsert, search, delete
├── groq_client.py            # Groq LLM — query parsing + intent extraction
├── config.py                 # All env vars (pydantic-settings)
│
├── scripts/
│   └── seed_and_test.py      # 100 synthetic attendees + 12 test queries
│
├── .env.example              # Copy to .env and fill in your keys
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container build (bakes embedding model at build time)
├── docker-compose.yml        # Single-service compose (Pinecone is cloud, no local DB)
├── event-search.service      # systemd unit file for EC2
├── nginx-search.conf         # Nginx reverse proxy config (optional)
│
└── .github/
    └── workflows/
        └── deploy.yml        # Auto-deploy to EC2 on push to main
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- Pinecone account — free at https://app.pinecone.io
- Groq API key — free at https://console.groq.com

### Local Development

```bash
# 1. Clone
git clone https://github.com/for-real-afk/event_bot_vector_search.git
cd event_bot_vector_search

# 2. Create virtualenv
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Open .env and fill in PINECONE_API_KEY and GROQ_API_KEY

# 5. Start server
uvicorn main:app --reload --port 8003

# 6. Open interactive docs
# http://localhost:8003/docs
```

### Seed with Test Data

```bash
# Seed 100 synthetic attendees + run 12 test queries
python scripts/seed_and_test.py

# Skip seeding, just test search
python scripts/seed_and_test.py --test-only

# Against a remote server
python scripts/seed_and_test.py --url http://your-ec2-ip:8003
```

---

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `PINECONE_API_KEY` | Yes | — | From https://app.pinecone.io |
| `PINECONE_INDEX` | No | `attendees` | Pinecone index name |
| `PINECONE_CLOUD` | No | `aws` | Cloud provider |
| `PINECONE_REGION` | No | `us-east-1` | Free tier default |
| `EMBEDDING_MODEL` | No | `BAAI/bge-small-en-v1.5` | fastembed model |
| `VECTOR_SIZE` | No | `384` | Must match model output dims |
| `SCORE_THRESHOLD` | No | `0.25` | Min cosine similarity to include a result |
| `GROQ_API_KEY` | No | — | Enables LLM query parsing. Without it, raw query is used |
| `GROQ_BASE_URL` | No | Groq cloud | Override to point at your EC2 Gemma (Ollama) |
| `GROQ_MODEL` | No | `llama-3.1-8b-instant` | LLM for query parsing |
| `GROQ_QUERY_EXPANSION` | No | `true` | Set `false` to disable LLM parsing |
| `DEBUG` | No | `false` | Verbose logging |

### Switching to EC2 Gemma (Production)

Two lines in `.env` — no code changes:

```env
GROQ_BASE_URL=http://<EC2-PRIVATE-IP>:11434/v1
GROQ_MODEL=gemma3:27b
GROQ_API_KEY=ollama
```

---

## API Endpoints

**Base URL:** `http://your-ec2-ip:8003`
**Interactive docs:** `http://your-ec2-ip:8003/docs`

---

### `GET /health`

```bash
curl http://localhost:8003/health

# Response
{ "status": "ok", "version": "1.0.0" }
```

---

### `GET /search`

Main search endpoint. Accepts natural language, returns ranked attendees.

**Parameters**

| Param | Type | Required | Description |
|---|---|---|---|
| `q` | string | Yes | Natural language query |
| `limit` | integer | No | Max results, default 10, max 50 |
| `experience_level` | string | No | Hard override: `junior` \| `mid` \| `senior` \| `expert` |
| `organization` | string | No | Hard override: exact org name |

Manual params override LLM-extracted filters when both are present.

**Example**

```bash
curl "http://localhost:8003/search?q=AI+engineers+with+less+than+5+years+experience"

# Response
{
  "query": "AI engineers with less than 5 years experience",
  "expanded_query": "AI engineers machine learning deep learning data science",
  "total": 5,
  "results": [
    {
      "id": "usr_051",
      "full_name": "Harshit Bansal",
      "role": "Document AI Engineer",
      "organization": "KYC AI",
      "experience_level": "mid",
      "detailed_profile": "Building OCR and document intelligence systems...",
      "linkedin_url": "https://linkedin.com/in/harshitbansal-kyc",
      "score": 0.7374
    }
  ]
}
```

**Score guide**

| Score | Match quality |
|---|---|
| 0.75 – 1.0 | Strong match |
| 0.50 – 0.74 | Good match |
| 0.25 – 0.49 | Partial match |
| Below 0.25 | Filtered out automatically |

---

### `POST /attendees`

Index or update a single attendee. Call from your main backend on registration.

```bash
curl -X POST http://localhost:8003/attendees \
  -H "Content-Type: application/json" \
  -d '{
    "id": "user_123",
    "full_name": "Priya Nair",
    "email": "priya@example.com",
    "organization": "HealthAI Labs",
    "role": "ML Engineer",
    "experience_level": "senior",
    "detailed_profile": "Building diagnostic AI for radiology using PyTorch.",
    "linkedin_url": "https://linkedin.com/in/priyanair"
  }'

# Response 201
{ "indexed": 1, "id": "user_123" }
```

**Fields**

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Your backend's unique ID |
| `full_name` | Yes | |
| `email` | Yes | |
| `organization` | Yes | |
| `role` | Yes | |
| `phone` | No | Stored, not searched |
| `experience_level` | No | `junior` \| `mid` \| `senior` \| `expert` |
| `detailed_profile` | No | Free text — primary search signal. Always include this |
| `linkedin_url` | No | Returned in results, not used for search |

---

### `POST /attendees/bulk`

Batch index. Use to seed from your DB at event setup.

```bash
curl -X POST http://localhost:8003/attendees/bulk \
  -H "Content-Type: application/json" \
  -d '[{ "id": "usr_001", ... }, { "id": "usr_002", ... }]'

# Response 201
{ "indexed": 2, "message": "2 attendee(s) indexed" }
```

---

### `DELETE /attendees/{id}`

Remove an attendee (e.g. cancellation).

```bash
curl -X DELETE http://localhost:8003/attendees/user_123

# Response
{ "deleted": "user_123" }
```

---

### `DELETE /attendees`

Wipe entire index. Use when re-seeding for a new event.

```bash
curl -X DELETE http://localhost:8003/attendees

# Response
{ "message": "Index wiped and recreated" }
```

---

## Query Examples

The LLM parser handles natural language — no structured input needed.

| Query | Extracted by LLM |
|---|---|
| `AI engineers with less than 5 years experience` | filter: `experience_level=mid` |
| `senior NLP researchers` | filter: `experience_level=senior` |
| `junior data scientists` | filter: `experience_level=junior` |
| `expert investors in deep tech` | filter: `experience_level=expert` |
| `founders working in agriculture` | no filter — pure semantic search |
| `ML engineers at IIT Bombay` | filter: `organization=IIT Bombay AI Lab` |
| `healthcare AI researchers open to collaboration` | no filter — semantic search |

---

## Deployment

### EC2 Setup (First Time)

```bash
# SSH in
ssh -i your-key.pem ubuntu@your-ec2-ip

# Clone
git clone https://github.com/for-real-afk/event_bot_vector_search.git
cd event_bot_vector_search

# Virtualenv + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pre-cache embedding model (one-time ~4 min download)
python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

# Create .env
cp .env.example .env
nano .env    # add PINECONE_API_KEY and GROQ_API_KEY

# Install and start systemd service
sudo cp event-search.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable event-search
sudo systemctl start event-search

# Verify
curl http://localhost:8003/health
```

### Service Management

```bash
sudo systemctl start event-search       # start
sudo systemctl stop event-search        # stop
sudo systemctl restart event-search     # restart after code change
sudo systemctl status event-search      # current status

sudo journalctl -u event-search -f      # live logs
sudo journalctl -u event-search -n 50   # last 50 lines
sudo journalctl -u event-search -b      # since last boot
```

### EC2 Security Group

Open inbound TCP port `8003` from `0.0.0.0/0` in your AWS Security Group.

---

## GitHub Actions CI/CD

Every push to `main` auto-deploys to EC2.

**Setup — add these three secrets to your GitHub repo:**
`Settings → Secrets and variables → Actions → New repository secret`

| Secret | Value |
|---|---|
| `EC2_HOST` | Your EC2 public IP |
| `EC2_USERNAME` | `ubuntu` |
| `EC2_SSH_KEY` | Full contents of your `.pem` file |

**After setup, every deploy is:**

```bash
git add .
git commit -m "your change"
git push
```

GitHub Actions SSHes in, pulls latest code, reinstalls deps if needed, restarts the service. Watch it live under the **Actions** tab.

---

## Frontend Integration

```javascript
// React hook — drop this into your project
import { useState, useEffect } from 'react';

const BASE_URL = 'http://your-ec2-ip:8003';

export function useAttendeeSearch() {
  const [query, setQuery]     = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  useEffect(() => {
    if (!query.trim()) { setResults([]); return; }

    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ q: query, limit: 10 });
        const res    = await fetch(`${BASE_URL}/search?${params}`);
        const data   = await res.json();
        setResults(data.results);
      } catch {
        setError('Search unavailable');
      } finally {
        setLoading(false);
      }
    }, 400); // debounce 400ms

    return () => clearTimeout(timer);
  }, [query]);

  return { query, setQuery, results, loading, error };
}
```

---

## Calling from Your Main Backend

### Node.js

```javascript
async function indexAttendee(user) {
  await fetch('http://localhost:8003/attendees', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id:               String(user.id),
      full_name:        user.name,
      email:            user.email,
      phone:            user.phone,
      organization:     user.org,
      role:             user.role,
      experience_level: user.level,
      detailed_profile: user.bio,
      linkedin_url:     user.linkedin,
    }),
  });
}
```

### Python

```python
import httpx

async def index_attendee(user: dict):
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://localhost:8003/attendees",
            json={
                "id":               str(user["id"]),
                "full_name":        user["name"],
                "email":            user["email"],
                "organization":     user["org"],
                "role":             user["role"],
                "experience_level": user.get("level"),
                "detailed_profile": user.get("bio"),
                "linkedin_url":     user.get("linkedin"),
            }
        )
```

---

## Error Codes

| Status | Meaning |
|---|---|
| `200` | Success |
| `201` | Attendee indexed |
| `422` | Validation error — check required fields |
| `500` | Server error — run `sudo journalctl -u event-search -n 50` |
