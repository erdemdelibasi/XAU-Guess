// Public frontend config. The Supabase ANON key belongs here: it is designed
// to be client-side, and Row Level Security (supabase/schema.sql) restricts it
// to read-only SELECT. The service_role key must NEVER appear in this file.
//
// Fill these in from your Supabase project settings (Project Settings -> API).
const CONFIG = {
  SUPABASE_URL: "https://YOUR-PROJECT.supabase.co",
  SUPABASE_ANON_KEY: "YOUR-ANON-KEY",
};
