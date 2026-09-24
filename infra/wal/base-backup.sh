#!/bin/sh
# Q182：周期 pg_basebackup（tar + gzip，stream 备份期 WAL），写入共享卷并在完成后
# 打 .done 标记，由 wal-archiver 推送到 MinIO。pgvector 镜像内已含 pg_basebackup。
set -u

BASE_DIR=/basebackups
INTERVAL="${BASEBACKUP_INTERVAL_SECONDS:-86400}"
PGHOST="${PGHOST:-postgres}"
PGUSER="${PGUSER:-loom}"
export PGPASSWORD="${PGPASSWORD:-loom}"

take() {
  ts=$(date +%Y%m%dT%H%M%S)
  dir="$BASE_DIR/$ts"
  mkdir -p "$dir"
  echo "taking base backup $ts"
  if pg_basebackup -h "$PGHOST" -U "$PGUSER" -D "$dir" -Ft -z -X stream -c fast; then
    touch "$dir.done"
  else
    echo "base backup failed; removing $dir"
    rm -rf "$dir"
  fi
}

while true; do
  take
  sleep "$INTERVAL"
done
