#!/bin/sh
# Copy the container-side snapshot volume to a directory on the host.
#
# The dumps live in a named volume, so the host filesystem cannot see them at
# all; docker cp is the only way out without adding a bind mount. Runs from
# launchd, so every path here is absolute on purpose.
set -u

CONTAINER=${BACKUP_CONTAINER:-infra-db-backup-1}
DST=${BACKUP_HOST_DIR:-$HOME/000mycodes-backups/loom}
DOCKER=/usr/local/bin/docker

mkdir -p "$DST" || exit 1
"$DOCKER" cp "$CONTAINER:/backups/." "$DST/" || exit 1
