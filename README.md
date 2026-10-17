---
title: CITYPILOT
sdk: docker
app_port: 7860
---

# ayna-hackathon-2026

Minimal Python repository for the AYNA 2026 hackathon. Use `data/` for local datasets, `notebooks/` for exploration, `src/` for Python code, and `outputs/` for generated results.

Docker packaging reuses the routing app factory. See [deployment instructions](docs/DEPLOYMENT.md)
for explicit artifact mounts, local rehearsal, Hugging Face configuration and
remaining decision-cache/UI release requirements. This is not a deployed service.
