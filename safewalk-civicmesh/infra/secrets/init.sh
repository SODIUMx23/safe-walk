#!/bin/sh
set -eu
# Generate once into a named volume, never into the image, source tree, or logs.
# Files are read-only in consumers; replace this bootstrap with your secret manager
# in a multi-host installation. Back up archive_key separately before any rotation.
directory=/run/shared
mkdir -p "$directory"
for name in pg_admin_password db_password redis_password mqtt_password minio_password device_api_token caregiver_api_token archive_key; do
  if [ ! -s "$directory/$name" ]; then
    umask 077
    temporary="$(mktemp "$directory/.secret.XXXXXX")"
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "$temporary"
    printf '\n' >> "$temporary"
    chmod 0444 "$temporary"
    mv "$temporary" "$directory/$name"
  fi
done
if [ ! -s "$directory/minio_user" ]; then
  printf 'safewalk-root\n' > "$directory/minio_user"
  chmod 0444 "$directory/minio_user"
fi
printf 'SafeWalk credentials initialized in the private Docker volume.\n'
