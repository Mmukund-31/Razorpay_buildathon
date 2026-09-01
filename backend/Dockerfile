# Build context MUST be the repo root (not backend/) — this Dockerfile copies ml/ and
# simulator/ from alongside backend/. On Render: set "Docker Build Context Directory" to "."
# and "Dockerfile Path" to "backend/Dockerfile". Locally: `docker build -f backend/Dockerfile .`
# from the repo root.
FROM python:3.12-slim

WORKDIR /app

# libgomp1 is required by LightGBM at import time, not just build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
RUN pip install --no-cache-dir -e .

# ml/ and simulator/ live at the repo root, one level up from backend/ — copied in explicitly
# so `import ml.*` / `import simulator.*` resolve inside the container exactly like they do
# in local dev (see app/main.py's sys.path note). ml/data and ml/training/artifacts are
# deliberately NOT copied from the host (.dockerignore excludes them, and they're gitignored
# besides) — the dataset and model are generated fresh in the next step instead, so the image
# is reproducible from source rather than depending on committed binary artifacts.
COPY ml /ml
COPY simulator /simulator
COPY scripts /scripts
ENV PYTHONPATH=/:/app

# Generates the 50k-row synthetic dataset (deterministic seed) and trains both models, exactly
# like the local Quickstart in README.md — the image always has an active model to serve.
RUN pip install --no-cache-dir pandas numpy scikit-learn lightgbm joblib \
    && python /scripts/generate_synthetic_dataset.py --rows 50000 --seed 42 \
    && python /ml/training/train_baseline.py \
    && python /ml/training/train_lightgbm.py

EXPOSE 8000

# Render (and most PaaS) inject $PORT at runtime; default to 8000 for `docker run` locally.
# Migrations run at container start, not build time, so they always target the actual
# deployed database, not whatever DATABASE_URL happened to be set during the build.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
