-- ============================================
-- EdgeGate - Database Initialization
-- PostgreSQL 17
-- ============================================

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy search

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE edgegate TO edgegate_admin;

-- Set timezone
SET timezone = 'UTC';

-- Performance optimizations for PostgreSQL 17
ALTER DATABASE edgegate SET random_page_cost = 1.1;
ALTER DATABASE edgegate SET effective_cache_size = '4GB';
ALTER DATABASE edgegate SET shared_buffers = '1GB';
ALTER DATABASE edgegate SET work_mem = '50MB';

-- Success message
SELECT 'Database initialized successfully!' AS status;
