#!/bin/sh
# Copy the container-side snapshot volumes to directories on the host.
#
# Both families live in named volumes, so the host filesystem cannot see them
# at all; docker cp is the only way out without adding a bind mount. Runs from
# launchd, so every path here is absolute on purpose.
#
# Two sources are deliberately independent: a failure in one must not skip the
# other, so each records its own status and the script exits non-zero at the
# end if either failed.
set -u

DOCKER=/usr/local/bin/docker
DST=${BACKUP_HOST_DIR:-$HOME/000mycodes-backups/loom}

# Logical dumps (pg_dump snapshots), refreshed on every backup cycle.
BACKUP_CONTAINER=${BACKUP_CONTAINER:-infra-db-backup-1}
# Base backups plus archived WAL, the PITR source; written daily.
BASEBACKUP_CONTAINER=${BASEBACKUP_CONTAINER:-infra-db-basebackup-1}

rc=0

mkdir -p "$DST" || exit 1
"$DOCKER" cp "$BACKUP_CONTAINER:/backups/." "$DST/" || rc=1

# Kept in a subdirectory so the two families never collide by name.
mkdir -p "$DST/base" || rc=1
"$DOCKER" cp "$BASEBACKUP_CONTAINER:/basebackups/." "$DST/base/" || rc=1

# A zero-byte snapshot means the dump was interrupted before it wrote anything,
# but docker cp faithfully reproduces it. Left in place it looks like a backup
# that exists and is only discovered at restore time, so park it out of the way;
# the container copy stays untouched.
mkdir -p "$DST/_invalid" || rc=1
find "$DST" -maxdepth 1 -type f -size 0c -exec mv -f {} "$DST/_invalid/" \; 2>/dev/null || true

exit $rc
