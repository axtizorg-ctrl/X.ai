(function () {
  const ID = "org.x.assistant.bridge";
  const URL = "http://127.0.0.1:8765/active";
  let token = localStorage.getItem("x_token") || "";

  async function push() {
    const f = editorManager.activeFile;
    if (!f || !f.uri || !token) return;
    try {
      await fetch(URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Token": token },
        body: JSON.stringify({ uri: f.uri, dirty: !f.isSaved }),
      });
    } catch (e) { /* X app not running */ }
  }

  async function askToken() {
    const prompt = acode.require("prompt");
    const t = await prompt("Paste the token from the X app", "", "text");
    if (t) { token = t.trim(); localStorage.setItem("x_token", token); push(); }
  }

  acode.setPluginInit(ID, async () => {
    if (!token) await askToken();
    editorManager.on("switch-file", push);
    editorManager.on("save-file", push);
    editorManager.editor.commands.addCommand({
      name: "x-set-token", description: "X: set token", exec: askToken,
    });
    push();
  });

  acode.setPluginUnmount(ID, () => {
    editorManager.off("switch-file", push);
    editorManager.off("save-file", push);
  });
})();
