"""teaf — core package for the Tacit Externalisation Framework PoC.

Subpackages and modules map directly onto the four TEAF components (see README):
  - explicit_channels/  → Component 1 (RAG + anomaly detection)
  - agents/             → Components 2 (coaching) and 3 (domain)
  - orchestration.py    → the turn loop + the two triggers
  - reflection.py       → transcript → human-approved prompt patch
  - store.py / models.py / llm.py → persistence, model registry, provider wrapper
"""
