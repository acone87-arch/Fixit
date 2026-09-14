#!/usr/bin/env bash
# Restore one Fixit DB+media backup into disposable local resources and compare
# it with the manifests captured from the source.  Production containers and
# volumes are never attached to the restored database.
set -Eeuo pipefail

backup="${1:?backup directory required}"
test -d "$backup"
for required in database.dump database.counts uploads.tar.gz uploads.sha256 SHA256SUMS; do
  test -f "$backup/$required"
done

(cd "$backup" && sha256sum -c SHA256SUMS)

suffix="${RANDOM:-0}-$$"
container="fixit-backup-restore-$suffix"
media_root=$(mktemp -d)
restored_counts=$(mktemp)
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$media_root" "$restored_counts"
}
trap cleanup EXIT

docker run -d --name "$container" --network none \
  -e POSTGRES_USER=fsm -e POSTGRES_PASSWORD="restore-only-$suffix" \
  -e POSTGRES_DB=fixit_restore postgres:16-alpine >/dev/null
ready=false
for attempt in $(seq 1 30); do
  if docker exec "$container" pg_isready -U fsm -d fixit_restore >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
test "$ready" = true

docker exec -i "$container" pg_restore \
  --exit-on-error --no-owner --no-privileges -U fsm -d fixit_restore \
  < "$backup/database.dump"

docker exec "$container" psql -U fsm -d fixit_restore -Atc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name" \
  | while IFS= read -r table; do
      count=$(docker exec "$container" psql -U fsm -d fixit_restore -Atc \
        "SELECT count(*) FROM \"$table\"")
      printf '%s|%s\n' "$table" "$count"
    done > "$restored_counts"
cmp "$backup/database.counts" "$restored_counts"

alembic_version=$(docker exec "$container" psql -U fsm -d fixit_restore -Atc \
  "SELECT version_num FROM alembic_version")
test -n "$alembic_version"

tar -xzf "$backup/uploads.tar.gz" -C "$media_root"
if test -s "$backup/uploads.sha256"; then
  (cd "$media_root" && sha256sum -c "$backup/uploads.sha256")
fi

table_count=$(wc -l < "$restored_counts" | tr -d ' ')
media_count=$(find "$media_root/uploads" -type f | wc -l | tr -d ' ')
printf 'Backup restore verified: tables=%s media_files=%s alembic=%s\n' \
  "$table_count" "$media_count" "$alembic_version"
