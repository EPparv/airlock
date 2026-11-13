#!/bin/bash
# Called by the app window, never by a user-facing terminal.
set -euo pipefail
umask 077
payload="$1"
base="$2"
mkdir -p "$base"
progress() { printf '%s' "$1" > "$base/progress.txt"; }
trap 'progress "Setup stopped. Check your internet connection, then click Try again."' ERR
runtime="$base/runtime"
app="$base/app"
mkdir -p "$runtime" "$app"
hash_file() { /usr/bin/shasum -a 256 "$1" | /usr/bin/cut -d ' ' -f 1; }
case "$(/usr/bin/uname -m)" in
 arm64) target=aarch64-apple-darwin; expected=50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544 ;;
 x86_64) target=x86_64-apple-darwin; expected=960da44cb4b73685206ddd250b19e0a117fa41095710c1038f081f5cb613efb4 ;;
 *) exit 1 ;;
esac
if [ ! -x "$runtime/uv" ]; then
 progress 'Preparing Airlock. Downloading its runtime…'
 archive="$(mktemp "$runtime/download.XXXXXX")"
 unpack="$(mktemp -d "$runtime/unpack.XXXXXX")"
 /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --connect-timeout 20 "https://github.com/astral-sh/uv/releases/download/0.12.23/uv-$target.tar.gz" -o "$archive"
 [ "$(hash_file "$archive")" = "$expected" ]
 /usr/bin/tar --no-same-owner -xzf "$archive" -C "$unpack" --strip-components=1 "uv-$target/uv"
 chmod 700 "$unpack/uv"
 mv "$unpack/uv" "$runtime/uv"
 rm -f "$archive";rmdir "$unpack"
fi
export UV_PYTHON_INSTALL_DIR="$runtime/python"
export UV_CACHE_DIR="$runtime/cache"
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_PROGRESS=1
export PYTHONDONTWRITEBYTECODE=1
if [ ! -x "$runtime/venv/bin/python" ]; then
 progress 'Installing the app runtime. No extra apps or accounts are needed…'
 "$runtime/uv" --no-config venv --python 3.12.15 "$runtime/venv"
fi
lock_hash="$(hash_file "$payload/requirements.lock")"
saved_hash="$(cat "$runtime/dependencies.sha256" 2>/dev/null || true)"
if [ "$lock_hash" != "$saved_hash" ] || ! "$runtime/venv/bin/python" -c 'import mcp,cryptography,yaml' >/dev/null 2>&1; then
 progress 'Finishing installation. Checking the app components…'
 "$runtime/uv" --no-config pip sync --python "$runtime/venv/bin/python" --require-hashes --only-binary :all: "$payload/requirements.lock"
 printf '%s' "$lock_hash" > "$runtime/dependencies.sha256"
fi
progress 'Opening Airlock…'
# Only allowlisted program files are copied. Existing encrypted data is retained.
/usr/bin/ditto "$payload/privacy_layer" "$app/privacy_layer"
/usr/bin/ditto "$payload/ui" "$app/ui"
/usr/bin/ditto "$payload/builtin" "$app/builtin"
/usr/bin/ditto "$payload/vendor" "$app/vendor"
/bin/cp "$payload/release.json" "$app/release.json"
if [ ! -e "$app/.venv" ]; then /bin/ln -s "$runtime/venv" "$app/.venv"; fi
cd "$app"
exec "$runtime/venv/bin/python" -m privacy_layer.launcher --no-open
