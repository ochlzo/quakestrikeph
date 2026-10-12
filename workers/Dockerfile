FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ARG UV_VERSION=0.11.32

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --system --gid 10001 quakestrike \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin quakestrike \
    && chown quakestrike:quakestrike /app

USER quakestrike

COPY --chown=quakestrike:quakestrike workers/pyproject.toml workers/uv.lock ./workers/
WORKDIR /app/workers
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=quakestrike:quakestrike workers/src ./src
COPY --chown=quakestrike:quakestrike workers/model-release-manifests ./model-release-manifests
COPY --chown=quakestrike:quakestrike database/alembic.ini /app/database/alembic.ini
COPY --chown=quakestrike:quakestrike database/migrations /app/database/migrations
RUN uv sync --frozen --no-dev


ENTRYPOINT ["uv", "run", "--frozen", "--no-dev", "--no-sync"]
CMD ["quakestrike-ingestor"]
