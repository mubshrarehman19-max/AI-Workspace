"""Config, logging, database abstraction, password hashing."""
import hashlib, hmac, logging, os, secrets, sqlite3
from typing import Any, Iterator

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("aiws")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, pw_hash TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INT, created_at REAL);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY, user_id INT, name TEXT, prompt TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS settings(workspace_id INT PRIMARY KEY, name TEXT, role TEXT, system_prompt TEXT, model TEXT,
  temperature REAL, max_tokens INT, personality TEXT, style TEXT);
CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, workspace_id INT, session_id TEXT, title TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id INT, role TEXT, content TEXT, citations TEXT, tokens INT, created_at REAL);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, workspace_id INT, filename TEXT, summary TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, document_id INT, workspace_id INT, idx INT, text TEXT);
CREATE TABLE IF NOT EXISTS embeddings(chunk_id INTEGER PRIMARY KEY, vector TEXT);
CREATE TABLE IF NOT EXISTS prompt_templates(id INTEGER PRIMARY KEY, workspace_id INT, category TEXT, title TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, description TEXT, template TEXT);
CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY, workspace_id INT, content TEXT, pinned INT DEFAULT 0, created_at REAL);
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, workspace_id INT, event TEXT, tokens INT DEFAULT 0, cost REAL DEFAULT 0, latency REAL DEFAULT 0, created_at REAL);
"""

SKILLS = {
    "research": ("Structured research brief", "Research the topic and give key findings, open questions and next steps:\n{input}"),
    "summarize": ("Concise summary", "Summarize in 5 bullet points:\n{input}"),
    "email": ("Professional email writer", "Write a clear professional email for:\n{input}"),
    "report": ("Report generator", "Write a report with headings (Overview, Findings, Recommendations) on:\n{input}"),
    "meeting_notes": ("Meeting notes extractor", "Extract decisions, action items and owners from:\n{input}"),
    "ideas": ("Idea generator", "Generate 10 distinct ideas for:\n{input}"),
    "task_plan": ("Task planner", "Break into prioritized tasks with estimates:\n{input}"),
    "swot": ("SWOT generator", "Produce a SWOT analysis for:\n{input}"),
}


def _path() -> str:
    return os.getenv("DB_PATH", "workspace.db")


def init_db() -> None:
    c = sqlite3.connect(_path())
    c.executescript(SCHEMA)
    for n, (d, t) in SKILLS.items():
        c.execute("INSERT OR IGNORE INTO skills VALUES(?,?,?)", (n, d, t))
    c.commit(); c.close()


def get_db() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(_path()); c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def q(db: sqlite3.Connection, sql: str, *a: Any) -> list[dict]:
    return [dict(r) for r in db.execute(sql, a).fetchall()]


def x(db: sqlite3.Connection, sql: str, *a: Any) -> int:
    cur = db.execute(sql, a); db.commit(); return cur.lastrowid or 0


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


def check_pw(pw: str, stored: str) -> bool:
    return hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)
