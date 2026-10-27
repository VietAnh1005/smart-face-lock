#!/usr/bin/env bash
# Chạy Smart Face Lock. Mọi tham số được chuyển tiếp cho main.py, ví dụ:
#   scripts/dev.sh               chạy ứng dụng
#   scripts/dev.sh --calibrate   chỉnh ngưỡng
#   scripts/dev.sh --reset       xóa dữ liệu, cài lại
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# venv nằm ở đường dẫn không dấu vì dlib không đọc được model trong thư mục có dấu
VENV="${USERPROFILE:-$HOME}/.venvs/smart_face_lock"
PYTHON="$VENV/Scripts/python.exe"            # Windows
[ -x "$PYTHON" ] || PYTHON="$VENV/bin/python" # macOS / Linux

if [ ! -x "$PYTHON" ]; then
  echo "Không tìm thấy $PYTHON — làm theo mục Cài đặt trong README.md" >&2
  exit 1
fi

cd "$ROOT"
exec "$PYTHON" -W ignore main.py "$@"
