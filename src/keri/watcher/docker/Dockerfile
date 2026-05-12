FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    liblmdb-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml .
RUN pip install --upgrade pip && pip install build
COPY . .
RUN pip install --no-cache-dir -e .


FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    liblmdb0 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r keri --gid=999 \
    && useradd -r -g keri --uid=999 --home-dir=/app --shell=/sbin/nologin keri

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/keri-watcher /usr/local/bin/keri-watcher
COPY --from=builder /build /app

RUN mkdir -p /var/lib/keri-watcher/lmdb \
    && chown -R keri:keri /var/lib/keri-watcher /app

USER keri

EXPOSE 5632 5633 9090

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5632/health || exit 1

ENTRYPOINT ["keri-watcher"]