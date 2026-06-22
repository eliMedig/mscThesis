# syntax=docker/dockerfile:1
# TEAF PoC — single-process Streamlit container. Build context is the repo root;
# the app lives under poc/.

# ---- builder: install deps (native-module toolchain BEFORE pip, per convention) ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# build-essential + python3-dev so a FRESH build (empty cache) compiles any native
# modules (e.g. chroma-hnswlib) instead of silently hanging. Compilers stay in the
# builder stage only; the runtime image stays slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY poc/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ---- runtime: slim image with the built venv, the app, and a pre-baked model ----
FROM python:3.12-slim AS runtime
# libgomp1 is the OpenMP runtime torch + scikit-learn need (not in -slim by default).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8501 \
    HF_HOME=/app/hf-cache
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Pre-download the local embedding model so the running container needs no internet.
# Done BEFORE copying the app so changing app code does NOT re-download the model.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY poc/ /app/
RUN mkdir -p /data
EXPOSE 8501
# Bind 0.0.0.0 on the configurable PORT; Traefik reaches it on this internal port.
# Shell form so ${PORT} expands.
CMD streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port=${PORT} \
    --server.headless=true \
    --browser.gatherUsageStats=false
