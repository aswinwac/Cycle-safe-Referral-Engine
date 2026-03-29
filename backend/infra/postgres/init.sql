CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Keep bootstrap SQL intentionally light.
-- Application tables should be managed through Alembic migrations.

