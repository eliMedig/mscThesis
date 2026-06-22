# msc-thesis

MSc Artificial Intelligence thesis repository. The proof-of-concept for the
**Tacit Externalisation Framework (TEAF)** lives under [`poc/`](poc/) — see
[poc/README.md](poc/README.md) for the framework, the TEAF→module mapping, and how
to run it locally.

## Run locally

```powershell
py -3.12 -m venv poc/.venv
poc/.venv/Scripts/Activate.ps1
pip install -r poc/requirements.txt
streamlit run poc/app.py
```

## Deploy (self-hosted: Docker + Traefik + Woodpecker)

Single-process Streamlit container, built + deployed on the runner on push to
`main` (like the other homelab apps), behind Traefik on the external `private`
network.

The image installs heavy deps at build time (torch, chromadb) and the embedding
model. The runner's **default build network can't resolve external DNS**
(`deb.debian.org`/PyPI), so `docker-compose.yml` sets `build.network: host` — the
build steps borrow the host's working DNS. This is scoped to the build only; the
container's runtime network is unchanged.

One-time server steps: enable the repo in Woodpecker and mark it **Trusted**
(required for the Docker socket mount).

- **Dockerfile** — multi-stage; native toolchain in the builder; runtime binds
  `0.0.0.0` on `PORT` (default 8501); pre-bakes the local embedding model so the
  running container needs no internet at runtime.
- **docker-compose.yml** — `build: { context: ., network: host }`, network
  `private`, **no published ports**, Traefik `Host(\`msc-thesis.home\`)` →
  internal port 8501, one bind mount for `DATA_DIR`
  (`/home/eli/apps/msc-thesis/data:/data`).
- **.woodpecker.yml** — on push to `main`, `docker compose -p msc-thesis up -d
  --build --force-recreate`.

Persistent data (SQLite DB, Chroma vector store, reflection patches, synthetic
portfolio) lives under the single `DATA_DIR` volume. API keys are optional and can
be entered at runtime in **Admin → Models**.
