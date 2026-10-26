# AI Workspace Platform
Multi-user AI workspace (ChatGPT Teams / Claude Projects style): FastAPI + SQLite + pluggable LLM.

## Architecture
`Client → FastAPI (app/main.py) → Auth (token sessions, PBKDF2) → Workspace/Conversation managers → services.chat → Memory + Knowledge Base (chunk → embed → cosine search) → LLM → SQLite`
- `core.py` config, logging, DB abstraction, password hashing  - `services.py` reusable services  - `main.py` API + Pydantic models
- LLM: set `OPENAI_API_KEY` for OpenAI; otherwise a deterministic mock is used (tests run offline).
- Embeddings: hashed bag-of-words (offline); replace `services.embed` with a real model for production quality.

## Schema (12 tables)
users, sessions, workspaces, settings (assistant config), conversations, messages, documents, chunks, embeddings, prompt_templates, skills (8 built-in, shared by all workspaces), memory, logs (tokens/cost/latency).

## Frontend
Streamlit UI (`frontend/streamlit_app.py`): login/register, workspaces, chat (search/rename/delete/export), documents + semantic search, memory, prompt library, skills, assistant config, dashboard. Dark theme via `.streamlit/config.toml`.

## Run
```
pip install -r requirements.txt && cp .env.example .env
uvicorn app.main:app --reload     # docs at /docs
pytest -q                          # 32 tests
pip install streamlit && API_URL=http://localhost:8000 streamlit run frontend/streamlit_app.py
python eval/run_eval.py            # 46 scenarios + 6 experiments + perf -> docs/RESULTS.md
```
## Advanced features: conversation export (Markdown), conversation search, pinned memory, multiple models (per-workspace `model`), dark mode.
## Docs: `docs/REPORT.md` (research report), `docs/RESULTS.md` (evaluation, experiments, performance). Deploy: `render.yaml` (API + UI).
## Security: PBKDF2 passwords; random bearer tokens revoked on logout; every query scoped by owner (404 on foreign IDs); per-user rate limit; Pydantic validation; retrieved text wrapped in `<context>` with an injection-resistant system rule; secrets via env vars; logs omit message bodies.
## Known limitations: eval scores use a mock LLM (pipeline accuracy, not model quality; citation precision 68% due to hashed embeddings), no real embeddings by default, tokens estimated (len/4), in-memory rate limiter (single process), not yet deployed (needs your Render account), no screenshots.
