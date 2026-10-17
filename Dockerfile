FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/citypilot \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    CITYPILOT_ARTIFACT_DIR=/artifacts/c4-model \
    CITYPILOT_CONFIG_DIR=/app/supplements/m_services_v1/config

WORKDIR /app

# Keep the validated pins; fail the build if compatible binary wheels are absent.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
        --only-binary=:all: -r /app/requirements.txt \
    && python -m pip check \
    && groupadd --gid 1000 citypilot \
    && useradd --uid 1000 --gid 1000 --create-home \
        --shell /usr/sbin/nologin citypilot \
    && mkdir -p /artifacts \
    && chown 1000:1000 /artifacts

# Explicit runtime sources only. No notebook, raw data, bundle, cache or UI copy.
COPY src/citypilot/ /app/src/citypilot/
COPY supplements/m_services_v1/config/ /app/supplements/m_services_v1/config/
COPY config/objective/ /app/config/objective/

USER 1000:1000
EXPOSE 7860

# Routing readiness only; this does not certify a decision cache or approved UI.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-I", "-B", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/routing/ready', timeout=4).read()"]

CMD ["python", "-I", "-B", "-m", "uvicorn", "citypilot.api:create_app", "--factory", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
