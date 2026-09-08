// Public frontend config. The Supabase ANON key belongs here: it is designed
// to be client-side, and Row Level Security (supabase/schema.sql) restricts it
// to read-only SELECT. The service_role key must NEVER appear in this file.
//
// Fill these in from your Supabase project settings (Project Settings -> API).
const CONFIG = {
  SUPABASE_URL: "https://fswidrptzhasckigvrmi.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZzd2lkcnB0emhhc2NraWd2cm1pIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg3ODU5NDgsImV4cCI6MjEwNDM2MTk0OH0.LgrpEqMNmhDTGYJA8K9TC9_PYlg0Z_6W0D6qJTMcMlI",
};
