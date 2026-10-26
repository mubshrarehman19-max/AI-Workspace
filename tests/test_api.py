import base64, pytest
from fastapi.testclient import TestClient
from app.core import init_db
from app.main import app
from app import services as svc

B64 = lambda s: base64.b64encode(s.encode()).decode()


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db")); monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    init_db(); return TestClient(app)


def signup(c, email="a@x.com"):
    c.post("/auth/register", json={"email": email, "password": "password1"})
    return {"Authorization": "Bearer " + c.post("/auth/login", json={"email": email, "password": "password1"}).json()["token"]}


@pytest.fixture()
def env(c):
    h = signup(c); ws = c.post("/workspaces", json={"name": "Research"}, headers=h).json()["id"]
    cv = c.post(f"/workspaces/{ws}/conversations", json={"title": "T"}, headers=h).json()["id"]
    return c, h, ws, cv


def test_register_duplicate(c):
    assert c.post("/auth/register", json={"email": "a@x.com", "password": "password1"}).status_code == 201
    assert c.post("/auth/register", json={"email": "a@x.com", "password": "password1"}).status_code == 409

def test_login_bad_password(c):
    signup(c); assert c.post("/auth/login", json={"email": "a@x.com", "password": "wrongpass1"}).status_code == 401

def test_logout_invalidates_token(c):
    h = signup(c); assert c.post("/auth/logout", headers=h).status_code == 200
    assert c.get("/workspaces", headers=h).status_code == 401

def test_requires_auth(c):
    assert c.get("/workspaces").status_code == 401

def test_workspace_create_list(env):
    c, h, ws, _ = env; assert [w["name"] for w in c.get("/workspaces", headers=h).json()] == ["Research"]

def test_workspace_isolation(env):
    c, h, ws, cv = env; h2 = signup(c, "b@x.com")
    assert c.get(f"/workspaces/{ws}/memory", headers=h2).status_code == 404
    assert c.post(f"/conversations/{cv}/chat", json={"message": "hi"}, headers=h2).status_code == 404

def test_assistant_config(env):
    c, h, ws, _ = env
    c.put(f"/workspaces/{ws}/assistant", json={"name": "Aria", "temperature": 0.9}, headers=h)
    assert c.get(f"/workspaces/{ws}/assistant", headers=h).json()["name"] == "Aria"

def test_assistant_validation(env):
    c, h, ws, _ = env; assert c.put(f"/workspaces/{ws}/assistant", json={"temperature": 5}, headers=h).status_code == 422

def test_conversation_rename_delete(env):
    c, h, ws, cv = env
    c.patch(f"/conversations/{cv}", json={"title": "New"}, headers=h)
    assert c.get(f"/workspaces/{ws}/conversations", headers=h).json()[0]["title"] == "New"
    c.delete(f"/conversations/{cv}", headers=h)
    assert c.get(f"/workspaces/{ws}/conversations", headers=h).json() == []

def test_chat_history_persisted(env):
    c, h, ws, cv = env; c.post(f"/conversations/{cv}/chat", json={"message": "hello"}, headers=h)
    m = c.get(f"/conversations/{cv}/messages", headers=h).json()
    assert [x["role"] for x in m] == ["user", "assistant"]

def test_conversation_search(env):
    c, h, ws, cv = env; c.post(f"/conversations/{cv}/chat", json={"message": "zebra facts"}, headers=h)
    assert len(c.get(f"/workspaces/{ws}/conversations?search=zebra", headers=h).json()) == 1
    assert c.get(f"/workspaces/{ws}/conversations?search=nothing", headers=h).json() == []

def test_document_upload_and_chunks(env):
    c, h, ws, _ = env
    r = c.post(f"/workspaces/{ws}/documents", json={"filename": "a.txt", "content_b64": B64("word " * 300)}, headers=h)
    assert r.status_code == 201 and r.json()["chunks"] >= 3

def test_unsupported_upload(env):
    c, h, ws, _ = env
    assert c.post(f"/workspaces/{ws}/documents", json={"filename": "a.exe", "content_b64": B64("x")}, headers=h).status_code == 400

def test_semantic_search(env):
    c, h, ws, _ = env
    for n, t in [("bio.txt", "Photosynthesis converts light into chemical energy in chloroplasts"), ("fin.txt", "The stock market closed higher on Tuesday")]:
        c.post(f"/workspaces/{ws}/documents", json={"filename": n, "content_b64": B64(t)}, headers=h)
    assert c.post(f"/workspaces/{ws}/search", json={"query": "light energy chloroplasts"}, headers=h).json()[0]["filename"] == "bio.txt"

def test_chat_returns_citations(env):
    c, h, ws, cv = env
    c.post(f"/workspaces/{ws}/documents", json={"filename": "bio.txt", "content_b64": B64("Photosynthesis converts light into chemical energy in chloroplasts")}, headers=h)
    assert c.post(f"/conversations/{cv}/chat", json={"message": "light energy chloroplasts"}, headers=h).json()["citations"] == ["bio.txt#0"]

def test_memory_pin(env):
    c, h, ws, _ = env; c.post(f"/workspaces/{ws}/memory", json={"content": "Prefers tea", "pinned": True}, headers=h)
    assert c.get(f"/workspaces/{ws}/memory", headers=h).json()[0]["pinned"] == 1

def test_memory_persists_across_conversations(env):
    c, h, ws, cv = env; c.post(f"/conversations/{cv}/chat", json={"message": "remember that my favourite drink is oolong"}, headers=h)
    cv2 = c.post(f"/workspaces/{ws}/conversations", json={}, headers=h).json()["id"]
    assert "oolong" in c.post(f"/conversations/{cv2}/chat", json={"message": "what is my favourite drink?"}, headers=h).json()["reply"]
    assert "oolong" not in c.post(f"/conversations/{cv2}/chat", json={"message": "what is my favourite drink?", "use_memory": False}, headers=h).json()["reply"].split("context:")[-1]

def test_prompt_library_crud(env):
    c, h, ws, _ = env
    pid = c.post(f"/workspaces/{ws}/prompts", json={"category": "Writing", "title": "t", "body": "b"}, headers=h).json()["id"]
    c.put(f"/workspaces/{ws}/prompts/{pid}", json={"category": "Business", "title": "t2", "body": "b"}, headers=h)
    assert c.get(f"/workspaces/{ws}/prompts", headers=h).json()[0]["category"] == "Business"
    c.delete(f"/workspaces/{ws}/prompts/{pid}", headers=h)
    assert c.get(f"/workspaces/{ws}/prompts", headers=h).json() == []

def test_prompt_bad_category(env):
    c, h, ws, _ = env; assert c.post(f"/workspaces/{ws}/prompts", json={"category": "X", "title": "t", "body": "b"}, headers=h).status_code == 422

@pytest.mark.parametrize("name", ["research", "summarize", "email", "report", "meeting_notes", "ideas", "task_plan", "swot"])
def test_skills_run(env, name):
    c, h, ws, _ = env; assert c.post(f"/workspaces/{ws}/skills/{name}/run", json={"input": "launch plan"}, headers=h).json()["output"]

def test_unknown_skill(env):
    c, h, ws, _ = env; assert c.post(f"/workspaces/{ws}/skills/nope/run", json={"input": "x"}, headers=h).status_code == 404

def test_dashboard(env):
    c, h, ws, cv = env; c.post(f"/conversations/{cv}/chat", json={"message": "hi"}, headers=h)
    d = c.get(f"/workspaces/{ws}/dashboard", headers=h).json()
    assert d["conversations"] == 1 and d["tokens"] > 0 and d["estimated_cost"] > 0

def test_export_markdown(env):
    c, h, ws, cv = env; c.post(f"/conversations/{cv}/chat", json={"message": "hi"}, headers=h)
    assert c.get(f"/conversations/{cv}/export", headers=h).text.startswith("# T")

def test_chunking_overlap():
    assert len(svc.chunk("w " * 250, 100, 20)) == 4

def test_embedding_similarity():
    a, b, d = svc.embed("red apple pie"), svc.embed("apple pie recipe"), svc.embed("quantum chromodynamics")
    assert svc.cos(a, b) > svc.cos(a, d)
