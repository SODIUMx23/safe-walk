# MinIO stopped publishing some newer binary images: build a verified AGPL source release.
FROM golang:1.26-bookworm AS compile
ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ARG MINIO_SHA256=be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c
RUN curl -fL --retry 3 "https://codeload.github.com/minio/minio/tar.gz/refs/tags/${MINIO_VERSION}" -o /tmp/minio.tar.gz \
    && echo "${MINIO_SHA256}  /tmp/minio.tar.gz" | sha256sum -c - \
    && mkdir /src && tar -xzf /tmp/minio.tar.gz -C /src --strip-components=1
WORKDIR /src
RUN GOMAXPROCS=2 CGO_ENABLED=0 go build -p 2 -trimpath -ldflags="-s -w -X github.com/minio/minio/cmd.Version=${MINIO_VERSION} -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_VERSION}" -o /minio .
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 minio && useradd -u 10001 -g minio -M minio \
    && mkdir -p /data && chown minio:minio /data
COPY --from=compile /minio /usr/local/bin/minio
USER 10001:10001
EXPOSE 9000 9002
ENTRYPOINT ["tini", "--", "/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9002"]
