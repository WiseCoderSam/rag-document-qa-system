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
# --proxy-headers makes request.client.host reflect the real client IP from
# X-Forwarded-For (set by Render's proxy) instead of the proxy's own IP —
# without it, every user shares one IP and the per-IP rate limits/auth
# lockout would throttle everyone collectively. Trusting "*" is safe here
# because traffic can only reach the container through Render's proxy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
