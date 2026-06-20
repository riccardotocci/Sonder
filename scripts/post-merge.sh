#!/bin/bash
set -e

# Post-merge setup for Sonder (FastAPI backend + Vite/React frontend).
# Idempotent and non-interactive: re-syncs dependencies after a task merge.

# Backend Python dependencies
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

# Frontend Node dependencies
if [ -f frontend/package-lock.json ]; then
  npm install --prefix frontend
fi
