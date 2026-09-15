#!/usr/bin/env bash
# Real PostgreSQL custom-format and media restore drill with disposable Docker
# containers.  Used by CI; it does not connect to the application database.
set -Eeuo pipefail

root=$(mktemp -d)
source_container="fixit-backup-source-${RANDOM:-0}-$$"
cleanup() {
  docker rm -f "$source_container" >/dev/null 2>&1 || true
  rm -rf "$root"
}
trap cleanup EXIT

backup="$root/backup"
media="$root/media"
mkdir -p "$backup" "$media/uploads/evidence"
printf 'photo-evidence\n' > "$media/uploads/evidence/photo.jpg"
printf 'pdf-evidence\n' > "$media/uploads/evidence/act.pdf"

docker run -d --name "$source_container" --network none \
  -e POSTGRES_USER=fsm -e POSTGRES_PASSWORD=source-only \
  -e POSTGRES_DB=fsm postgres:16-alpine >/dev/null
ready=false
for attempt in $(seq 1 30); do
  if test "$(docker exec "$source_container" psql -U fsm -d fsm -Atc \
      'SELECT 1' 2>/dev/null || true)" = 1; then
    ready=true
    break
  fi
  sleep 1
done
test "$ready" = true

docker exec -i "$source_container" psql -U fsm -d fsm -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES ('20260914_0016');
CREATE TABLE organizations (id uuid PRIMARY KEY, name text NOT NULL);
INSERT INTO organizations VALUES ('00000000-0000-0000-0000-000000000001', 'Restore drill');
CREATE TABLE equipment (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id), serial_number text);
INSERT INTO equipment VALUES
  ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'RESTORE-1'),
  ('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'RESTORE-2');
SQL

docker exec "$source_container" pg_dump -U fsm -d fsm -Fc > "$backup/database.dump"
docker exec "$source_container" psql -U fsm -d fsm -Atc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name" \
  | while IFS= read -r table; do
      count=$(docker exec "$source_container" psql -U fsm -d fsm -Atc \
        "SELECT count(*) FROM \"$table\"")
      printf '%s|%s\n' "$table" "$count"
    done > "$backup/database.counts"
tar -czf "$backup/uploads.tar.gz" -C "$media" uploads
(cd "$media" && find uploads -type f -print0 | sort -z | xargs -0 -r sha256sum) \
  > "$backup/uploads.sha256"
(cd "$backup" && sha256sum database.dump uploads.tar.gz > SHA256SUMS)

bash scripts/verify_pilot_backup.sh "$backup"
