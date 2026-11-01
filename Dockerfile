# CovertLens web service image (CL-47).
# Multi-stage: node builds the frontend, python:3.12-slim serves.
#   docker build -t covertlens .
#   docker run -p 8000:8000 -v covertlens-data:/data covertlens

FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend
WORKDIR /build
# React + Vite + TypeScript app (CL-48); lockfile-pinned install.
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COVERTLENS_DATA_DIR=/data \
    COVERTLENS_WORKERS=4
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
WORKDIR /app
COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt
COPY covertlens/ ./covertlens/
COPY config/ ./config/
COPY schemas/ ./schemas/
COPY app/ ./app/
COPY scripts/precompute.py ./scripts/precompute.py
COPY --from=frontend /build/dist/ ./app/static/
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/cache \
    && chown -R appuser:appuser /data /app
USER appuser
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Test stage: library test-suite inside the image (CI build-image job).
FROM runtime AS test
USER root
RUN pip install --no-cache-dir "pytest>=8"
COPY tests/ ./tests/
COPY pyproject.toml ./
USER appuser
CMD ["python", "-m", "pytest", "-q"]

# Final stage is the runtime image, so a plain `docker build .`
# produces the service (stranger-with-one-command path, CL-47).
FROM runtime
