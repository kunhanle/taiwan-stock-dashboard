FROM python:3.11-slim

WORKDIR /app

# Copy frontend
COPY frontend /app/frontend

# Install backend dependencies
COPY backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend /app/backend

# Ship the pre-built linkage snapshot seed. The container is too small to
# recompute the taxonomy live and the working snapshot is gitignored, so the
# API falls back to this seed (path must match SEED_SNAPSHOT in linkage_api.py).
COPY linkage-service/seed/linkage_snapshot.seed.json /app/linkage-service/seed/linkage_snapshot.seed.json

EXPOSE 8000

# Use shell form for PORT expansion
CMD sh -c "cd /app/backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
