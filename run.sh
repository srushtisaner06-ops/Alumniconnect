#!/usr/bin/env bash
# One-command local start: builds the C++ engine, starts API (:8000) and UI (:5173).
set -e
cd "$(dirname "$0")"
make -C engine || echo "g++ not available: the backend will use its built-in Python fallback"
pip install -r backend/requirements.txt
(cd frontend && npm install)
(cd backend && python3 -m uvicorn app.main:app --port 8000) &
BACK=$!
trap "kill $BACK" EXIT
cd frontend && npm run dev
