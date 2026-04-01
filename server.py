#!/usr/bin/env python3
import base64
import json
import os
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import cgi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "data.db")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def init_db():
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_name TEXT,
                person_name TEXT,
                touse INTEGER NOT NULL DEFAULT 0,
                bouse INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS votes (
                image_id INTEGER NOT NULL,
                voter_id TEXT NOT NULL,
                vote TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (image_id, voter_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                upvotes INTEGER NOT NULL DEFAULT 0,
                downvotes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comment_votes (
                comment_id INTEGER NOT NULL,
                voter_id TEXT NOT NULL,
                vote TEXT NOT NULL,
                PRIMARY KEY (comment_id, voter_id)
            )
            """
        )
        # Lightweight migration for existing DBs.
        columns = [row[1] for row in conn.execute("PRAGMA table_info(images)")]
        if "person_name" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN person_name TEXT")
        if "affiliation" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN affiliation TEXT")
        comment_cols = [row[1] for row in conn.execute("PRAGMA table_info(comments)")]
        if "upvotes" not in comment_cols:
            conn.execute("ALTER TABLE comments ADD COLUMN upvotes INTEGER NOT NULL DEFAULT 0")
        if "downvotes" not in comment_cols:
            conn.execute("ALTER TABLE comments ADD COLUMN downvotes INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    if ext == ".css":
        return "text/css; charset=utf-8"
    if ext == ".js":
        return "application/javascript; charset=utf-8"
    if ext == ".html":
        return "text/html; charset=utf-8"
    return "application/octet-stream"


def safe_join(base, *paths):
    new_path = os.path.abspath(os.path.join(base, *paths))
    if not new_path.startswith(base):
        return None
    return new_path


class Handler(BaseHTTPRequestHandler):
    server_version = "TouseBouseServer/0.2"

    def _ensure_voter(self):
        cookie = self.headers.get("Cookie", "")
        voter_id = None
        for part in cookie.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            if key == "voter_id":
                voter_id = value
                break
        if not voter_id:
            voter_id = uuid.uuid4().hex
            self._set_cookie = f"voter_id={voter_id}; Path=/; Max-Age=31536000"
        else:
            self._set_cookie = None
        self._voter_id = voter_id

    def _send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if hasattr(self, "_set_cookie") and self._set_cookie:
            self.send_header("Set-Cookie", self._set_cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if hasattr(self, "_set_cookie") and self._set_cookie:
            self.send_header("Set-Cookie", self._set_cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, content_type=None):
        if not os.path.isfile(path):
            self._send_text("Not found", status=404)
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type or guess_mime(path))
        if hasattr(self, "_set_cookie") and self._set_cookie:
            self.send_header("Set-Cookie", self._set_cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._ensure_voter()
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self._serve_file(os.path.join(PUBLIC_DIR, "index.html"))
            return
        if parsed.path.startswith("/uploads/"):
            rel = parsed.path[len("/uploads/"):]
            safe_path = safe_join(UPLOADS_DIR, rel)
            if safe_path is None:
                self._send_text("Bad path", status=400)
                return
            self._serve_file(safe_path)
            return
        if parsed.path.startswith("/public/"):
            rel = parsed.path[len("/public/"):]
            safe_path = safe_join(PUBLIC_DIR, rel)
            if safe_path is None:
                self._send_text("Bad path", status=400)
                return
            self._serve_file(safe_path)
            return
        if parsed.path == "/api/random":
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT * FROM images
                    WHERE person_name IS NOT NULL AND TRIM(person_name) != ''
                    ORDER BY RANDOM()
                    LIMIT 1
                    """
                ).fetchone()
            if row is None:
                self._send_json({"empty": True})
                return
            with sqlite3.connect(DB_PATH) as conn:
                vote_row = conn.execute(
                    "SELECT vote FROM votes WHERE image_id = ? AND voter_id = ?",
                    (row["id"], self._voter_id),
                ).fetchone()
            my_vote = vote_row[0] if vote_row else None
            self._send_json(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "original_name": row["original_name"],
                    "person_name": row["person_name"],
                    "affiliation": row["affiliation"],
                    "touse": row["touse"],
                    "bouse": row["bouse"],
                    "my_vote": my_vote,
                }
            )
            return
        if parsed.path == "/api/image":
            qs = parse_qs(parsed.query)
            image_id = qs.get("id", [None])[0]
            if image_id is None:
                self._send_json({"error": "missing id"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM images WHERE id = ?", (image_id,)
                ).fetchone()
            if row is None:
                self._send_json({"empty": True})
                return
            with sqlite3.connect(DB_PATH) as conn:
                vote_row = conn.execute(
                    "SELECT vote FROM votes WHERE image_id = ? AND voter_id = ?",
                    (row["id"], self._voter_id),
                ).fetchone()
            my_vote = vote_row[0] if vote_row else None
            self._send_json({
                "id": row["id"],
                "filename": row["filename"],
                "original_name": row["original_name"],
                "person_name": row["person_name"],
                "affiliation": row["affiliation"],
                "touse": row["touse"],
                "bouse": row["bouse"],
                "my_vote": my_vote,
            })
            return
        if parsed.path == "/api/search":
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0].strip()
            affil_filter = qs.get("affiliation", [""])[0].strip()
            if not q and not affil_filter:
                self._send_json([])
                return
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                params = []
                where = ["person_name IS NOT NULL", "TRIM(person_name) != ''"]
                if q:
                    where.append("person_name LIKE ?")
                    params.append(f"%{q}%")
                if affil_filter:
                    where.append("affiliation = ?")
                    params.append(affil_filter)
                rows = conn.execute(
                    f"""
                    SELECT id, filename, person_name, affiliation, touse, bouse,
                           (touse + bouse) AS total
                    FROM images
                    WHERE {' AND '.join(where)}
                    ORDER BY (touse + bouse) DESC
                    LIMIT 20
                    """,
                    params,
                ).fetchall()
            self._send_json([
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "person_name": r["person_name"],
                    "affiliation": r["affiliation"],
                    "touse": r["touse"],
                    "bouse": r["bouse"],
                    "total": r["total"],
                }
                for r in rows
            ])
            return
        if parsed.path == "/api/results":
            qs = parse_qs(parsed.query)
            image_id = qs.get("id", [None])[0]
            if image_id is None:
                self._send_json({"error": "missing id"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT id, touse, bouse FROM images WHERE id = ?",
                    (image_id,),
                ).fetchone()
            if row is None:
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_json({"id": row["id"], "touse": row["touse"], "bouse": row["bouse"]})
            return
        if parsed.path == "/api/leaderboard":
            qs = parse_qs(parsed.query)
            try:
                limit = int(qs.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100
            affil_filter = qs.get("affiliation", [""])[0].strip()
            affil_clause = "AND affiliation = ?" if affil_filter else ""
            affil_params = [affil_filter] if affil_filter else []
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                total_count = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM images
                    WHERE person_name IS NOT NULL AND TRIM(person_name) != ''
                    {affil_clause}
                    """,
                    affil_params,
                ).fetchone()[0]
                base_query = f"""
                    SELECT id, filename, person_name, affiliation, touse, bouse,
                           (touse + bouse) AS total
                    FROM images
                    WHERE person_name IS NOT NULL AND TRIM(person_name) != ''
                    {affil_clause}
                    ORDER BY {{order}}
                    LIMIT ?
                """
                overall_rows = conn.execute(
                    base_query.format(order="touse DESC, bouse ASC, (touse + bouse) DESC, person_name COLLATE NOCASE ASC"),
                    affil_params + [limit],
                ).fetchall()
                touser_rows = conn.execute(
                    base_query.format(order="touse DESC, (touse + bouse) DESC, person_name COLLATE NOCASE ASC"),
                    affil_params + [limit],
                ).fetchall()
                bouser_rows = conn.execute(
                    base_query.format(order="bouse DESC, (touse + bouse) DESC, person_name COLLATE NOCASE ASC"),
                    affil_params + [limit],
                ).fetchall()

            def serialize(rows):
                return [
                    {
                        "id": row["id"],
                        "filename": row["filename"],
                        "person_name": row["person_name"],
                        "affiliation": row["affiliation"],
                        "touse": row["touse"],
                        "bouse": row["bouse"],
                        "total": row["total"],
                    }
                    for row in rows
                ]

            response = {
                "overall": serialize(overall_rows),
                "top_tousers": serialize(touser_rows),
                "top_bousers": serialize(bouser_rows),
                "meta": {
                    "limit": limit,
                    "total_count": total_count,
                },
            }
            self._send_json(response)
            return
        if parsed.path == "/api/version":
            self._send_json(
                {
                    "server_version": self.server_version,
                    "db_path": DB_PATH,
                }
            )
            return
        if parsed.path == "/api/comments":
            qs = parse_qs(parsed.query)
            image_id = qs.get("id", [None])[0]
            if image_id is None:
                self._send_json({"error": "missing id"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, text, upvotes, downvotes, created_at FROM comments WHERE image_id = ? ORDER BY (upvotes - downvotes) DESC, created_at ASC",
                    (image_id,),
                ).fetchall()
                comment_ids = [r["id"] for r in rows]
                my_votes = {}
                if comment_ids:
                    placeholders = ",".join("?" * len(comment_ids))
                    for cv in conn.execute(
                        f"SELECT comment_id, vote FROM comment_votes WHERE comment_id IN ({placeholders}) AND voter_id = ?",
                        (*comment_ids, self._voter_id),
                    ).fetchall():
                        my_votes[cv["comment_id"]] = cv["vote"]
            self._send_json([
                {
                    "id": r["id"],
                    "text": r["text"],
                    "upvotes": r["upvotes"],
                    "downvotes": r["downvotes"],
                    "my_vote": my_votes.get(r["id"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ])
            return

        self._send_text("Not found", status=404)

    def do_POST(self):
        self._ensure_voter()
        parsed = urlparse(self.path)
        if parsed.path == "/api/vote":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({"error": "invalid json"}, status=400)
                return
            image_id = payload.get("image_id")
            vote = payload.get("vote")
            if not image_id or vote not in {"touse", "bouse"}:
                self._send_json({"error": "bad payload"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT vote FROM votes WHERE image_id = ? AND voter_id = ?",
                    (image_id, self._voter_id),
                ).fetchone()
                if existing is None:
                    if vote == "touse":
                        conn.execute("UPDATE images SET touse = touse + 1 WHERE id = ?", (image_id,))
                    else:
                        conn.execute("UPDATE images SET bouse = bouse + 1 WHERE id = ?", (image_id,))
                    conn.execute(
                        "INSERT INTO votes (image_id, voter_id, vote, created_at) VALUES (?, ?, ?, ?)",
                        (image_id, self._voter_id, vote, time.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                else:
                    prev = existing[0]
                    if prev != vote:
                        if prev == "touse":
                            conn.execute("UPDATE images SET touse = MAX(touse - 1, 0) WHERE id = ?", (image_id,))
                        else:
                            conn.execute("UPDATE images SET bouse = MAX(bouse - 1, 0) WHERE id = ?", (image_id,))
                        if vote == "touse":
                            conn.execute("UPDATE images SET touse = touse + 1 WHERE id = ?", (image_id,))
                        else:
                            conn.execute("UPDATE images SET bouse = bouse + 1 WHERE id = ?", (image_id,))
                        conn.execute(
                            "UPDATE votes SET vote = ?, created_at = ? WHERE image_id = ? AND voter_id = ?",
                            (vote, time.strftime("%Y-%m-%d %H:%M:%S"), image_id, self._voter_id),
                        )
                conn.commit()
                row = conn.execute(
                    "SELECT touse, bouse FROM images WHERE id = ?",
                    (image_id,),
                ).fetchone()
            if row is None:
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_json({"touse": row[0], "bouse": row[1]})
            return

        if parsed.path == "/api/upload":
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("application/json"):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._send_json({"error": "invalid json"}, status=400)
                    return
                person_name = str(payload.get("name", "")).strip()
                affiliation = str(payload.get("affiliation", "")).strip() or None
                filename = str(payload.get("filename", "")).strip()
                data_url = str(payload.get("data_url", "")).strip()
                if not person_name:
                    self._send_json({"error": "missing name"}, status=400)
                    return
                if not filename or not data_url:
                    self._send_json({"error": "missing file"}, status=400)
                    return
                if not data_url.startswith("data:") or ";base64," not in data_url:
                    self._send_json({"error": "invalid image data"}, status=400)
                    return
                header, b64data = data_url.split(";base64,", 1)
                mime = header.replace("data:", "")
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    ext = MIME_EXT.get(mime, "")
                if ext not in ALLOWED_EXTENSIONS:
                    self._send_json({"error": "unsupported file type"}, status=400)
                    return
                try:
                    binary = base64.b64decode(b64data)
                except Exception:
                    self._send_json({"error": "invalid image data"}, status=400)
                    return
                if len(binary) > MAX_UPLOAD_BYTES:
                    self._send_json({"error": "file too large"}, status=413)
                    return
                safe_name = f"{uuid.uuid4().hex}{ext}"
                target_path = os.path.join(UPLOADS_DIR, safe_name)
                with open(target_path, "wb") as f:
                    f.write(binary)
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "INSERT INTO images (filename, original_name, person_name, affiliation, created_at) VALUES (?, ?, ?, ?, ?)",
                        (safe_name, os.path.basename(filename), person_name, affiliation, time.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    conn.commit()
                self._send_json({"ok": True, "filename": safe_name, "person_name": person_name})
                return

            if "multipart/form-data" not in content_type:
                self._send_json({"error": "expected multipart form"}, status=400)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > MAX_UPLOAD_BYTES:
                self._send_json({"error": "file too large"}, status=413)
                return
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                    "CONTENT_LENGTH": str(content_length),
                },
            )
            if "file" not in form:
                self._send_json({"error": "missing file"}, status=400)
                return
            file_item = form["file"]
            if isinstance(file_item, list):
                self._send_json({"error": "only one image allowed"}, status=400)
                return
            if not getattr(file_item, "filename", None):
                self._send_json({"error": "missing filename"}, status=400)
                return
            person_name = form.getfirst("name", "") or form.getfirst("person_name", "")
            person_name = person_name.strip()
            if not person_name:
                self._send_json({"error": "missing name"}, status=400)
                return
            original_name = os.path.basename(file_item.filename)
            ext = os.path.splitext(original_name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                self._send_json({"error": "unsupported file type"}, status=400)
                return
            safe_name = f"{uuid.uuid4().hex}{ext}"
            target_path = os.path.join(UPLOADS_DIR, safe_name)
            with open(target_path, "wb") as f:
                f.write(file_item.file.read())
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO images (filename, original_name, person_name, created_at) VALUES (?, ?, ?, ?)",
                    (safe_name, original_name, person_name, time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            self._send_json({"ok": True, "filename": safe_name, "person_name": person_name})
            return

        if parsed.path == "/api/comment":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({"error": "invalid json"}, status=400)
                return
            image_id = payload.get("image_id")
            text = str(payload.get("text", "")).strip()
            if not image_id or not text:
                self._send_json({"error": "missing fields"}, status=400)
                return
            if len(text) > 200:
                self._send_json({"error": "comment too long (max 200 chars)"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO comments (image_id, text, created_at) VALUES (?, ?, ?)",
                    (image_id, text, time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/comment/vote":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({"error": "invalid json"}, status=400)
                return
            comment_id = payload.get("comment_id")
            vote = payload.get("vote")
            if not comment_id or vote not in {"up", "down"}:
                self._send_json({"error": "bad payload"}, status=400)
                return
            with sqlite3.connect(DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT vote FROM comment_votes WHERE comment_id = ? AND voter_id = ?",
                    (comment_id, self._voter_id),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO comment_votes (comment_id, voter_id, vote) VALUES (?, ?, ?)",
                        (comment_id, self._voter_id, vote),
                    )
                    if vote == "up":
                        conn.execute("UPDATE comments SET upvotes = upvotes + 1 WHERE id = ?", (comment_id,))
                    else:
                        conn.execute("UPDATE comments SET downvotes = downvotes + 1 WHERE id = ?", (comment_id,))
                elif existing[0] == vote:
                    conn.execute(
                        "DELETE FROM comment_votes WHERE comment_id = ? AND voter_id = ?",
                        (comment_id, self._voter_id),
                    )
                    if vote == "up":
                        conn.execute("UPDATE comments SET upvotes = MAX(upvotes - 1, 0) WHERE id = ?", (comment_id,))
                    else:
                        conn.execute("UPDATE comments SET downvotes = MAX(downvotes - 1, 0) WHERE id = ?", (comment_id,))
                else:
                    conn.execute(
                        "UPDATE comment_votes SET vote = ? WHERE comment_id = ? AND voter_id = ?",
                        (vote, comment_id, self._voter_id),
                    )
                    if vote == "up":
                        conn.execute("UPDATE comments SET upvotes = upvotes + 1, downvotes = MAX(downvotes - 1, 0) WHERE id = ?", (comment_id,))
                    else:
                        conn.execute("UPDATE comments SET downvotes = downvotes + 1, upvotes = MAX(upvotes - 1, 0) WHERE id = ?", (comment_id,))
                conn.commit()
                row = conn.execute("SELECT upvotes, downvotes FROM comments WHERE id = ?", (comment_id,)).fetchone()
            if row is None:
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_json({"upvotes": row[0], "downvotes": row[1]})
            return

        self._send_text("Not found", status=404)


def run(host="127.0.0.1", port=8000):
    init_db()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    run(host, port)