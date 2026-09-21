#!/bin/sh
# Minimal PostgreSQL backup loop for the private beta single-host deployment
# (Q144 checklist #5). Runs pg_dump once at start and then every
# BACKUP_INTERVAL_SECONDS; prunes dumps older than RETENTION_DAYS.
set -e

: "${PGHOST:=postgres}"
: "${PGPORT:=5432}"
: "${PGUSER:=loom}"
: "${PGDATABASE:=loom}"
: "${BACKUP_DIR:=/backups}"
: "${RETENTION_DAYS:=7}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"

mkdir -p "$BACKUP_DIR"

backup_once() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  out="$BACKUP_DIR/loom-$ts.sql.gz"
  echo "[backup] dumping $PGDATABASE to $out"
  pg_dump --no-password --format=custom --compress=9 --file="$out.tmp"
  mv "$out.tmp" "$out"
  echo "[backup] pruning dumps older than $RETENTION_DAYS days"
  find "$BACKUP_DIR" -name 'loom-*.sql.gz' -type f -mtime "+$RETENTION_DAYS" -delete
}

while true; do
  if backup_once; then
    echo "[backup] ok"
  else
    echo "[backup] FAILED" >&2
  fi
  sleep "$BACKUP_INTERVAL_SECONDS"
done
