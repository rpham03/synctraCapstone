#!/bin/bash
# Run this once to create the conda environment and install dependencies.
# Usage: bash setup.sh

conda create -n syntra-backend python=3.11 -y
conda run -n syntra-backend pip install \
  "fastapi==0.115.0" \
  "uvicorn[standard]==0.30.6" \
  "pydantic==2.9.2" \
  "pydantic-settings==2.5.2" \
  "httpx==0.27.0" \
  "python-dotenv==1.0.1" \
  "icalendar==5.0.13" \
  "recurring-ical-events==3.2.0"

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
