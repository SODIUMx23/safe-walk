# Build ONLY Timescale's Apache-2.0 portion; no Timescale License features.
# Use the maintained PostgreSQL Bookworm base; older PostGIS binary images can
# reference the now-archived Bullseye PGDG repository.
FROM postgres:16-bookworm AS compile
ARG TIMESCALE_VERSION=2.31.0
ARG TIMESCALE_SHA256=7a0135283240abb64c87713e3280d70461954028d6426374b7e4e59f7dca6a56
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl cmake build-essential postgresql-server-dev-16 libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fL --retry 3 "https://codeload.github.com/timescale/timescaledb/tar.gz/refs/tags/${TIMESCALE_VERSION}" -o /tmp/timescale.tar.gz \
    && echo "${TIMESCALE_SHA256}  /tmp/timescale.tar.gz" | sha256sum -c - \
    && mkdir /tmp/timescale && tar -xzf /tmp/timescale.tar.gz -C /tmp/timescale --strip-components=1 \
    && cd /tmp/timescale && ./bootstrap -DAPACHE_ONLY=1 -DREGRESS_CHECKS=OFF -DWARNINGS_AS_ERRORS=OFF -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --parallel 2 && cmake --install build
FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
COPY --from=compile /usr/lib/postgresql/16/lib/timescaledb*.so /usr/lib/postgresql/16/lib/
COPY --from=compile /usr/share/postgresql/16/extension/timescaledb* /usr/share/postgresql/16/extension/
COPY infra/db/init.sql /opt/safewalk/init.sql
COPY infra/db/init.sh /docker-entrypoint-initdb.d/30-safewalk.sh
RUN chmod 0755 /docker-entrypoint-initdb.d/30-safewalk.sh
# No TSL background policies are used; app maintenance handles retention.
CMD ["postgres", "-c", "shared_preload_libraries=timescaledb", "-c", "max_connections=100", "-c", "timescaledb.max_background_workers=0"]
