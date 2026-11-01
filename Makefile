.PHONY: test build-ui check syntax zipapp

build-ui:
	python3 tools/build_ui.py

zipapp:
	python3 tools/build_zipapp.py

# -x '/\._'：外置磁盘会给出 macOS AppleDouble 伴生文件，compileall 读到它们的空字节会误报
syntax:
	python3 -m compileall -q -x '/\._' src tools tests

check: syntax
	python3 tools/build_ui.py --check
	python3 -m unittest discover -s tests -v

test: check
