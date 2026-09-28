# X Mobile AI Assistant v2

Reformats the file you're editing in Acode using Qwen (running in Termux), only after you tap **Yes**.
It learns from your Yes/No decisions and from notes you teach it. Everything it stores is encrypted.

## Build the APK (no PC needed beyond a browser)
1. Create a GitHub repo, upload this folder's contents.
2. Actions tab -> "Build APK" -> Run workflow (~15-25 min).
3. Download the `X-Assistant-APK` artifact, unzip, install `*-debug.apk`.

## Phone setup
1. Termux: get Ollama running (`ollama serve &`) and `ollama pull qwen2.5-coder:1.5b`
   (any Qwen model works: set `X_QWEN_MODEL`, or edit `bridge/termux_bridge.py`).
2. Open X, choose a passphrase, grant "All files access".
3. Acode plugin: zip the contents of `acode-plugin/` (plugin.json at the zip root), install it in
   Acode from the zip, paste the token from X ("Copy Acode plugin token").
   Without the plugin X falls back to your most recently edited file in /storage/emulated/0/projects.

## Use
Save your file in Acode -> X -> "Reformat active file" -> read the diff -> Yes / No.
Yes writes the file (original kept in encrypted memory - "Undo last reformat" restores it).
No (optionally with a reason) teaches X what to avoid.

## Encryption
AES-256-GCM. Random master key wrapped by scrypt(passphrase). Memory rows, chat history and file
backups are ciphertext on disk. Your project files stay plain text so Acode can open them.
Local API: 127.0.0.1 only, token required. Endpoints: `/active`, `/memory/search?q=`, `/memory/add`
(Termux scripts and Qwen tools can use them while the app is unlocked).

Tests: `python tests/test_core.py`
