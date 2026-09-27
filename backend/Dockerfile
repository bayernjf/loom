FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_RETRIES=5 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY backend/ /app/
# Skill/WF registry lives at repo root; the app resolves it at /runtime in the image.
COPY runtime/ /runtime/
# Runtime lock only (43 pins, zero dev tooling) + the package with --no-deps, so the
# image carries exactly the dependency set CI tested (Q222: open bounds had drifted
# 12 of 58 packages between the runner, the image and every rehearsal environment).
RUN pip install -r requirements.lock && pip install . --no-deps

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status == 200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
