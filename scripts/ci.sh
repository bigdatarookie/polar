#!/usr/bin/env bash
# One public locked environment for author, independent QA and Actions.
set -euo pipefail
TOOLS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_ROOT=$TOOLS_ROOT
REPORT_DIR=
TESTS=()
while (($#)); do
  case "$1" in
    --source) SOURCE_ROOT=$(cd "$2" && pwd); shift 2 ;;
    --reports) REPORT_DIR=$2; shift 2 ;;
    --test) TESTS+=(--test "$2"); shift 2 ;;
    *) echo 'usage: scripts/ci.sh [--source CHECKOUT] [--reports EMPTY_DIR] [--test tests/path.py]' >&2; exit 2 ;;
  esac
done
if [[ -z "$REPORT_DIR" ]]; then REPORT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/polar-ci-report.XXXXXX"); else mkdir -p "$REPORT_DIR"; fi
REPORT_DIR=$(cd "$REPORT_DIR" && pwd)
if [[ -n $(ls -A "$REPORT_DIR") ]]; then echo 'Refusing nonempty reports directory' >&2; exit 2; fi
RUN_ID="polar-ci-$(date -u +%Y%m%dT%H%M%S)-$$"
DB_ID=; NETWORK_ID=; TEST_ID=
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  local failed=0 remaining
  for id in "$TEST_ID" "$DB_ID"; do
    if [[ -n "$id" ]]; then
      docker rm -f "$id" >>"$REPORT_DIR/container-cleanup.log" 2>&1 || failed=1
      remaining=$(docker ps -aq --no-trunc --filter "id=$id") || failed=1
      [[ -z "$remaining" ]] || failed=1
    fi
  done
  if [[ -n "$NETWORK_ID" ]]; then
    docker network rm "$NETWORK_ID" >"$REPORT_DIR/network-cleanup.log" 2>&1 || failed=1
    remaining=$(docker network ls -q --filter "id=$NETWORK_ID") || failed=1
    [[ -z "$remaining" ]] || failed=1
  fi
  if [[ "$failed" == 0 ]]; then echo VERIFIED_ABSENT >"$REPORT_DIR/cleanup-status.txt"; else echo UNKNOWN_OR_FAILED >"$REPORT_DIR/cleanup-status.txt"; code=1; fi
  echo "CI reports: $REPORT_DIR"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# The image is an output of this command, never a privately prepared prerequisite.
docker build --iidfile "$REPORT_DIR/image-id" -f "$TOOLS_ROOT/.github/ci/Dockerfile" "$TOOLS_ROOT/.github/ci" >"$REPORT_DIR/environment-build.log" 2>&1 || { tail -100 "$REPORT_DIR/environment-build.log"; exit 1; }
IMAGE_ID=$(cat "$REPORT_DIR/image-id")
NETWORK_ID=$(docker network create --label polar.resource.project=polar --label "polar.resource.task=$RUN_ID" "$RUN_ID")
DB_ID=$(docker run -d --tmpfs /var/lib/postgresql/data --network "$NETWORK_ID" --network-alias ci-db --label polar.resource.project=polar --label "polar.resource.task=$RUN_ID" -e POSTGRES_USER=polar -e POSTGRES_PASSWORD=polar_ci -e POSTGRES_DB=polar_test_ci postgres:17.11-alpine@sha256:3540c0362c809df084ffac0ae69fe794515f9de92692f02178bcdce0ef0302ac)
READY=0
for attempt in $(seq 1 60); do
  if docker exec "$DB_ID" pg_isready -U polar -d polar_test_ci >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
[[ "$READY" == 1 ]] || { docker logs "$DB_ID" >"$REPORT_DIR/postgres.log" 2>&1; exit 1; }
docker exec "$DB_ID" psql -U polar -d polar_test_ci -c 'CREATE DATABASE polar_test_dataset_ci' >"$REPORT_DIR/database-setup.log" 2>&1
TEST_ID=$(docker create --network "$NETWORK_ID" --label polar.resource.project=polar --label "polar.resource.task=$RUN_ID" \
  --mount "type=bind,src=$SOURCE_ROOT,dst=/workspace,readonly" --mount "type=bind,src=$REPORT_DIR,dst=/reports" \
  -e POLAR_TEST_DATABASE_URL=postgresql://polar:polar_ci@ci-db:5432/polar_test_ci \
  -e POLAR_DATASET_TEST_DATABASE_URL=postgresql://polar:polar_ci@ci-db:5432/polar_test_dataset_ci \
  "$IMAGE_ID" "${TESTS[@]}")
set +e
docker start --attach "$TEST_ID" >"$REPORT_DIR/console.log" 2>&1
TRANSPORT=$?
set -e
EXIT_CODE=$(docker inspect --format '{{.State.ExitCode}}' "$TEST_ID")
cat "$REPORT_DIR/console.log"
docker logs "$DB_ID" >"$REPORT_DIR/postgres.log" 2>&1
[[ "$TRANSPORT" == 0 ]] || exit "$TRANSPORT"
exit "$EXIT_CODE"
