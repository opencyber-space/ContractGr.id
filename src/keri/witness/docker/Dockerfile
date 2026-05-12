FROM rust:1.76-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && echo "" > src/lib.rs
RUN cargo build --release 2>/dev/null || true
RUN rm -rf src

COPY src ./src
COPY migrations ./migrations
RUN touch src/main.rs src/lib.rs

RUN cargo build --release


FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r keri --gid=999 \
    && useradd -r -g keri --uid=999 --home-dir=/app --shell=/sbin/nologin keri

WORKDIR /app

COPY --from=builder /build/target/release/keri-witness /usr/local/bin/keri-witness
COPY --from=builder /build/migrations /app/migrations

RUN chown -R keri:keri /app

USER keri

EXPOSE 5631 9090

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5631/health || exit 1

ENTRYPOINT ["/usr/local/bin/keri-witness"]