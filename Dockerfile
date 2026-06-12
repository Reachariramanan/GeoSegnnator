# ---------- Stage 1: build the React frontend ----------
FROM node:20-slim AS frontend
WORKDIR /app/client
COPY client/package.json client/package-lock.json* ./
RUN npm install
COPY client/ ./
RUN npm run build

# ---------- Stage 2: Python backend serving API + built frontend ----------
FROM python:3.12-slim AS runtime
WORKDIR /app

# OpenCV / scikit-image runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
COPY Data/ ./Data/

# Built SPA from stage 1 -> served by FastAPI at /
COPY --from=frontend /app/client/dist ./server/static

ENV PORT=8787 \
    STATIC_DIR=/app/server/static \
    PYTHONUNBUFFERED=1
EXPOSE 8787

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
