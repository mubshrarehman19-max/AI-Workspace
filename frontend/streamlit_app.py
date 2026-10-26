"""Streamlit UI. Run: API_URL=http://localhost:8000 streamlit run frontend/streamlit_app.py"""
import base64
import json
import os
import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config("AI Workspace", "🧠", layout="wide")


def call(m, path, **k):
    tok = st.session_state.get("tok")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    try:
        r = httpx.request(m, API + path, headers=headers, timeout=60, **k)
    except httpx.ConnectError:
        st.error(
            f"Cannot reach the backend at {API}. Start it with: uvicorn app.main:app --reload")
        return None
    if r.status_code >= 400:
        try:
            st.error(r.json().get("detail", r.text))
        except ValueError:
            st.error(r.text)
        return None
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


if "tok" not in st.session_state:
    st.title("🧠 AI Workspace Platform")
    e, p = st.text_input("Email"), st.text_input("Password", type="password")
    a, b = st.columns(2)
    if a.button("Login", use_container_width=True):
        r = call("POST", "/auth/login", json={"email": e, "password": p})
        if r:
            st.session_state.tok = r["token"]
            st.rerun()
    if b.button("Register", use_container_width=True) and call("POST", "/auth/register", json={"email": e, "password": p}):
        st.success("Registered. Now log in.")
    st.stop()

with st.sidebar:
    st.header("Workspaces")
    wss = call("GET", "/workspaces") or []
    ws = st.selectbox("Workspace", wss,
                      format_func=lambda w: w["name"]) if wss else None
    nn = st.text_input("New workspace")
    if st.button("Create") and nn and call("POST", "/workspaces", json={"name": nn}):
        st.rerun()
    if st.button("Logout"):
        call("POST", "/auth/logout")
        del st.session_state["tok"]
        st.rerun()
if not ws:
    st.info("Create a workspace to begin.")
    st.stop()
W = f"/workspaces/{ws['id']}"
st.title(ws["name"])
t = st.tabs(["💬 Chat", "📄 Documents", "🧠 Memory", "📚 Prompts",
            "🛠 Skills", "⚙ Assistant", "📊 Dashboard"])

with t[0]:
    sq = st.text_input("Search conversations")
    cons = call("GET", f"{W}/conversations", params={"search": sq}) or []
    c1, c2 = st.columns([3, 1])
    if c2.button("➕ New chat"):
        call("POST", f"{W}/conversations", json={"title": "New chat"})
        st.rerun()
    cv = c1.selectbox("Conversation", cons, format_func=lambda c:
                      f"{c['title']} · {c['session_id'][:6]}") if cons else None
    if cv:
        a, b, d = st.columns([3, 1, 1])
        nt = a.text_input("Rename", cv["title"])
        if b.button("Rename"):
            call("PATCH", f"/conversations/{cv['id']}", json={"title": nt})
            st.rerun()
        if d.button("Delete"):
            call("DELETE", f"/conversations/{cv['id']}")
            st.rerun()
        mem = st.toggle("Use long-term memory", True)
        for m in call("GET", f"/conversations/{cv['id']}/messages") or []:
            with st.chat_message(m["role"]):
                st.write(m["content"])
                if json.loads(m["citations"] or "[]"):
                    st.caption("Sources: " +
                               ", ".join(json.loads(m["citations"])))
        if msg := st.chat_input("Message your assistant"):
            if call("POST", f"/conversations/{cv['id']}/chat", json={"message": msg, "use_memory": mem}):
                st.rerun()
        st.download_button("Export Markdown", call(
            "GET", f"/conversations/{cv['id']}/export") or "", f"{cv['title']}.md")

with t[1]:
    f = st.file_uploader("Upload PDF / DOCX / TXT / MD",
                         type=["pdf", "docx", "txt", "md"])
    if f and st.button("Index document"):
        r = call("POST", f"{W}/documents", json={"filename": f.name,
                 "content_b64": base64.b64encode(f.read()).decode()})
        if r:
            st.success(f"Indexed {r['chunks']} chunks")
    for d in call("GET", f"{W}/documents") or []:
        st.write(f"**{d['filename']}** — {d['summary']}")
    qs = st.text_input("Semantic search")
    if qs:
        for h in call("POST", f"{W}/search", json={"query": qs}) or []:
            st.write(f"`{h['filename']}#{h['chunk']}` score {h['score']}")
            st.caption(h["text"][:300])

with t[2]:
    mc, mp = st.text_input("Memory item"), st.checkbox("Pin")
    if st.button("Save memory") and mc:
        call("POST", f"{W}/memory", json={"content": mc, "pinned": mp})
        st.rerun()
    for m in call("GET", f"{W}/memory") or []:
        st.write(("📌 " if m["pinned"] else "• ") + m["content"])

with t[3]:
    cat = st.selectbox("Category", [
                       "Writing", "Programming", "Research", "Business", "Education", "Custom"])
    pt, pb = st.text_input("Title"), st.text_area("Prompt body")
    if st.button("Save prompt") and pt and pb:
        call("POST", f"{W}/prompts",
             json={"category": cat, "title": pt, "body": pb})
        st.rerun()
    for p in call("GET", f"{W}/prompts") or []:
        with st.expander(f"[{p['category']}] {p['title']}"):
            st.code(p["body"], language=None)
            if st.button("Delete", key=f"dp{p['id']}"):
                call("DELETE", f"{W}/prompts/{p['id']}")
                st.rerun()

with t[4]:
    sk = call("GET", "/skills") or []
    s = st.selectbox(
        "Skill", sk, format_func=lambda s: f"{s['name']} — {s['description']}") if sk else None
    ti = st.text_area("Input")
    if s and st.button("Run skill") and ti:
        st.write(
            call("POST", f"{W}/skills/{s['name']}/run", json={"input": ti})["output"])

with t[5]:
    a = call("GET", f"{W}/assistant") or {}
    if a:
        n = {k: st.text_input(k, a[k]) for k in [
            "name", "role", "model", "personality", "style"]}
        n["system_prompt"] = st.text_area("system_prompt", a["system_prompt"])
        n["temperature"] = st.slider(
            "temperature", 0.0, 2.0, float(a["temperature"]))
        n["max_tokens"] = st.number_input(
            "max_tokens", 1, 4096, int(a["max_tokens"]))
        if st.button("Save assistant") and call("PUT", f"{W}/assistant", json=n):
            st.success("Saved")

with t[6]:
    d = call("GET", f"{W}/dashboard") or {}
    if d:
        cols = st.columns(6)
        for col, (k, v) in zip(cols, [("Chats", d["conversations"]), ("Docs", d["documents"]), ("Memory", d["memory_items"]),
                                      ("Prompts", d["prompt_templates"]), ("Tokens", d["tokens"]), ("Est. cost $", d["estimated_cost"])]):
            col.metric(k, v)
        st.dataframe(d["recent_activity"])
