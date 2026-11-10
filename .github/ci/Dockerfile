FROM node:24.22.1-bookworm-slim@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c AS node
FROM python:3.13.18-bookworm@sha256:cc55e4ded9c95f6ce2133b3d096db43f214d280c2a8af65d83e246c8fa7d168c
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
RUN mkdir -p /private/tmp && chmod 1777 /private/tmp
COPY requirements.lock /opt/polar-ci/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r /opt/polar-ci/requirements.lock \
    && python -m pip check && git --version && node --version
COPY run.py /opt/polar-ci/run.py
COPY runtime_smoke.py /opt/polar-ci/runtime_smoke.py
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/polar-ci/run.py"]
