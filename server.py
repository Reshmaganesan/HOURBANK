"""HourBank backend: a dependency-free Python + SQLite REST API that also serves the frontend.

Run:  python3 server.py   then open http://localhost:8000
"""
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "hourbank.db")
STATIC = os.path.join(BASE, "static")
SEED = os.path.join(BASE, "seed.json")
PORT = int(os.environ.get("PORT", "8000"))

CATEGORIES = ["Tech", "Cooking", "Language", "Music", "Home & Repair",
              "Creative", "Wellness", "Education", "Garden", "Travel"]
STARTING_HOURS = 3.0
MIN_BALANCE = -2.0  # a member may go at most 2 hours into credit
write_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, city TEXT NOT NULL, emoji TEXT NOT NULL,
        bio TEXT NOT NULL DEFAULT '', balance REAL NOT NULL DEFAULT 3,
        created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS listings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id),
        type TEXT NOT NULL CHECK(type IN ('offer','request')),
        title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
        hours REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS exchanges(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL REFERENCES listings(id),
        provider_id INTEGER NOT NULL REFERENCES members(id),
        receiver_id INTEGER NOT NULL REFERENCES members(id),
        hours REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        thanks TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL, completed_at REAL);
    CREATE TABLE IF NOT EXISTS ledger(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id),
        exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
        delta REAL NOT NULL, created_at REAL NOT NULL);
    """)
    if conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn):
    with open(SEED, encoding="utf-8") as f:
        data = json.load(f)
    now = time.time()
    for i, m in enumerate(data["members"]):
        conn.execute(
            "INSERT INTO members(name,city,emoji,bio,balance,created_at) VALUES(?,?,?,?,?,?)",
            (m["name"], m["city"], m["emoji"], m["bio"], STARTING_HOURS,
             now - (40 - i) * 86400))
    total = len(data["listings"])
    for i, l in enumerate(data["listings"]):
        created = now - (total - i) * 5400
        cur = conn.execute(
            "INSERT INTO listings(member_id,type,title,category,description,hours,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (l["owner"], l["type"], l["title"], l["category"], l["description"],
             l["hours"], l["status"], created))
        if l["status"] == "done":
            lid, other = cur.lastrowid, l["done_with"]
            provider, receiver = (l["owner"], other) if l["type"] == "offer" else (other, l["owner"])
            ex = conn.execute(
                "INSERT INTO exchanges(listing_id,provider_id,receiver_id,hours,status,thanks,"
                "created_at,completed_at) VALUES(?,?,?,?,?,?,?,?)",
                (lid, provider, receiver, l["hours"], "completed", l.get("thanks", ""),
                 created, created + 3600)).lastrowid
            settle(conn, ex, provider, receiver, l["hours"], created + 3600)


def settle(conn, exchange_id, provider, receiver, hours, ts):
    conn.execute("UPDATE members SET balance = balance + ? WHERE id=?", (hours, provider))
    conn.execute("UPDATE members SET balance = balance - ? WHERE id=?", (hours, receiver))
    conn.execute("INSERT INTO ledger(member_id,exchange_id,delta,created_at) VALUES(?,?,?,?)",
                 (provider, exchange_id, hours, ts))
    conn.execute("INSERT INTO ledger(member_id,exchange_id,delta,created_at) VALUES(?,?,?,?)",
                 (receiver, exchange_id, -hours, ts))


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


LISTING_SQL = ("SELECT l.*, m.name AS owner_name, m.emoji AS owner_emoji, m.city AS owner_city "
               "FROM listings l JOIN members m ON m.id = l.member_id")
EXCHANGE_SQL = ("SELECT e.*, l.title, l.category, l.type AS listing_type, "
                "p.name AS provider_name, p.emoji AS provider_emoji, "
                "r.name AS receiver_name, r.emoji AS receiver_emoji "
                "FROM exchanges e JOIN listings l ON l.id = e.listing_id "
                "JOIN members p ON p.id = e.provider_id "
                "JOIN members r ON r.id = e.receiver_id")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def num(value, field, lo, hi):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{field} must be a number")
    if not lo <= v <= hi:
        raise ApiError(400, f"{field} must be between {lo} and {hi}")
    return round(v * 2) / 2


def need_member(conn, member_id):
    try:
        mid = int(member_id)
    except (TypeError, ValueError):
        raise ApiError(400, "member_id is required")
    m = conn.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    if not m:
        raise ApiError(404, "Member not found")
    return m


# ---------- route handlers ----------
def get_members(conn, q, body):
    return rows(conn.execute(
        "SELECT m.*, COALESCE((SELECT SUM(hours) FROM exchanges WHERE provider_id=m.id "
        "AND status='completed'),0) AS hours_given FROM members m ORDER BY m.name"))


def get_member(conn, q, body, mid):
    m = need_member(conn, mid)
    out = dict(m)
    out["listings"] = rows(conn.execute(LISTING_SQL + " WHERE l.member_id=? ORDER BY l.id DESC", (m["id"],)))
    out["exchanges"] = rows(conn.execute(
        EXCHANGE_SQL + " WHERE e.provider_id=? OR e.receiver_id=? ORDER BY e.id DESC", (m["id"], m["id"])))
    out["ledger"] = rows(conn.execute(
        "SELECT * FROM ledger WHERE member_id=? ORDER BY id DESC LIMIT 50", (m["id"],)))
    return out


def get_listings(conn, q, body):
    where, args = [], []
    status = q.get("status", ["open"])[0]
    if status != "all":
        where.append("l.status=?"); args.append(status)
    if q.get("type", [""])[0] in ("offer", "request"):
        where.append("l.type=?"); args.append(q["type"][0])
    if q.get("category", [""])[0]:
        where.append("l.category=?"); args.append(q["category"][0])
    if q.get("member_id", [""])[0]:
        where.append("l.member_id=?"); args.append(q["member_id"][0])
    text = q.get("q", [""])[0].strip()
    if text:
        like = f"%{text}%"
        where.append("(l.title LIKE ? OR l.description LIKE ? OR l.category LIKE ? OR m.city LIKE ?)")
        args += [like] * 4
    sql = LISTING_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY l.id DESC"
    return rows(conn.execute(sql, args))


def post_listing(conn, q, body):
    m = need_member(conn, body.get("member_id"))
    ltype = body.get("type")
    if ltype not in ("offer", "request"):
        raise ApiError(400, "type must be 'offer' or 'request'")
    title = str(body.get("title", "")).strip()
    desc = str(body.get("description", "")).strip()
    cat = body.get("category")
    if not 3 <= len(title) <= 80:
        raise ApiError(400, "Title must be 3 to 80 characters")
    if not 10 <= len(desc) <= 500:
        raise ApiError(400, "Description must be 10 to 500 characters")
    if cat not in CATEGORIES:
        raise ApiError(400, "Unknown category")
    hours = num(body.get("hours"), "hours", 0.5, 8)
    cur = conn.execute(
        "INSERT INTO listings(member_id,type,title,category,description,hours,created_at)"
        " VALUES(?,?,?,?,?,?,?)", (m["id"], ltype, title, cat, desc, hours, time.time()))
    return rows(conn.execute(LISTING_SQL + " WHERE l.id=?", (cur.lastrowid,)))[0]


def accept_listing(conn, q, body, lid):
    me = need_member(conn, body.get("member_id"))
    l = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    if not l:
        raise ApiError(404, "Listing not found")
    if l["status"] != "open":
        raise ApiError(409, "This listing is no longer open")
    if l["member_id"] == me["id"]:
        raise ApiError(400, "You cannot accept your own listing")
    provider, receiver = ((l["member_id"], me["id"]) if l["type"] == "offer"
                          else (me["id"], l["member_id"]))
    rec = conn.execute("SELECT balance FROM members WHERE id=?", (receiver,)).fetchone()
    if rec["balance"] - l["hours"] < MIN_BALANCE:
        who = "You do not" if receiver == me["id"] else "The requester does not"
        raise ApiError(400, f"{who} have enough hours for this exchange yet. "
                            "Help someone first to earn more.")
    ex = conn.execute(
        "INSERT INTO exchanges(listing_id,provider_id,receiver_id,hours,created_at) VALUES(?,?,?,?,?)",
        (l["id"], provider, receiver, l["hours"], time.time())).lastrowid
    conn.execute("UPDATE listings SET status='booked' WHERE id=?", (l["id"],))
    return rows(conn.execute(EXCHANGE_SQL + " WHERE e.id=?", (ex,)))[0]


def complete_exchange(conn, q, body, eid):
    ex = conn.execute("SELECT * FROM exchanges WHERE id=?", (eid,)).fetchone()
    if not ex:
        raise ApiError(404, "Exchange not found")
    me = need_member(conn, body.get("member_id"))
    if ex["status"] != "pending":
        raise ApiError(409, "This exchange is already closed")
    if me["id"] != ex["receiver_id"]:
        raise ApiError(403, "Only the person who received help can confirm it")
    thanks = str(body.get("thanks", "")).strip()[:200]
    now = time.time()
    conn.execute("UPDATE exchanges SET status='completed', thanks=?, completed_at=? WHERE id=?",
                 (thanks, now, ex["id"]))
    conn.execute("UPDATE listings SET status='done' WHERE id=?", (ex["listing_id"],))
    settle(conn, ex["id"], ex["provider_id"], ex["receiver_id"], ex["hours"], now)
    return rows(conn.execute(EXCHANGE_SQL + " WHERE e.id=?", (ex["id"],)))[0]


def cancel_exchange(conn, q, body, eid):
    ex = conn.execute("SELECT * FROM exchanges WHERE id=?", (eid,)).fetchone()
    if not ex:
        raise ApiError(404, "Exchange not found")
    me = need_member(conn, body.get("member_id"))
    if ex["status"] != "pending":
        raise ApiError(409, "This exchange is already closed")
    if me["id"] not in (ex["provider_id"], ex["receiver_id"]):
        raise ApiError(403, "Only the two people involved can cancel")
    conn.execute("UPDATE exchanges SET status='cancelled' WHERE id=?", (ex["id"],))
    conn.execute("UPDATE listings SET status='open' WHERE id=?", (ex["listing_id"],))
    return {"ok": True}


def get_activity(conn, q, body):
    return rows(conn.execute(
        EXCHANGE_SQL + " WHERE e.status='completed' ORDER BY e.completed_at DESC LIMIT 12"))


def get_stats(conn, q, body):
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "members": one("SELECT COUNT(*) FROM members"),
        "open_listings": one("SELECT COUNT(*) FROM listings WHERE status='open'"),
        "hours_exchanged": one("SELECT COALESCE(SUM(hours),0) FROM exchanges WHERE status='completed'"),
        "exchanges": one("SELECT COUNT(*) FROM exchanges WHERE status='completed'"),
        "categories": CATEGORIES,
    }


ROUTES = [
    ("GET", r"^/api/members$", get_members),
    ("GET", r"^/api/members/(\d+)$", get_member),
    ("GET", r"^/api/listings$", get_listings),
    ("POST", r"^/api/listings$", post_listing),
    ("POST", r"^/api/listings/(\d+)/accept$", accept_listing),
    ("POST", r"^/api/exchanges/(\d+)/complete$", complete_exchange),
    ("POST", r"^/api/exchanges/(\d+)/cancel$", cancel_exchange),
    ("GET", r"^/api/activity$", get_activity),
    ("GET", r"^/api/stats$", get_stats),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "HourBank/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, method):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            for m, pattern, fn in ROUTES:
                match = re.match(pattern, url.path)
                if m == method and match:
                    return self.run_api(fn, url, match.groups())
            return self.send_json(404, {"error": "Not found"})
        if method == "GET":
            return self.serve_static(url.path)
        self.send_json(405, {"error": "Method not allowed"})

    def run_api(self, fn, url, args):
        body = {}
        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > 20000:
                return self.send_json(413, {"error": "Request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"error": "Invalid JSON body"})
        try:
            with write_lock:
                conn = db()
                try:
                    result = fn(conn, parse_qs(url.query), body, *args)
                    conn.commit()
                finally:
                    conn.close()
            self.send_json(201 if self.command == "POST" else 200, result)
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except Exception as e:  # pragma: no cover
            self.send_json(500, {"error": f"Server error: {e}"})

    def serve_static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self.send_json(404, {"error": "Not found"})
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")


if __name__ == "__main__":
    init_db()
    print(f"HourBank running at http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
