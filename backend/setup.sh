#!/bin/bash
# Run this once to create the conda environment and install dependencies.
# Usage: bash setup.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
conda create -n syntra-backend python=3.11 -y
conda run -n syntra-backend pip install -r "${SCRIPT_DIR}/requirements.txt" \
  -r "${SCRIPT_DIR}/requirements-dev.txt"

echo ""
echo "Done! To start the server run:"
echo "  conda activate syntra-backend"
echo "  python -m uvicorn app.main:app --reload"

# ── Uncomment when wiring up the database ──────────────────────────────────────
# conda run -n syntra-backend pip install \
#   "sqlalchemy==2.0.30" \
#   "alembic==1.13.1" \
#   "psycopg2-binary==2.9.10" \
#   "redis==5.0.4"

# ── Uncomment when wiring up Google OAuth ──────────────────────────────────────
# conda run -n syntra-backend pip install \
#   "google-api-python-client==2.127.0" \
#   "google-auth-oauthlib==1.2.0"
