"""Supabase client. Credentials come from the environment only -- never here."""
import os

from supabase import Client, create_client


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    # predict.py / retrain.py need INSERT/UPDATE rights, so they run with the
    # service_role key (GitHub Secrets or backend/.env, never the frontend).
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)
