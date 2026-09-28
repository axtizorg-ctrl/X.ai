import json, os, sys, tempfile, unittest, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.crypto import Vault
from core.memory import Memory
from core.reformat import Reformatter, verify, strip_fences
from core.server import start_server
from bridge.acode_bridge import Tracker, uri_to_path


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.v = Vault(os.path.join(self.d, "vault.json"))
        self.v.create("correct horse battery")
        self.m = Memory(os.path.join(self.d, "m.db"), self.v)

    def test_vault(self):
        blob = self.v.encrypt(b"secret code", b"a")
        self.assertNotIn(b"secret", blob)
        self.assertEqual(self.v.decrypt(blob, b"a"), b"secret code")
        with self.assertRaises(Exception):
            self.v.decrypt(blob, b"other-aad")
        bad = bytearray(blob); bad[-1] ^= 1
        with self.assertRaises(Exception):
            self.v.decrypt(bytes(bad), b"a")
        v2 = Vault(self.v.path)
        with self.assertRaises(ValueError):
            v2.unlock("wrong passphrase")
        v2.unlock("correct horse battery")
        self.assertEqual(v2.decrypt(blob, b"a"), b"secret code")
        v2.change_passphrase("new passphrase!")
        v3 = Vault(self.v.path); v3.unlock("new passphrase!")
        self.assertEqual(v3.decrypt(blob, b"a"), b"secret code")

    def test_memory_encrypted_at_rest_and_search(self):
        self.m.add("pref", {"text": "always use 4 spaces and single quotes"}, "python")
        self.m.add("note", {"text": "kivy screens go in ui folder"})
        raw = open(os.path.join(self.d, "m.db"), "rb").read()
        self.assertNotIn(b"single quotes", raw)
        self.assertNotIn(b"kivy screens", raw)
        hits = self.m.search("kivy ui screens", "")
        self.assertEqual(hits[0]["data"]["text"], "kivy screens go in ui folder")
        self.assertIn("4 spaces", self.m.context_for("python", "def f(): pass"))

    def test_verify(self):
        self.assertTrue(verify("x=1\nif x:\n  y=2\n", "x = 1\nif x:\n    y = 2\n", "a.py")[0])
        self.assertFalse(verify("x=1\n", "x = 2\n", "a.py")[0])
        self.assertTrue(verify("{'a':1}".replace("'", '"'), '{\n  "a": 1\n}', "a.json")[0])
        self.assertTrue(verify("a{b:1}", "a {\n  b: 1\n}", "a.css")[0])
        self.assertFalse(verify("a{b:1}", "a {\n  b: 2\n}", "a.css")[0])
        self.assertEqual(strip_fences("```python\nx = 1\n```"), "x = 1\n")

    def test_reformat_flow(self):
        f = os.path.join(self.d, "t.py")
        open(f, "w").write("def f( a,b ):\n  return a+b\n")
        good = "def f(a, b):\n    return a + b\n"
        seen = {}
        def fake(msgs):
            seen["sys"] = msgs[0]["content"]
            return "```python\n" + good + "```"
        self.m.add("pref", {"text": "prefer 4 space indent"}, "python")
        r = Reformatter(self.m, fake)
        p = r.propose(f)
        self.assertTrue(p.safe); self.assertIn("4 space indent", seen["sys"])
        self.assertEqual(open(f).read(), "def f( a,b ):\n  return a+b\n")  # untouched before Yes
        r.apply(p)
        self.assertEqual(open(f).read(), good)
        self.assertEqual(self.m.list("accepted")[0]["data"]["after"], good)
        self.assertTrue(r.undo(f))
        self.assertEqual(open(f).read(), "def f( a,b ):\n  return a+b\n")
        # unsafe change is flagged, stale file refused, No is learned
        p2 = Reformatter(self.m, lambda m: "def f(a, b):\n    return a - b\n").propose(f)
        self.assertFalse(p2.safe)
        open(f, "a").write("# edited\n")
        with self.assertRaises(RuntimeError):
            r.apply(p2)
        r.reject(p2, "never change logic")
        self.assertIn("never change logic", self.m.context_for("python", "return a"))

    def test_paths_and_tracker(self):
        self.assertEqual(uri_to_path("content://com.android.externalstorage.documents/tree/primary%3Aprojects::primary:projects/app/a.py"),
                         "/storage/emulated/0/projects/app/a.py")
        self.assertEqual(uri_to_path("content://com.android.externalstorage.documents/tree/primary%3Aprojects/document/primary%3Aprojects%2Fb.js"),
                         "/storage/emulated/0/projects/b.js")
        self.assertIsNone(uri_to_path("content://other.provider/x"))
        a, b = os.path.join(self.d, "a.py"), os.path.join(self.d, "b.js")
        open(a, "w").write("1"); open(b, "w").write("2")
        os.utime(a, (1, 1))
        t = Tracker(self.d)
        self.assertEqual(t.current()[0], b)
        t.report(a, True)
        self.assertEqual(t.current(), (a, "Acode plugin", True))

    def test_server(self):
        t = Tracker(self.d)
        srv = start_server(t, lambda: self.m, "tok123", port=0)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        def call(path, body=None, tok="tok123"):
            req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                         {"X-Token": tok, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, {}
        f = os.path.join(self.d, "z.py"); open(f, "w").write("x")
        self.assertEqual(call("/active", {"path": f}, tok="bad")[0], 401)
        self.assertEqual(call("/active", {"path": f})[0], 200)
        self.assertEqual(call("/active")[1]["path"], f)
        self.assertEqual(call("/memory/add", {"kind": "note", "text": "qwen likes tabs"})[0], 200)
        self.assertEqual(call("/memory/add", {"kind": "backup", "text": "x"})[0], 400)
        res = call("/memory/search?q=qwen+tabs")[1]["results"]
        self.assertEqual(res[0]["data"]["text"], "qwen likes tabs")
        srv.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
