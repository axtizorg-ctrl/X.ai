import os, secrets, threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import StringProperty
from kivy.utils import escape_markup, platform

from bridge import acode_bridge, termux_bridge
from core.crypto import Vault
from core.memory import Memory
from core.reformat import Reformatter
from core.server import start_server

CHAT_SYS = "You are X, a concise on-device coding assistant."


def ensure_storage():
    """Android 11+: /storage/emulated/0/projects needs 'All files access'."""
    if platform != "android":
        return
    try:
        from jnius import autoclass
        if autoclass("android.os.Environment").isExternalStorageManager():
            return
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        i = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
        i.setData(Uri.parse("package:" + act.getPackageName()))
        act.startActivity(i)
    except Exception as e:
        Logger.warning("X: storage permission: %s", e)


def colorize(diff):
    out = []
    for line in diff.splitlines():
        t = escape_markup(line)
        if line.startswith("+") and not line.startswith("+++"):
            t = "[color=66ff88]%s[/color]" % t
        elif line.startswith("-") and not line.startswith("---"):
            t = "[color=ff7777]%s[/color]" % t
        out.append(t)
    return "\n".join(out)


class XApp(App):
    title = "X"
    lock_hint = StringProperty("")
    active_text = StringProperty("Active file: (none yet)")
    status_text = StringProperty("")
    review_title = StringProperty("")
    diff_text = StringProperty("")
    mem_text = StringProperty("")
    chat_text = StringProperty("")

    def build(self):
        Window.clearcolor = (0.05, 0.07, 0.11, 1)
        d = self.user_data_dir
        self.vault = Vault(os.path.join(d, "vault.json"))
        self.mem = None
        self.prop = None
        self.history = []
        self.server = None
        self.tracker = acode_bridge.Tracker()
        tok = os.path.join(d, "token")
        if not os.path.exists(tok):
            fd = os.open(tok, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(24))
        self.token = open(tok).read().strip()
        self.lock_hint = ("Enter your passphrase" if self.vault.exists() else
                          "First run: choose a passphrase (8+ chars).\nIt encrypts everything X stores. "
                          "It cannot be recovered if you forget it.")
        ensure_storage()
        return Builder.load_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "main.kv"))

    # ---------- helpers ----------
    def go(self, name):
        self.root.current = name
        if name == "memory":
            self.refresh_memory()

    def bg(self, fn, done):
        def run():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            Clock.schedule_once(lambda dt: done(res, err))
        threading.Thread(target=run, daemon=True).start()

    # ---------- unlock ----------
    def unlock(self, pw):
        try:
            if self.vault.exists():
                self.vault.unlock(pw)
            elif len(pw) >= 8:
                self.vault.create(pw)
            else:
                self.lock_hint = "Passphrase must be at least 8 characters"
                return
        except ValueError:
            self.lock_hint = "Wrong passphrase"
            return
        self.mem = Memory(os.path.join(self.user_data_dir, "memory.db"), self.vault)
        self.reformatter = Reformatter(self.mem, termux_bridge.chat)
        if self.server is None:
            try:
                self.server = start_server(self.tracker, lambda: self.mem, self.token)
            except OSError as e:
                Logger.warning("X: local server: %s", e)
        self.root.ids.pass_in.text = ""
        self.go("home")
        self.refresh_active()
        Clock.schedule_interval(lambda dt: self.refresh_active(), 5)

    def refresh_active(self):
        self.bg(self.tracker.current, self._active)

    def _active(self, res, err):
        if err or not res or not res[0]:
            self.active_text = "No active file found.\nOpen a file in Acode."
        else:
            p, src, dirty = res
            self.active_text = "%s\n%s%s" % (os.path.basename(p), src,
                                             "  (unsaved in Acode - save first)" if dirty else "")

    # ---------- reformat ----------
    def propose(self):
        path = self.tracker.current()[0]
        if not path:
            self.status_text = "No active file found. Open a file in Acode."
            return
        self.status_text = "Asking Qwen..."
        self.bg(lambda: self.reformatter.propose(path), self._proposed)

    def _proposed(self, prop, err):
        if err:
            self.status_text = "Error: %s" % err
            return
        if not prop.diff:
            self.status_text = "Already formatted - nothing to change."
            return
        self.prop, self.status_text = prop, ""
        self.review_title = "%s  %s" % (os.path.basename(prop.path),
                                        "[OK] formatting only" if prop.safe else "[!] " + prop.note)
        self.diff_text = colorize(prop.diff)
        self.go("review")

    def decide(self, yes):
        reason = self.root.ids.reason_in.text
        self.root.ids.reason_in.text = ""
        try:
            if yes:
                self.reformatter.apply(self.prop)
                msg = "Applied. Reload the file in Acode. X learned from your Yes."
            else:
                self.reformatter.reject(self.prop, reason)
                msg = "Discarded. X learned from your No."
        except Exception as e:
            msg = "Error: %s" % e
        self.prop, self.status_text = None, msg
        self.go("home")

    def undo(self):
        path = self.tracker.current()[0]
        ok = path and self.reformatter.undo(path)
        self.status_text = "Restored previous version." if ok else "No backup for this file."

    # ---------- chat ----------
    def send(self, text):
        text = text.strip()
        if not text or not self.mem:
            return
        self.root.ids.chat_in.text = ""
        self.chat_text += "\n\nYou: " + text
        msgs = ([{"role": "system", "content": CHAT_SYS + self.mem.context_for("", text)}]
                + self.history[-8:] + [{"role": "user", "content": text}])
        self.bg(lambda: termux_bridge.chat(msgs), lambda r, e: self._reply(text, r, e))

    def _reply(self, q, reply, err):
        if err:
            self.chat_text += "\n\nX: (error) %s" % err
            return
        self.history += [{"role": "user", "content": q}, {"role": "assistant", "content": reply}]
        self.mem.add("chat", {"q": q[:500], "a": reply[:1500]})
        self.chat_text += "\n\nX: " + reply

    # ---------- memory ----------
    def refresh_memory(self):
        if not self.mem:
            return
        rows = self.mem.list(limit=40)
        self.mem_text = "\n".join("#%d [%s] %s" % (r["id"], r["kind"], self.mem.text_of(r)[:70])
                                  for r in rows if r["kind"] != "backup") or "(empty)"

    def add_mem(self, kind, text):
        if text.strip():
            self.mem.add(kind, {"text": text.strip()})
            self.root.ids.note_in.text = ""
            self.refresh_memory()

    def forget(self, text):
        if text.strip().isdigit():
            self.mem.delete(int(text))
            self.root.ids.del_in.text = ""
            self.refresh_memory()

    # ---------- misc ----------
    def check_status(self):
        self.status_text = "Checking..."
        self.bg(termux_bridge.status, lambda r, e: setattr(self, "status_text", r[1] if r else str(e)))

    def copy_token(self):
        Clipboard.copy(self.token)
        self.status_text = "Plugin token copied. Paste it into the Acode plugin when asked."

    def voice(self):
        import voice
        voice.start_voice()


if __name__ == "__main__":
    XApp().run()
