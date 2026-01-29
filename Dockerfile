FROM python:3.11-slim

WORKDIR /app

# Copy frontend
COPY frontend /app/frontend

# Install backend dependencies
COPY backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend /app/backend

EXPOSE 8000

# Use shell form for PORT expansion
CMD sh -c "cd /app/backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
