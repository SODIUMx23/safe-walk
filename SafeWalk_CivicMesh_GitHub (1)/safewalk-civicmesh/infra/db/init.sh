#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$(cat /run/secrets/db_password)" \
  --file=/opt/safewalk/init.sql
