-- Runs once on first container init (postgres image convention). Creates a
-- second, separate database for integration tests so `pytest` can never
-- truncate the real dev database at WNBA_ENGINE_DATABASE_URL. See
-- tests/integration/test_ingestion_e2e.py, which refuses to run unless it
-- is connected to a database with 'test' in its name.
CREATE DATABASE wnba_engine_test;
