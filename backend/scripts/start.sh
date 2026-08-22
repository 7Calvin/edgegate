#!/bin/bash
#
# Backend Startup Script
# Runs migrations and starts the application
#

set -e

echo "============================================"
echo "EdgeGate - Backend"
echo "============================================"

# Wait for database to be ready
echo "Waiting for database..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if python -c "
import asyncio
import asyncpg

async def check():
    try:
        conn = await asyncpg.connect(
            host='${POSTGRES_HOST:-postgres}',
            port=${POSTGRES_PORT:-5432},
            database='${POSTGRES_DB:-edgegate}',
            user='${POSTGRES_USER:-edgegate_admin}',
            password='${POSTGRES_PASSWORD:-changeme}'
        )
        await conn.close()
        return True
    except:
        return False

exit(0 if asyncio.run(check()) else 1)
" 2>/dev/null; then
        echo "Database is ready!"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Waiting for database... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "ERROR: Database not available after $MAX_RETRIES retries"
    exit 1
fi

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "Migrations completed successfully"
else
    echo "WARNING: Migration failed, attempting to continue..."
fi

# Initialize database (create admin if not exists)
echo "Initializing database..."
python -c "
import asyncio
from app.db.init_db import create_initial_admin
from app.db.session import AsyncSessionLocal

async def init():
    async with AsyncSessionLocal() as db:
        await create_initial_admin(db)

asyncio.run(init())
"

# Start the application
echo "Starting application..."
exec uvicorn app.main:app \
    --host ${BACKEND_HOST:-0.0.0.0} \
    --port ${BACKEND_PORT:-8000} \
    --workers ${WORKERS:-1} \
    --log-level ${LOG_LEVEL:-info}
