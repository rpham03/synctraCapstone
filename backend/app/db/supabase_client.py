"""Supabase client initialization for storing calendar events."""

import os
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_KEY environment variables."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
