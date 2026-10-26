# Enterprise AI Platform Architecture (Research Report)

**AI platforms.** Products such as ChatGPT Teams, Claude Projects and Copilot Studio wrap a stateless LLM in stateful software: identity, workspaces, retrieval, memory, tools and observability. The model is a replaceable component; the platform is the product.

**Workspace architecture.** A workspace is the unit of isolation and configuration. It owns its assistant settings, conversations, documents, memory and prompts, so a user can run "Marketing" and "Research" assistants without cross-contamination. Our schema keys every table on `workspace_id`, and every query also checks the workspace owner.

**Persistent memory.** Conversation history gives short-term continuity (we send the last 10 messages). Long-term memory stores durable facts ("remember that...") and pinned items, retrieved by similarity and injected into the prompt each turn. Experiment 1 showed recall rising from 0% to 100% with memory enabled.

**Prompt management.** System prompts, templates and skills are versionable assets, not code. We provide a categorised prompt library and eight reusable skills shared across workspaces. Experiment 2 showed a long system prompt cost 7x the tokens on every request, so prompt size is a cost lever. Production next step: store prompt versions with an id, author and change log.

**Multi-user systems.** Requires authentication, per-user data scoping and quotas. We use PBKDF2-hashed passwords, random revocable bearer tokens, owner checks on every route (foreign IDs return 404) and a per-user rate limit.

**Knowledge management.** Documents are parsed, chunked (120 words, 20 overlap), embedded and searched by cosine similarity; answers cite `file#chunk`. Experiment 6 showed large chunks dilute similarity and reduce hit rate; small chunks give sharper citations at higher storage cost. The default hashed embeddings are for offline use; production should use a real embedding model and a vector index (pgvector, Qdrant).

**Scalability.** Replace SQLite with PostgreSQL, move the rate limiter and sessions to Redis, run stateless API replicas behind a load balancer, make embedding and indexing asynchronous (queue + workers), and cache frequent retrievals. Search is currently brute-force O(chunks); an ANN index is needed beyond about 100k chunks.

**Security.** API keys live in environment variables only. Retrieved text is wrapped in a `<context>` block and the system prompt instructs the model to treat it as untrusted data (mitigates, but does not eliminate, prompt injection). Conversations are isolated by owner checks; logs store metadata (tokens, cost, latency), not message bodies. Remaining work: HTTPS-only deployment, token expiry, upload size limits, audit logging and output filtering for sensitive data.
