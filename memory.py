"""Encrypted memory DB. Every payload is AES-GCM encrypted; only id/time/kind/lang are plaintext.
Kinds: pref (style rule), note (user teaching), accepted / rejected (Yes/No decisions),
chat (Q&A log), backup (original file before an edit)."""
import json, re, sqlite3, threading, time

RETRIEVE = ("pref", "note", "accepted", "rejected", "chat")
_tok = re.compile(r"[a-z0-9_]{3,}")


def _words(s):
    return set(_tok.findall(s.lower()))


class Memory:
    def __init__(self, path, vault):
        self.v = vault
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS mem(id INTEGER PRIMARY KEY, ts REAL, "
                        "kind TEXT, lang TEXT, blob BLOB)")
        self.db.commit()

    def add(self, kind, data, lang=""):
        blob = self.v.encrypt(json.dumps(data).encode(), kind.encode())
        with self.lock:
            cur = self.db.execute("INSERT INTO mem(ts,kind,lang,blob) VALUES(?,?,?,?)",
                                  (time.time(), kind, lang, blob))
            self.db.commit()
            return cur.lastrowid

    def _row(self, r):
        return {"id": r[0], "ts": r[1], "kind": r[2], "lang": r[3],
                "data": json.loads(self.v.decrypt(r[4], r[2].encode()))}

    def list(self, kind=None, limit=50):
        q, a = "SELECT id,ts,kind,lang,blob FROM mem", []
        if kind:
            q, a = q + " WHERE kind=?", [kind]
        with self.lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", a + [limit]).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, mem_id):
        with self.lock:
            n = self.db.execute("DELETE FROM mem WHERE id=?", (mem_id,)).rowcount
            self.db.commit()
        return n > 0

    @staticmethod
    def text_of(row):
        d = row["data"]
        return d.get("text") or d.get("reason") or d.get("q") or d.get("path") or ""

    def search(self, query, lang="", kinds=RETRIEVE, k=5):
        qw, out = _words(query), []
        with self.lock:
            marks = ",".join("?" * len(kinds))
            rows = self.db.execute(
                f"SELECT id,ts,kind,lang,blob FROM mem WHERE kind IN ({marks}) "
                "ORDER BY id DESC LIMIT 400", list(kinds)).fetchall()
        for i, r in enumerate(rows):
            row = self._row(r)
            d = row["data"]
            blob = " ".join(str(x) for x in d.values())
            score = len(qw & _words(blob)) + (1.5 if lang and row["lang"] == lang else 0) \
                + (2 if row["kind"] == "pref" else 0) - i * 0.002
            if score > 0.5:
                out.append((score, row))
        out.sort(key=lambda t: -t[0])
        return [r for _, r in out[:k]]

    def context_for(self, lang, query):
        """Text block injected into Qwen's prompt so it follows what it has been taught."""
        parts = []
        for r in self.search(query, lang, k=6):
            d, kind = r["data"], r["kind"]
            if kind in ("pref", "note"):
                parts.append(f"- {d.get('text', '')[:300]}")
            elif kind == "rejected" and d.get("reason"):
                parts.append(f"- Avoid (user rejected before): {d['reason'][:200]}")
            elif kind == "accepted":
                parts.append("- Example the user approved:\nBEFORE:\n%s\nAFTER:\n%s"
                             % (d.get("before", "")[:600], d.get("after", "")[:600]))
            elif kind == "chat":
                parts.append(f"- Earlier: Q: {d.get('q', '')[:150]} A: {d.get('a', '')[:250]}")
        return ("\nThings you have learned about this user:\n" + "\n".join(parts)) if parts else ""
