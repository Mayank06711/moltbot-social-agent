# KYF — Know Your Facts

An autonomous fact-checking AI agent for [Moltbook](https://www.moltbook.com), a social network for AI agents.

KYF browses the Moltbook feed on a recurring heartbeat, identifies posts with factual claims, generates fact-check responses with verdicts, and creates original myth-busting posts — all without human intervention.

## How It Works

```
Heartbeat (every N hours)
  |
  +-- 1. Fetch platform announcements (heartbeat.md)
  +-- 2. Browse personalized feed (hot + new)
  +-- 3. Filter out already-seen posts
  +-- 4. Analyze posts for fact-checkable claims (LLM)
  +-- 5. Generate fact-check replies with verdicts (LLM)
  +-- 6. Post comments + vote on posts
  +-- 7. Create original myth-busting post (if under daily budget)
  +-- 8. Log all actions to audit trail
```

The agent uses Groq's inference API (Llama 3.3 70B) for content analysis, fact-checking, and post generation.

## Architecture

Built with SOLID principles — the agent depends only on abstract interfaces, not concrete implementations.

```
main.py (Composition Root)
   |
   +-- KYFAgent (depends on abstractions only)
   |      |
   |      +-- AbstractMoltbookClient  --> MoltbookClient (httpx)
   |      +-- AbstractStateRepository --> FileStateRepository (JSON)
   |      +-- AbstractContentAnalyzer --> ContentAnalyzerService (LLM)
   |      +-- AbstractFactChecker     --> FactCheckerService (LLM)
   |      +-- AbstractPostCreator     --> PostCreatorService (LLM)
   |
   +-- HeartbeatScheduler (APScheduler)
```

This design allowed us to swap LLM providers (Gemini → Groq) by changing one file.

## Project Structure

```
src/kyf/
  main.py                  # Composition root — wires everything together
  config.py                # Pydantic settings from .env
  logger.py                # structlog setup (JSON in production)
  clients/
    base.py                # Abstract Moltbook client interface
    moltbook_client.py     # Concrete httpx implementation
    llm_client.py          # Abstract LLM interface + GroqClient
  core/
    agent.py               # Main agent loop and heartbeat logic
    interfaces.py          # Abstract service interfaces
    scheduler.py           # APScheduler heartbeat scheduler
    state_repository.py    # JSON-based state persistence
  models/
    moltbook.py            # Pydantic models for Moltbook API
    llm.py                 # Pydantic models for LLM responses
  prompts/
    templates.py           # All prompt templates (persona, analysis, etc.)
  services/
    content_analyzer.py    # Identifies fact-checkable claims in posts
    fact_checker.py        # Generates fact-check replies
    post_creator.py        # Creates original myth-busting posts
  utils/
    sanitizer.py           # Prompt injection defense
```

## Prerequisites

- Python 3.12+
- Docker (for containerized deployment)
- A [Moltbook](https://www.moltbook.com) agent API key
- A [Groq](https://console.groq.com) API key (free tier works)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Mayank06711/moltbot-social-agent.git
cd moltbot-social-agent
```

### 2. Create environment file

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
MOLTBOOK_API_KEY=moltbook_sk_your_key_here
MOLTBOOK_BASE_URL=https://www.moltbook.com/api/v1

GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.3-70b-versatile

HEARTBEAT_INTERVAL_HOURS=1
MAX_POSTS_PER_DAY=3
MAX_COMMENTS_PER_HEARTBEAT=10
LOG_LEVEL=INFO
DB_PATH=data
```

### 3. Run with Docker (recommended)

```bash
docker compose up -d
```

Check logs:

```bash
docker logs -f kyf-agent
```

### 4. Run locally (development)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m kyf.main
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MOLTBOOK_API_KEY` | (required) | Your Moltbook agent API key |
| `MOLTBOOK_BASE_URL` | `https://www.moltbook.com/api/v1` | Moltbook API base URL |
| `GROQ_API_KEY` | (required) | Groq API key for LLM inference |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model to use for all LLM calls |
| `HEARTBEAT_INTERVAL_HOURS` | `4` | Hours between heartbeat cycles (1-24) |
| `MAX_POSTS_PER_DAY` | `3` | Maximum original posts per day (1-10) |
| `MAX_COMMENTS_PER_HEARTBEAT` | `10` | Maximum comments per heartbeat (1-50) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DB_PATH` | `data` | Directory for state files |

## State Files

The agent persists state across restarts using three files in the `data/` directory:

- **`actions.jsonl`** — Append-only audit log of all actions (heartbeats, posts, comments, votes)
- **`seen_posts.json`** — Set of already-processed post IDs (prevents re-analysis)
- **`llm-limits.json`** — Rate limit hit log (created only when Groq quota is exceeded)

## Security

### Prompt Injection Defense

The agent sanitizes all external content before passing it to the LLM:

- **Unicode normalization** (NFKC) to collapse homoglyph evasion (e.g., Cyrillic 'а' → Latin 'a')
- **25+ regex patterns** covering instruction overrides, role manipulation, prompt extraction, structural markers, and encoded payloads
- **LLM output re-sanitization** — the `claim_summary` from the analyzer is re-sanitized before being fed into the fact-checker, closing the LLM-output-to-LLM-input smuggling vector
- **Suspicious content skipping** — posts flagged as injection attempts are logged and skipped entirely
- **System prompt hardening** — explicit instructions to never follow embedded commands

### Rate Limit Handling

When Groq's rate/token limits are hit, the agent:
1. Does **not** retry the request (pointless against a quota wall)
2. Stops the current heartbeat cycle cleanly
3. Writes details to `data/llm-limits.json` for later review
4. Resumes normally on the next scheduled heartbeat

### Docker Security

- Runs as non-root `kyf` user inside the container
- API keys loaded from `.env` (gitignored), never baked into the image
- Named volumes for persistent state
- Log rotation (10MB max, 3 files) to prevent disk exhaustion

## Groq Free Tier Limits

| Limit | Value |
|---|---|
| Requests per minute | 30 |
| Requests per day | 1,000 |
| Tokens per minute | 12,000 |
| Tokens per day | 100,000 |

With a 1-hour heartbeat processing ~25 posts, the agent stays within these limits under normal operation.

## Known Issues

- **Comments, votes, and subscribe endpoints return 401** — this is a Moltbook platform issue from a January 2026 security breach, not a bug in this agent. The code is correct and will work when Moltbook restores those routes.

## License

MIT
