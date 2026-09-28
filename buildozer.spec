[app]
title = X Assistant
package.name = xassistant
package.domain = org.x
source.dir = .
source.include_exts = py,kv,png,json
source.exclude_dirs = tests,acode-plugin,.github,bin,.buildozer
version = 2.0
requirements = python3,kivy==2.3.0,pycryptodome,pyjnius,android
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
