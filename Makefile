.PHONY: test build-ui check syntax zipapp dmg

build-ui:
	python3 tools/build_ui.py

zipapp:
	python3 tools/build_zipapp.py

# 安装包：先由 panweb install-app 造自包含 App，再 hdiutil 打成 .dmg（仅 macOS）
dmg:
	python3 tools/build_dmg.py

# -x '/\._'：外置磁盘会给出 macOS AppleDouble 伴生文件，compileall 读到它们的空字节会误报
syntax:
	python3 -m compileall -q -x '/\._' src tools tests

check: syntax
	python3 tools/build_ui.py --check
	python3 -m unittest discover -s tests -v

test: check
