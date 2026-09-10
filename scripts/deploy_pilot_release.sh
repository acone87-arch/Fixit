#!/usr/bin/env bash
# Run on the existing /opt/fixit VPS only, after acceptance of the exact SHA.
# Preserve DB/uploads and the previous image. Never downgrade a live database.
set -Eeuo pipefail
cd /opt/fixit
release_sha="${1:?accepted release SHA required}"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
git cat-file -e "$release_sha^{commit}"
git diff --quiet
git diff --cached --quiet
compose=(docker compose -f docker-compose.prod.yml)
old_sha=$(git rev-parse HEAD)
old_container=$("${compose[@]}" ps -q api)
test -n "$old_container"
old_image=$(docker inspect --format '{{.Image}}' "$old_container")
old_tag=$(docker inspect --format '{{.Config.Image}}' "$old_container")
umask 077
backup="/opt/fixit/backups/pilot-$(date -u +%Y%m%dT%H%M%SZ)-${release_sha:0:12}"
mkdir -p "$backup"
printf '%s\n' "$old_sha" > "$backup/code.sha"
printf '%s\n' "$old_image" > "$backup/image.id"
cp .env "$backup/env"
docker tag "$old_image" "fixit-pilot-rollback:${release_sha:0:12}"
stopped=false
rollback() {
  rc=$?
  trap - ERR
  set +e
  git checkout --detach "$old_sha"
  if [ "$stopped" = true ]; then
    echo 'Release failed; restoring previous application image. Database and uploads remain intact.' >&2
    docker tag "$old_image" "$old_tag"
    "${compose[@]}" up -d --no-deps --no-build --force-recreate api
  fi
  echo "Recovery files: $backup" >&2
  exit "$rc"
}
trap rollback ERR
git checkout --detach "$release_sha"
"${compose[@]}" build api
# Pause writes briefly so the DB and media archives describe the same state.
stopped=true
"${compose[@]}" stop api
"${compose[@]}" exec -T db pg_dump -U fsm -d fsm -Fc </dev/null > "$backup/database.dump"
docker run --rm --volumes-from "$old_container:ro" --entrypoint tar "$old_image" -czf - -C /app uploads > "$backup/uploads.tar.gz"
test -s "$backup/database.dump" && test -s "$backup/uploads.tar.gz"
"${compose[@]}" exec -T db pg_restore --list < "$backup/database.dump" > "$backup/database.list"
tar -tzf "$backup/uploads.tar.gz" > "$backup/uploads.list"
sha256sum "$backup/database.dump" "$backup/uploads.tar.gz" > "$backup/SHA256SUMS"
"${compose[@]}" run --rm -T api alembic upgrade head </dev/null
"${compose[@]}" up -d --no-deps --no-build --force-recreate api
healthy=false
for attempt in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then healthy=true; break; fi
  sleep 2
done
test "$healthy" = true
test "$(git rev-parse HEAD)" = "$release_sha"
"${compose[@]}" exec -T api alembic current </dev/null
printf 'Release SHA: %s\nPrevious SHA: %s\nBackup: %s\n' "$release_sha" "$old_sha" "$backup"
trap - ERR
