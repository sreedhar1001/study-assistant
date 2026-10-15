import hmac
import json
import os
import random
import sqlite3
from functools import wraps

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-development-secret")
DB_PATH = "studyguide.db"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                source_quote TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(note_id) REFERENCES notes(id)
            )
        """)


init_db()


def require_login(api=False):
    """Use this decorator to protect app pages and API routes."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                if api:
                    return jsonify({"error": "Please log in."}), 401
                return redirect(url_for("home"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


LOGIN_PAGE = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Study Guide Login</title>
<style>
body{font:16px system-ui;max-width:420px;margin:12vh auto;padding:20px}
input,button{font:inherit;padding:10px;width:100%;box-sizing:border-box;margin:8px 0}
.error{color:#b00}
</style></head>
<body>
<h1>Living Study Guide</h1>
<p>Enter your app password to continue.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post" action="/login">
<input type="password" name="password" placeholder="App password" required>
<button type="submit">Log in</button>
</form>
</body></html>
"""


@app.route("/")
def home():
    if not session.get("logged_in"):
        return render_template_string(LOGIN_PAGE)
    return render_template_string(APP_PAGE)


@app.post("/login")
def login():
    expected = os.environ.get("APP_PASSWORD")
    submitted = request.form.get("password", "")
    if not expected:
        return render_template_string(
            LOGIN_PAGE,
            error="Set APP_PASSWORD in Replit Secrets before logging in."
        )
    if hmac.compare_digest(submitted, expected):
        session["logged_in"] = True
        return redirect(url_for("home"))
    return render_template_string(LOGIN_PAGE, error="Incorrect password."), 401


@app.post("/logout")
@require_login()
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/api/notes")
@require_login(api=True)
def get_notes():
    with db() as conn:
        rows = conn.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/notes")
@require_login(api=True)
def add_note():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()

    if not title or not content:
        return jsonify({"error": "Add both a title and note text."}), 400

    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO notes (title, content) VALUES (?, ?)",
            (title, content)
        )
        note_id = cursor.lastrowid

    return jsonify({"id": note_id, "title": title, "content": content})


@app.post("/api/generate")
@require_login(api=True)
def generate():
    data = request.get_json(force=True)
    note_id = data.get("note_id")
    kind = data.get("kind")

    if kind not in ("flashcard", "quiz"):
        return jsonify({"error": "Choose flashcard or quiz."}), 400

    with db() as conn:
        note = conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()

    if not note:
        return jsonify({"error": "Note not found."}), 404

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "Add OPENAI_API_KEY to Replit Secrets."}), 500

    prompt = f"""
Create up to 5 {kind} study items using ONLY the source text below.
Do not use outside knowledge or infer facts not stated in the source.
For every item, include a source_quote copied exactly from the source.
Keep questions clear and answers concise.
Return JSON in this exact shape:
{{"items":[{{"question":"...","answer":"...","source_quote":"..."}}]}}

SOURCE TEXT:
{note["content"]}
"""

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You create study materials grounded only in the user's provided source."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )
        result = json.loads(response.choices[0].message.content)
        items = result.get("items", [])
    except Exception as exc:
        return jsonify({"error": f"Generation failed: {exc}"}), 500

    saved = []
    with db() as conn:
        for item in items:
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            quote = str(item.get("source_quote", "")).strip()

            # Reject any generated item whose citation is not an exact excerpt.
            if not question or not answer or not quote or quote not in note["content"]:
                continue

            cursor = conn.execute(
                """INSERT INTO cards
                   (note_id, kind, question, answer, source_quote, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (note_id, kind, question, answer, quote)
            )
            saved.append({
                "id": cursor.lastrowid,
                "note_id": note_id,
                "kind": kind,
                "question": question,
                "answer": answer,
                "source_quote": quote,
                "status": "pending",
                "note_title": note["title"],
            })

    return jsonify({
        "created": len(saved),
        "items": saved,
        "message": (
            "Some drafts were skipped because their source quote was not an exact "
            "excerpt of your note."
        ) if len(saved) < len(items) else ""
    })


@app.get("/api/drafts")
@require_login(api=True)
def get_drafts():
    with db() as conn:
        rows = conn.execute("""
            SELECT cards.*, notes.title AS note_title
            FROM cards JOIN notes ON notes.id = cards.note_id
            WHERE cards.status = 'pending'
            ORDER BY cards.id DESC
        """).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/cards/<int:card_id>/<action>")
@require_login(api=True)
def review_card(card_id, action):
    if action not in ("approve", "reject"):
        return jsonify({"error": "Unknown review action."}), 400

    status = "approved" if action == "approve" else "rejected"
    with db() as conn:
        cursor = conn.execute(
            "UPDATE cards SET status = ? WHERE id = ? AND status = 'pending'",
            (status, card_id)
        )
    if cursor.rowcount == 0:
        return jsonify({"error": "Draft not found or already reviewed."}), 404
    return jsonify({"status": status})


@app.get("/api/cards")
@require_login(api=True)
def get_cards():
    search = (request.args.get("q") or "").strip()
    with db() as conn:
        if search:
            like = f"%{search}%"
            rows = conn.execute("""
                SELECT cards.*, notes.title AS note_title
                FROM cards JOIN notes ON notes.id = cards.note_id
                WHERE cards.status = 'approved'
                  AND (cards.question LIKE ? OR cards.answer LIKE ?
                       OR cards.source_quote LIKE ? OR notes.title LIKE ?)
                ORDER BY cards.id DESC
            """, (like, like, like, like)).fetchall()
        else:
            rows = conn.execute("""
                SELECT cards.*, notes.title AS note_title
                FROM cards JOIN notes ON notes.id = cards.note_id
                WHERE cards.status = 'approved'
                ORDER BY cards.id DESC
            """).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/quiz")
@require_login(api=True)
def get_quiz():
    with db() as conn:
        rows = conn.execute("""
            SELECT * FROM cards
            WHERE status = 'approved'
            ORDER BY RANDOM()
            LIMIT 10
        """).fetchall()
    return jsonify([dict(row) for row in rows])


APP_PAGE = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Living Study Guide</title>
<style>
body{font:16px system-ui;max-width:900px;margin:24px auto;padding:0 16px;color:#222}
section,.item{border:1px solid #ddd;border-radius:10px;padding:16px;margin:16px 0}
textarea,input,select,button{font:inherit;padding:9px;box-sizing:border-box}
textarea{width:100%;min-height:120px}
input[type=text]{width:100%}
button{cursor:pointer;margin:4px 4px 4px 0}
.source{background:#f3f5f7;padding:10px;border-left:4px solid #74849a}
.muted{color:#666;font-size:.92em}
.error{color:#b00}
header{display:flex;justify-content:space-between;align-items:center}
</style>
</head>
<body>
<header>
<h1>Living Study Guide</h1>
<form method="post" action="/logout"><button>Log out</button></form>
</header>
<p class="muted">AI drafts stay pending until you approve them. Only approved items appear in your library and quiz.</p>

<section>
<h2>1. Add your notes</h2>
<input id="title" type="text" placeholder="Note title">
<p><textarea id="content" placeholder="Paste your trusted notes here"></textarea></p>
<button onclick="addNote()">Save notes</button>
<span id="noteMsg" class="muted"></span>
</section>

<section>
<h2>2. Generate drafts</h2>
<select id="noteSelect"></select>
<button onclick="generateItems('flashcard')">Generate flashcards</button>
<button onclick="generateItems('quiz')">Generate quiz questions</button>
<div id="drafts"></div>
</section>

<section>
<h2>3. Approved library</h2>
<input id="search" type="text" placeholder="Search questions, answers, sources, or note titles"
       oninput="loadLibrary()">
<div id="library"></div>
</section>

<section>
<h2>4. Quiz yourself</h2>
<button onclick="startQuiz()">Start quiz</button>
<div id="quiz"></div>
</section>

<script>
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url, options={}) {
  const res = await fetch(url, {
    headers: {"Content-Type":"application/json"},
    ...options
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}
async function loadNotes() {
  const notes = await api("/api/notes");
  const select = document.getElementById("noteSelect");
  select.innerHTML = notes.length
    ? notes.map(n => `<option value="${n.id}">${esc(n.title)}</option>`).join("")
    : `<option value="">Add a note first</option>`;
}
async function addNote() {
  try {
    const note = await api("/api/notes", {method:"POST", body:JSON.stringify({
      title:document.getElementById("title").value,
      content:document.getElementById("content").value
    })});
    document.getElementById("noteMsg").textContent = "Saved.";
    document.getElementById("title").value = "";
    document.getElementById("content").value = "";
    await loadNotes();
    document.getElementById("noteSelect").value = note.id;
  } catch(e) {
    document.getElementById("noteMsg").textContent = e.message;
  }
}
async function generateItems(kind) {
  const noteId = document.getElementById("noteSelect").value;
  if (!noteId) return alert("Add a note first.");
  const box = document.getElementById("drafts");
  box.textContent = "Generating…";
  try {
    const result = await api("/api/generate", {
      method:"POST", body:JSON.stringify({note_id:noteId, kind})
    });
    box.innerHTML = `<p>${result.created} draft(s) created. ${esc(result.message)}</p>`;
    await loadDrafts();
  } catch(e) { box.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
async function loadDrafts() {
  const items = await api("/api/drafts");
  const box = document.getElementById("drafts");
  if (!items.length) {
    box.innerHTML = "<p class='muted'>No drafts waiting for review.</p>";
    return;
  }
  box.innerHTML = items.map(x => `
    <article class="item">
      <p class="muted">${esc(x.note_title)} · ${esc(x.kind)}</p>
      <h3>${esc(x.question)}</h3>
      <p><b>Answer:</b> ${esc(x.answer)}</p>
      <p class="source"><b>Source:</b> ${esc(x.source_quote)}</p>
      <button onclick="review(${x.id},'approve')">Approve</button>
      <button onclick="review(${x.id},'reject')">Reject</button>
    </article>`).join("");
}
async function review(id, action) {
  try {
    await api(`/api/cards/${id}/${action}`, {method:"POST"});
    await loadDrafts();
    await loadLibrary();
  } catch(e) { alert(e.message); }
}
async function loadLibrary() {
  const q = document.getElementById("search").value;
  const items = await api("/api/cards?q=" + encodeURIComponent(q));
  const box = document.getElementById("library");
  box.innerHTML = items.length ? items.map(x => `
    <article class="item">
      <p class="muted">${esc(x.note_title)} · ${esc(x.kind)}</p>
      <h3>${esc(x.question)}</h3>
      <p><b>Answer:</b> ${esc(x.answer)}</p>
      <p class="source"><b>Source:</b> ${esc(x.source_quote)}</p>
    </article>`).join("") : "<p class='muted'>No approved cards found.</p>";
}
let quizItems = [], quizIndex = 0;
async function startQuiz() {
  quizItems = await api("/api/quiz");
  quizIndex = 0;
  showQuiz();
}
function showQuiz() {
  const box = document.getElementById("quiz");
  if (!quizItems.length) {
    box.innerHTML = "<p>Approve some cards first.</p>";
    return;
  }
  if (quizIndex >= quizItems.length) {
    box.innerHTML = "<p>Quiz complete! Nice work.</p>";
    return;
  }
  const x = quizItems[quizIndex];
  box.innerHTML = `
    <article class="item">
      <p>Question ${quizIndex+1} of ${quizItems.length}</p>
      <h3>${esc(x.question)}</h3>
      <button onclick="document.getElementById('answer').hidden=false">Show answer</button>
      <p id="answer" hidden><b>Answer:</b> ${esc(x.answer)}
        <span class="source"><br><b>Source:</b> ${esc(x.source_quote)}</span>
      </p>
      <button onclick="quizIndex++;showQuiz()">Next</button>
    </article>`;
}
loadNotes().then(loadDrafts).then(loadLibrary).catch(e => alert(e.message));
</script>
</body></html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)), debug=False)