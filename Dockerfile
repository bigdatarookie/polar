FROM python:3.13.18-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src src
COPY pyproject.toml .
ARG CODE_REVISION=UNRECORDED
ENV POLAR_CODE_REVISION=$CODE_REVISION
LABEL org.opencontainers.image.revision=$CODE_REVISION
RUN useradd --uid 10001 --create-home polar && mkdir -p /data/artifacts /output && chown -R 10001:10001 /data /output
USER 10001:10001
CMD ["python", "-m", "uvicorn", "polar.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
