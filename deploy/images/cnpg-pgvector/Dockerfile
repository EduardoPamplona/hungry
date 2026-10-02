# CloudNativePG-compatible Postgres 17 image WITH the pgvector extension.
#
# Why not pgvector/pgvector:pg17 (used in compose)? CNPG only manages operand
# images built on its own base (custom entrypoint, barman-cloud, instance
# manager). So we take the CNPG base and add pgvector from the PGDG apt repo,
# which the CNPG image already has configured.
#
# Confirm the exact base tag exists before building:
#   crane ls ghcr.io/cloudnative-pg/postgresql   (or check the GH package page)
ARG PG_TAG=17-standard-bookworm
FROM ghcr.io/cloudnative-pg/postgresql:${PG_TAG}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*
# CNPG runs the instance as uid 26 (the postgres user in these images).
USER 26
