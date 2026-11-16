#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != "Darwin" ]; then
    echo "Wersję macOS należy budować na Macu."
    exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
export PYINSTALLER_CONFIG_DIR="$PWD/.cache/pyinstaller"
.venv/bin/python -m PyInstaller --noconfirm --distpath dist/macos --workpath build/macos packaging/macos.spec
echo "Gotowe: dist/macos/PhotoSorter.app — otwórz dwuklikiem w Finderze."
