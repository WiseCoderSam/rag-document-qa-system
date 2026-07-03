FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any package requires compiling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Schema is Alembic-managed (see app/main.py) — apply migrations before
# starting the server so a fresh container/database is never left schemaless.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
