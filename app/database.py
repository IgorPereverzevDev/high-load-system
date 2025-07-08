from supabase import create_client, Client
import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SUPABASE_KEY = os.getenv("SUPABASE_KEY",
                         "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS requests (
        id UUID PRIMARY KEY,
        payload JSONB NOT NULL,
        result JSONB,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        sequence_number INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        completed_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
    CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);
    CREATE INDEX IF NOT EXISTS idx_requests_sequence ON requests(sequence_number);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_sequence_unique ON requests(sequence_number);
"""
