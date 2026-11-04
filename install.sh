#!/bin/sh
# panweb 安装：CLI 软链到 ~/.local/bin，技能装到 ~/.agents/skills
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/panweb" 2>/dev/null || true

mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/panweb" "$HOME/.local/bin/panweb"
echo "✅ CLI:      $HOME/.local/bin/panweb -> $DIR/panweb"

if [ -d "$DIR/skill/panweb-publish" ]; then
  mkdir -p "$HOME/.agents/skills"
  rm -rf "$HOME/.agents/skills/panweb-publish"
  cp -R "$DIR/skill/panweb-publish" "$HOME/.agents/skills/"
  echo "✅ 技能:    $HOME/.agents/skills/panweb-publish"
fi

if [ -d "$DIR/ui" ]; then
  mkdir -p "$HOME/.panweb"
  rm -rf "$HOME/.panweb/ui"
  cp -R "$DIR/ui" "$HOME/.panweb/ui"
  echo "✅ 控制台:  $HOME/.panweb/ui（备用副本）"
fi

if [ -f "$DIR/THIRD_PARTY_NOTICES.md" ]; then
  cp "$DIR/THIRD_PARTY_NOTICES.md" "$HOME/.panweb/THIRD_PARTY_NOTICES.md"
  rm -rf "$HOME/.panweb/third_party"
  cp -R "$DIR/assets/third_party" "$HOME/.panweb/third_party"
fi

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "⚠️  运行前提: 缺少 python3（python3 3.9+ 才能运行 panweb）"
  echo "             可运行 xcode-select --install，或安装 python.org 的 3.9+"
elif "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "✅ 运行前提: python3 $("$PYTHON" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null)"
else
  echo "⚠️  运行前提: python3 版本过低（$("$PYTHON" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null)，需要 3.9+）"
fi

if command -v cloudflared >/dev/null 2>&1 \
   || [ -x "$HOME/homebrew/bin/cloudflared" ] \
   || [ -x /opt/homebrew/bin/cloudflared ] \
   || [ -x /usr/local/bin/cloudflared ]; then
  echo "✅ 依赖:    cloudflared 已安装"
else
  echo "⚠️  缺依赖:  请运行  brew install cloudflared"
fi

echo "完成。试试: panweb doctor"
