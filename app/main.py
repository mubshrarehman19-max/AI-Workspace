"""FastAPI backend. Run: uvicorn app.main:app"""
import collections, os, sqlite3, time
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
import secrets

from . import services as svc
from .core import check_pw, get_db, hash_pw, init_db, q, x

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="AI Workspace Platform", version="1.0", lifespan=lifespan)
_hits: dict[int, collections.deque] = collections.defaultdict(collections.deque)


class Cred(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8)


class WsIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = ""


class AssistantIn(BaseModel):
    name: str = "Assistant"
    role: str = "helpful assistant"
    system_prompt: str = "Be accurate and concise."
    model: str = "gpt-4o-mini"
    temperature: float = Field(0.3, ge=0, le=2)
    max_tokens: int = Field(512, ge=1, le=4096)
    personality: str = "friendly"
    style: str = "concise"


class DocIn(BaseModel):
    filename: str
    content_b64: str


class SearchIn(BaseModel):
    query: str
    k: int = Field(3, ge=1, le=20)


class TitleIn(BaseModel):
    title: str = "New chat"


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    use_memory: bool = True


class MemIn(BaseModel):
    content: str
    pinned: bool = False


class PromptIn(BaseModel):
    category: str = Field(pattern="^(Writing|Programming|Research|Business|Education|Custom)$")
    title: str
    body: str


class SkillIn(BaseModel):
    input: str


def user(authorization: str = Header(""), db: sqlite3.Connection = Depends(get_db)) -> int:
    r = q(db, "SELECT user_id FROM sessions WHERE token=?", authorization.removeprefix("Bearer "))
    if not r:
        raise HTTPException(401, "invalid or missing token")
    return r[0]["user_id"]


def own(db, ws: int, uid: int) -> int:
    if not q(db, "SELECT 1 FROM workspaces WHERE id=? AND user_id=?", ws, uid):
        raise HTTPException(404, "workspace not found")
    return ws


def conv_ws(db, cid: int, uid: int) -> int:
    r = q(db, "SELECT c.workspace_id w FROM conversations c JOIN workspaces w ON w.id=c.workspace_id "
              "WHERE c.id=? AND w.user_id=?", cid, uid)
    if not r:
        raise HTTPException(404, "conversation not found")
    return r[0]["w"]


# ---- auth
@app.post("/auth/register", status_code=201)
def register(c: Cred, db=Depends(get_db)):
    if q(db, "SELECT 1 FROM users WHERE email=?", c.email.lower()):
        raise HTTPException(409, "email already registered")
    return {"id": x(db, "INSERT INTO users(email,pw_hash,created_at) VALUES(?,?,?)", c.email.lower(), hash_pw(c.password), time.time())}


@app.post("/auth/login")
def login(c: Cred, db=Depends(get_db)):
    r = q(db, "SELECT * FROM users WHERE email=?", c.email.lower())
    if not r or not check_pw(c.password, r[0]["pw_hash"]):
        raise HTTPException(401, "invalid credentials")
    tok = secrets.token_urlsafe(32)
    x(db, "INSERT INTO sessions VALUES(?,?,?)", tok, r[0]["id"], time.time())
    return {"token": tok}


@app.post("/auth/logout")
def logout(authorization: str = Header(""), uid: int = Depends(user), db=Depends(get_db)):
    x(db, "DELETE FROM sessions WHERE token=?", authorization.removeprefix("Bearer "))
    return {"ok": True}


# ---- workspaces & assistant
@app.post("/workspaces", status_code=201)
def create_ws(b: WsIn, uid: int = Depends(user), db=Depends(get_db)):
    wid = x(db, "INSERT INTO workspaces(user_id,name,prompt,created_at) VALUES(?,?,?,?)", uid, b.name, b.prompt, time.time())
    a = AssistantIn()
    x(db, "INSERT INTO settings VALUES(?,?,?,?,?,?,?,?,?)", wid, a.name, a.role, a.system_prompt, a.model, a.temperature, a.max_tokens, a.personality, a.style)
    return {"id": wid, "name": b.name}


@app.get("/workspaces")
def list_ws(uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT id,name,created_at FROM workspaces WHERE user_id=?", uid)


@app.get("/workspaces/{ws}/assistant")
def get_assistant(ws: int, uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT * FROM settings WHERE workspace_id=?", own(db, ws, uid))[0]


@app.put("/workspaces/{ws}/assistant")
def set_assistant(ws: int, a: AssistantIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    x(db, "UPDATE settings SET name=?,role=?,system_prompt=?,model=?,temperature=?,max_tokens=?,personality=?,style=? WHERE workspace_id=?",
      a.name, a.role, a.system_prompt, a.model, a.temperature, a.max_tokens, a.personality, a.style, ws)
    return a


@app.get("/workspaces/{ws}/dashboard")
def dashboard(ws: int, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    n = lambda t, col="workspace_id": q(db, f"SELECT COUNT(*) n FROM {t} WHERE {col}=?", ws)[0]["n"]
    u = q(db, "SELECT COALESCE(SUM(tokens),0) t, COALESCE(SUM(cost),0) c, COALESCE(AVG(latency),0) l FROM logs WHERE workspace_id=?", ws)[0]
    return {"conversations": n("conversations"), "documents": n("documents"), "memory_items": n("memory"),
            "prompt_templates": n("prompt_templates"), "tokens": u["t"], "estimated_cost": round(u["c"], 6),
            "avg_latency_s": round(u["l"], 4), "recent_activity": q(db, "SELECT event,created_at FROM logs WHERE workspace_id=? ORDER BY id DESC LIMIT 5", ws)}


# ---- knowledge base
@app.post("/workspaces/{ws}/documents", status_code=201)
def upload(ws: int, d: DocIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    try:
        return svc.add_document(db, ws, d.filename, d.content_b64)
    except Exception as e:  # parse / decode failures -> client error
        raise HTTPException(400, str(e))


@app.get("/workspaces/{ws}/documents")
def docs(ws: int, uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT id,filename,summary FROM documents WHERE workspace_id=?", own(db, ws, uid))


@app.post("/workspaces/{ws}/search")
def semantic(ws: int, s: SearchIn, uid: int = Depends(user), db=Depends(get_db)):
    return svc.search(db, own(db, ws, uid), s.query, s.k)


# ---- conversations
@app.post("/workspaces/{ws}/conversations", status_code=201)
def new_conv(ws: int, b: TitleIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    sid = secrets.token_hex(8)
    return {"id": x(db, "INSERT INTO conversations(workspace_id,session_id,title,created_at) VALUES(?,?,?,?)", ws, sid, b.title, time.time()), "session_id": sid}


@app.get("/workspaces/{ws}/conversations")
def list_conv(ws: int, search: str = "", uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    return q(db, "SELECT DISTINCT c.id,c.title,c.session_id,c.created_at FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id "
                 "WHERE c.workspace_id=? AND (c.title LIKE ? OR m.content LIKE ?)", ws, f"%{search}%", f"%{search}%")


@app.patch("/conversations/{cid}")
def rename(cid: int, b: TitleIn, uid: int = Depends(user), db=Depends(get_db)):
    conv_ws(db, cid, uid); x(db, "UPDATE conversations SET title=? WHERE id=?", b.title, cid)
    return {"id": cid, "title": b.title}


@app.delete("/conversations/{cid}")
def delete_conv(cid: int, uid: int = Depends(user), db=Depends(get_db)):
    conv_ws(db, cid, uid)
    x(db, "DELETE FROM messages WHERE conversation_id=?", cid); x(db, "DELETE FROM conversations WHERE id=?", cid)
    return {"ok": True}


@app.get("/conversations/{cid}/messages")
def messages(cid: int, uid: int = Depends(user), db=Depends(get_db)):
    conv_ws(db, cid, uid)
    return q(db, "SELECT role,content,citations,tokens,created_at FROM messages WHERE conversation_id=? ORDER BY id", cid)


@app.get("/conversations/{cid}/export", response_class=PlainTextResponse)
def export(cid: int, uid: int = Depends(user), db=Depends(get_db)):
    conv_ws(db, cid, uid)
    t = q(db, "SELECT title FROM conversations WHERE id=?", cid)[0]["title"]
    return f"# {t}\n\n" + "\n\n".join(f"**{m['role']}**: {m['content']}" for m in q(db, "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id", cid))


@app.post("/conversations/{cid}/chat")
def chat(cid: int, b: ChatIn, uid: int = Depends(user), db=Depends(get_db)):
    ws = conv_ws(db, cid, uid)
    dq, now, limit = _hits[uid], time.time(), int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= limit:
        raise HTTPException(429, "rate limit exceeded")
    dq.append(now)
    try:
        return svc.chat(db, ws, cid, b.message, b.use_memory)
    except Exception as e:
        svc.log.exception("chat failed")
        raise HTTPException(502, f"LLM error: {type(e).__name__}")


# ---- memory, prompts, skills
@app.post("/workspaces/{ws}/memory", status_code=201)
def add_mem(ws: int, m: MemIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    return {"id": x(db, "INSERT INTO memory(workspace_id,content,pinned,created_at) VALUES(?,?,?,?)", ws, m.content, int(m.pinned), time.time())}


@app.get("/workspaces/{ws}/memory")
def get_mem(ws: int, uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT id,content,pinned FROM memory WHERE workspace_id=?", own(db, ws, uid))


@app.post("/workspaces/{ws}/prompts", status_code=201)
def add_prompt(ws: int, p: PromptIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    return {"id": x(db, "INSERT INTO prompt_templates(workspace_id,category,title,body) VALUES(?,?,?,?)", ws, p.category, p.title, p.body)}


@app.get("/workspaces/{ws}/prompts")
def get_prompts(ws: int, uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT * FROM prompt_templates WHERE workspace_id=?", own(db, ws, uid))


@app.put("/workspaces/{ws}/prompts/{pid}")
def edit_prompt(ws: int, pid: int, p: PromptIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    x(db, "UPDATE prompt_templates SET category=?,title=?,body=? WHERE id=? AND workspace_id=?", p.category, p.title, p.body, pid, ws)
    return {"id": pid}


@app.delete("/workspaces/{ws}/prompts/{pid}")
def del_prompt(ws: int, pid: int, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid); x(db, "DELETE FROM prompt_templates WHERE id=? AND workspace_id=?", pid, ws)
    return {"ok": True}


@app.get("/skills")
def skills(uid: int = Depends(user), db=Depends(get_db)):
    return q(db, "SELECT name,description FROM skills")


@app.post("/workspaces/{ws}/skills/{name}/run")
def run(ws: int, name: str, s: SkillIn, uid: int = Depends(user), db=Depends(get_db)):
    own(db, ws, uid)
    try:
        return {"output": svc.run_skill(db, ws, name, s.input)}
    except KeyError:
        raise HTTPException(404, "unknown skill")
