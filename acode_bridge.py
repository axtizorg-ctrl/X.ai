"""Finds the file you are working on. Exact: the Acode plugin reports the active file.
Fallback: most recently modified source file under the projects folder."""
import os, time
from urllib.parse import unquote

PROJECTS = os.environ.get("X_PROJECTS", "/storage/emulated/0/projects")
EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".html", ".css", ".kv", ".java", ".kt",
        ".c", ".h", ".cpp", ".go", ".rs", ".sh", ".md", ".yml", ".yaml", ".xml", ".php", ".rb"}
SKIP = {".git", "node_modules", "__pycache__", "build", "dist", ".buildozer", "venv", ".venv"}


def get_project_path():
    return PROJECTS


def uri_to_path(uri):
    """Map an Acode/SAF uri (or plain path) to a real filesystem path, else None."""
    if uri.startswith("/"):
        return uri
    if uri.startswith("file://"):
        return unquote(uri[7:])
    if "::" in uri:                       # Acode: content://...tree/<tree>::<docId>
        doc = uri.split("::", 1)[1]
    elif "/document/" in uri:             # plain SAF document uri
        doc = uri.split("/document/", 1)[1]
    else:
        return None
    vol, _, rel = unquote(doc).partition(":")
    base = "/storage/emulated/0" if vol == "primary" else "/storage/" + vol
    return os.path.join(base, rel)


class Tracker:
    def __init__(self, root=None):
        self.root = root or PROJECTS
        self.reported = None      # (path, dirty, time)

    def report(self, uri_or_path, dirty=False):
        p = uri_to_path(uri_or_path)
        if not p:
            return None
        self.reported = (p, bool(dirty), time.time())
        return p

    def current(self):
        """-> (path or None, source, dirty)"""
        if self.reported and os.path.isfile(self.reported[0]):
            return self.reported[0], "Acode plugin", self.reported[1]
        best, best_t, seen = None, 0, 0
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in SKIP]
            for f in files:
                seen += 1
                if seen > 5000:
                    break
                if os.path.splitext(f)[1].lower() in EXTS:
                    p = os.path.join(d, f)
                    try:
                        t = os.path.getmtime(p)
                    except OSError:
                        continue
                    if t > best_t:
                        best, best_t = p, t
        return best, "most recently edited", False
