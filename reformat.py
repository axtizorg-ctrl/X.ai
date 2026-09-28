"""Ask Qwen to reformat a file, verify it changed formatting only, apply only after Yes."""
import ast, difflib, hashlib, json, os, re
from dataclasses import dataclass

LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "javascript",
         ".tsx": "typescript", ".json": "json", ".html": "html", ".css": "css", ".kv": "kv",
         ".java": "java", ".kt": "kotlin", ".c": "c", ".h": "c", ".cpp": "cpp", ".go": "go",
         ".rs": "rust", ".sh": "shell", ".md": "markdown", ".yml": "yaml", ".yaml": "yaml",
         ".xml": "xml", ".php": "php", ".rb": "ruby"}
MAX_BYTES = 24_000    # small on-device models lose the plot on big files

SYSTEM = ("You are a code formatter. Reformat the code the user sends: indentation, spacing, "
          "line breaks, blank lines, consistent style. Do NOT rename anything, do NOT add, remove "
          "or reorder logic, do NOT add comments. Reply with ONLY the complete reformatted code - "
          "no explanations and no markdown fences.")


@dataclass
class Proposal:
    path: str
    before: str
    after: str
    diff: str
    safe: bool
    note: str
    digest: str


def lang_of(path):
    return LANGS.get(os.path.splitext(path)[1].lower(), "")


def strip_fences(t):
    t = t.strip("\n")
    m = re.match(r"^```[\w+-]*\n(.*?)\n?```\s*$", t, re.S)
    return (m.group(1) if m else t).rstrip() + "\n"


def verify(before, after, path):
    """(safe, note). Python/JSON: parsed structure must match. Others: non-whitespace must match."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".py":
            ok = ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))
        elif ext == ".json":
            ok = json.loads(before) == json.loads(after)
        else:
            ok = re.sub(r"\s+", "", before) == re.sub(r"\s+", "", after)
    except (SyntaxError, ValueError):
        ok = False
    return ok, "" if ok else "code content changed, review carefully"


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Reformatter:
    def __init__(self, memory, chat):
        self.mem, self.chat = memory, chat

    def propose(self, path):
        if os.path.getsize(path) > MAX_BYTES:
            raise ValueError(f"file is over {MAX_BYTES // 1000} KB - too big for the on-device model")
        with open(path, encoding="utf-8") as f:
            before = f.read()
        if not before.strip():
            raise ValueError("file is empty")
        lang = lang_of(path)
        msgs = [{"role": "system", "content": SYSTEM + self.mem.context_for(lang, before[:2000])},
                {"role": "user", "content": f"Language: {lang or 'unknown'}\n\n{before}"}]
        after = strip_fences(self.chat(msgs))
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            "before", "after", n=2))
        safe, note = verify(before, after, path)
        return Proposal(path, before, after, diff, safe, note, _sha(before))

    def apply(self, p):
        with open(p.path, encoding="utf-8") as f:
            now = f.read()
        if _sha(now) != p.digest:
            raise RuntimeError("file changed since the proposal - run it again")
        self.mem.add("backup", {"path": p.path, "text": now}, lang_of(p.path))
        tmp = os.path.join(os.path.dirname(p.path), ".x_tmp_" + os.path.basename(p.path))
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(p.after)
        os.replace(tmp, p.path)
        self.mem.add("accepted", {"path": os.path.basename(p.path), "before": p.before[:1500],
                                  "after": p.after[:1500]}, lang_of(p.path))

    def reject(self, p, reason=""):
        self.mem.add("rejected", {"path": os.path.basename(p.path), "reason": reason.strip(),
                                  "before": p.before[:600]}, lang_of(p.path))

    def undo(self, path):
        for r in self.mem.list("backup", limit=200):
            if r["data"]["path"] == path:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(r["data"]["text"])
                self.mem.delete(r["id"])
                return True
        return False
