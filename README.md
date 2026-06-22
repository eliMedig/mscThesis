# TEAF PoC

Proof-of-concept of the **Tacit Externalisation Agent Framework (TEAF)** as part of an MSc thesis TEAF is a two-agent system for Enterprise Architecture governance coaching. A coaching agent talks to the
practitioner while a background domain agent grounds answers in governance documents (RAG), a structured
portfolio (SQL), and hybrid anomaly detection. The written thesis is the primary documentation for
the concepts. This repo is the running software artefact while it also preserves other appendencies of the thesis.

## Prerequisites to run the application

- Python 3.12 (3.11+ works), or
- Docker with Compose v2

## How to run it locally

```bash
git clone <repo-url> msc-thesis
cd msc-thesis
python -m venv poc/.venv
# activate: Windows -> poc\.venv\Scripts\Activate.ps1   macOS/Linux -> source poc/.venv/bin/activate
pip install -r poc/requirements.txt
streamlit run poc/app.py
```

Open http://localhost:8501. First launch downloads the local embedding model (~90 MB).

## Run with Docker

```bash
git clone git@github.com:eliMedig/mscThesis.git
cd mscThesis-main
docker compose up
```

Open http://localhost:8501. Data persists in the `msc-thesis-data` volume. (The home-lab deployment
behind Traefik lives in `docker-compose.homelab.yml` and is not needed here.)

## Configuration

The app needs at least one model before you can chat:

1. Settings → Models & API keys → register a model (e.g. provider `anthropic`, model
   `claude-sonnet-4-6`) and paste your API key for it.
2. Settings → Agents → assign that model to the Coaching agent, the Domain agent, and the
   reflection model.

Besides directly within the app you can instead also supply the keys as environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Keys entered in the UI are stored in the data directory and never committed.

## App usage

1. The Chat tab is where you can interact with the agent and manage your data sources. The application comes with coaching and domain knowledge that was synthesized during the MSc thesis. You can freely upload additional files or remove existing ones (accepted formats are TXT, MD as well as text-based PDFs). The exampleFiles folder contains the source documents, as well as a copy of the portfolio.csv file. If you want to update the portfolio, please ensure that the existing data structure is maintained as the PoC relies on certain hard-coded field names.

2. To include anomaly detection results you have to manually run the detection on first startup. Running the anomaly detection process creates a task for each detected anomaly. This functionality showcases how the system would generate notifications and can be reviewed in the tasks menu. Notifications are currently not integrated with any external system, and the PoC does not provide an option for such integration.

3. The self-reflection process is automatically triggered every 8 turns by default (this can be adjusted in the Settings menu - Interaction triggers - Trigger B), as well as whenever a session is ended. All externalisations are available in the Tacit Externalisation menu, where they can be approved or rejected. Approved externalisations are used to update the agent and may influence its future behavior.

## Reference

- Layout: `poc/app.py` is the entry point; `poc/teaf/` is the framework, `poc/ui/` the Streamlit pages.
- Version and changelog: `poc/config.py` and `change_log.md`.
- Tests: `cd poc && python -m pytest`.
