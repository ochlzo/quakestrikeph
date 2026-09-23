ARG BASE_IMAGE_TAG
FROM quakestrike-workers:${BASE_IMAGE_TAG}

USER root
RUN apt-get update && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER quakestrike

RUN uv sync --frozen --no-dev --extra prediction

CMD ["quakestrike-prediction"]
