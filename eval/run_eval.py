"""Runs 46 eval scenarios, 6 experiments and perf measurements -> docs/RESULTS.md"""
import base64, os, sqlite3, statistics as st, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(DB_PATH=os.path.join(tempfile.mkdtemp(), "e.db"), RATE_LIMIT_PER_MIN="100000"); os.environ.pop("OPENAI_API_KEY", None)
from fastapi.testclient import TestClient
from app import services as svc
from app.core import init_db, q
from app.main import app

T0 = time.perf_counter(); init_db(); startup = time.perf_counter() - T0
c = TestClient(app)
c.post("/auth/register", json={"email": "e@x.com", "password": "password1"})
H = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "e@x.com", "password": "password1"}).json()["token"]}
ws = c.post("/workspaces", json={"name": "Eval"}, headers=H).json()["id"]
conv = lambda: c.post(f"/workspaces/{ws}/conversations", json={}, headers=H).json()["id"]
def chat(cv, m, **k):
    t = time.perf_counter(); r = c.post(f"/conversations/{cv}/chat", json={"message": m, **k}, headers=H); return r, time.perf_counter() - t
b64 = lambda s: base64.b64encode(s.encode()).decode()
R: list[tuple[str, bool, float]] = []
rec = lambda cat, ok, lat: R.append((cat, bool(ok), lat))

DOCS = {"solar.txt": "Solar panels convert sunlight into electricity using photovoltaic silicon cells.",
        "python.txt": "Python uses indentation and dynamic typing; the pip tool installs packages from PyPI.",
        "sparta.txt": "Ancient Sparta trained citizens as soldiers through the agoge education system.",
        "coffee.txt": "Coffee beans are roasted at high temperature; arabica is sweeter than robusta.",
        "mito.txt": "Mitochondria produce ATP through cellular respiration inside eukaryotic cells."}
for n, t in DOCS.items():
    c.post(f"/workspaces/{ws}/documents", json={"filename": n, "content_b64": b64(t)}, headers=H)
DQ = [("how do photovoltaic silicon cells make electricity", "solar.txt"), ("sunlight into electricity panels", "solar.txt"),
      ("python indentation dynamic typing", "python.txt"), ("install packages with pip from PyPI", "python.txt"),
      ("agoge education Sparta soldiers", "sparta.txt"), ("how did Sparta train citizens", "sparta.txt"),
      ("arabica robusta coffee roasted", "coffee.txt"), ("coffee beans roasted temperature", "coffee.txt"),
      ("mitochondria produce ATP respiration", "mito.txt"), ("ATP cellular respiration eukaryotic cells", "mito.txt")]
prec = []
for qn, f in DQ:
    r, l = chat(conv(), qn); cites = [x.split("#")[0] for x in r.json()["citations"]]
    prec.append(cites.count(f) / len(cites) if cites else 0); rec("Document Questions", f in cites, l)
for qn in ["Explain what an API is", "What is a database index?", "Define machine learning", "What is recursion?", "Explain HTTP status codes", "What is Git?"]:
    r, l = chat(conv(), qn); rec("Knowledge Questions", r.status_code == 200 and len(r.json()["reply"]) > 10, l)
MEM = [("dog", "called", "Biscuit"), ("favourite colour", "is", "teal"), ("city", "is", "Lahore"), ("deadline", "is", "Friday"),
       ("favourite language", "is", "Rust"), ("favourite drink", "is", "oolong"), ("sport", "is", "cricket"), ("university", "is", "UCP")]
cv0 = conv()
for k, v, val in MEM:
    chat(cv0, f"remember that my {k} {v} {val}")
def mem_run(use):
    out = []
    for k, v, val in MEM:
        r, l = chat(conv(), f"what is my {k} {'called' if k == 'dog' else ''}", use_memory=use); out.append((val.lower() in r.json()["reply"].lower(), l))
    return out
for ok, l in mem_run(True):
    rec("Memory Questions", ok, l)
for n in [2, 3, 4, 5, 6]:
    cv = conv(); l = [chat(cv, f"turn {i}")[1] for i in range(n)]
    rec("Conversation Continuation", len(c.get(f"/conversations/{cv}/messages", headers=H).json()) == 2 * n, st.mean(l))
for i, cat in enumerate(["Writing", "Programming", "Business", "Education"]):
    t = time.perf_counter(); pid = c.post(f"/workspaces/{ws}/prompts", json={"category": cat, "title": f"p{i}", "body": f"Draft a {cat} outline"}, headers=H)
    r, l = chat(conv(), f"Draft a {cat} outline"); rec("Prompt Templates", pid.status_code == 201 and r.status_code == 200, time.perf_counter() - t)
for s in [x["name"] for x in c.get("/skills", headers=H).json()]:
    t = time.perf_counter(); r = c.post(f"/workspaces/{ws}/skills/{s}/run", json={"input": "mobile app launch"}, headers=H)
    rec("Skill Invocation", r.status_code == 200 and r.json()["output"], time.perf_counter() - t)
cv = conv(); t = time.perf_counter()
rec("Edge Cases", chat(cv, "")[0].status_code == 422, 0); rec("Edge Cases", chat(cv, "x" * 9000)[0].status_code == 422, 0)
rec("Edge Cases", chat(cv, "مرحبا 你好 ¿qué?")[0].status_code == 200, 0)
rec("Edge Cases", c.post(f"/workspaces/{ws}/skills/nope/run", json={"input": "x"}, headers=H).status_code == 404, 0)
rec("Edge Cases", c.get("/workspaces").status_code == 401, 0)

cats = list(dict.fromkeys(r[0] for r in R)); md = ["# Evaluation, Experiments & Performance (auto-generated by eval/run_eval.py)\n",
    "> LLM = built-in deterministic mock, so scores measure the *platform pipeline* (retrieval, memory, citations, persistence, validation), not model quality. Re-run with `OPENAI_API_KEY` set for model-level results.\n",
    f"## Evaluation: {len(R)} scenarios\n", "| Category | Scenarios | Accuracy | Avg time (ms) |", "|---|---|---|---|"]
for k in cats:
    rows = [r for r in R if r[0] == k]; md.append(f"| {k} | {len(rows)} | {sum(r[1] for r in rows)/len(rows):.0%} | {st.mean(r[2] for r in rows)*1000:.1f} |")
mr = [r for r in R if r[0] == "Memory Questions"]
md += [f"\n**Overall accuracy** {sum(r[1] for r in R)/len(R):.0%} · **Memory recall** {sum(r[1] for r in mr)/len(mr):.0%} · "
       f"**Citation quality** (precision of cited files) {st.mean(prec):.0%} · **Task success** (skills+prompts) "
       f"{st.mean([r[1] for r in R if r[0] in ('Skill Invocation','Prompt Templates')]):.0%} · **Mean response time** {st.mean(r[2] for r in R if r[2])*1000:.1f} ms\n", "## Experiments\n"]
db = sqlite3.connect(os.environ["DB_PATH"]); db.row_factory = sqlite3.Row
on, off = mem_run(True), mem_run(False)
md.append(f"1. **Memory on vs off** — recall {sum(o for o,_ in on)/8:.0%} vs {sum(o for o,_ in off)/8:.0%}. Memory is what carries facts across sessions.")
toks = {}
for name, sp in [("short", "Be concise."), ("detailed", "You are an expert analyst. " + "Always reason carefully and cite sources. " * 40)]:
    c.put(f"/workspaces/{ws}/assistant", json={"system_prompt": sp}, headers=H); toks[name] = chat(conv(), "hello")[0].json()["tokens"]
md.append(f"2. **Short vs detailed system prompt** — {toks['short']} vs {toks['detailed']} tokens/request ({toks['detailed']/toks['short']:.1f}x cost); detailed prompts cost more on every turn.")
c.put(f"/workspaces/{ws}/assistant", json={"system_prompt": "Be accurate."}, headers=H); lat = {}
for m in ["gpt-4o-mini", "gemini-1.5-flash"]:
    c.put(f"/workspaces/{ws}/assistant", json={"model": m, "system_prompt": "Be accurate."}, headers=H); lat[m] = st.mean(chat(conv(), "hi")[1] for _ in range(5)) * 1000
md.append(f"3. **Different models** — latency {', '.join(f'{k}: {v:.1f} ms' for k, v in lat.items())}. Mock backend, so identical; the model field is switchable per workspace for live comparison.")
hits = {k: sum(f in {h['filename'] for h in svc.search(db, ws, qn, k)} for qn, f in DQ) / len(DQ) for k in (1, 3, 5)}
md.append(f"4. **Small vs large context (top-k)** — hit rate k=1: {hits[1]:.0%}, k=3: {hits[3]:.0%}, k=5: {hits[5]:.0%}. Larger k adds recall but also more prompt tokens.")
cv = conv(); ln = {}
for n in (0, 20, 60):
    while len(q(db, "SELECT id FROM messages WHERE conversation_id=?", cv)) < n: chat(cv, "filler message")
    ln[n] = st.mean(chat(cv, "ping")[1] for _ in range(3)) * 1000
md.append(f"5. **Conversation length** — latency at 0/~20/~60 messages: {ln[0]:.1f}/{ln[20]:.1f}/{ln[60]:.1f} ms. Roughly flat because only the last 10 messages are sent.")
F = "the of and to in is that for with as on are by this be or from at".split(); cs = {}
for size in (30, 120, 400):
    idx = [(f, svc.embed(ch)) for f, t in DOCS.items() for ch in svc.chunk(" ".join(F * 10) + " " + t + " " + " ".join(F * 10), size, size // 6)]
    tops = []; t0 = time.perf_counter()
    for qn, f in DQ:
        qv = svc.embed(qn); b = max(idx, key=lambda x: svc.cos(qv, x[1])); tops.append((b[0] == f, svc.cos(qv, b[1])))
    cs[size] = (sum(a for a, _ in tops) / len(tops), st.mean(s for _, s in tops), len(idx), (time.perf_counter() - t0) * 1000)
md.append("6. **Chunk size** (padded docs) — " + "; ".join(f"{k} words: hit {v[0]:.0%}, mean top score {v[1]:.2f}, {v[2]} chunks, {v[3]:.1f} ms" for k, v in cs.items()) + ". Bigger chunks dilute similarity scores; smaller chunks give sharper citations.")
t0 = time.perf_counter(); [svc.embed("sample sentence about solar panels and energy " * 5) for _ in range(500)]; emb = (time.perf_counter() - t0) / 500 * 1000
n_ch = q(db, "SELECT COUNT(*) n FROM chunks")[0]["n"]; t0 = time.perf_counter(); [svc.search(db, ws, "solar energy", 3) for _ in range(20)]; sr = (time.perf_counter() - t0) / 20 * 1000
t0 = time.perf_counter(); [svc.recall(db, ws, "what is my dog") for _ in range(20)]; rc = (time.perf_counter() - t0) / 20 * 1000
t0 = time.perf_counter(); d = c.get(f"/workspaces/{ws}/dashboard", headers=H).json(); dq = (time.perf_counter() - t0) * 1000
md += ["\n## Performance\n", "| Metric | Value |", "|---|---|", f"| Application/DB startup | {startup*1000:.1f} ms |", f"| Embedding time | {emb:.3f} ms per chunk |",
       f"| Semantic search ({n_ch} chunks) | {sr:.2f} ms |", f"| Memory retrieval | {rc:.2f} ms |", f"| Dashboard (aggregate queries) | {dq:.1f} ms |",
       f"| Mean chat round-trip | {st.mean(r[2] for r in R if r[0] in ('Document Questions','Knowledge Questions'))*1000:.1f} ms |",
       f"| Token usage (whole eval) | {d['tokens']} tokens |", f"| Estimated cost @ $0.002/1k | ${d['estimated_cost']:.4f} |"]
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "RESULTS.md"), "w").write("\n".join(md)); print("\n".join(md))
