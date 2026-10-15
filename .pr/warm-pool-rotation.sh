#!/usr/bin/env bash
set -euo pipefail

# Usage: bash .pr/warm-pool-rotation.sh CHECKOUT baseline|fixed LABEL
CHECKOUT=$(cd "$1" && pwd)
MODE=$2
LABEL=$3
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CLI="$ROOT/.agents/skills/verify-agent-server/scripts/control-agent-server"
OUT="$ROOT/.pr/live-proof/$LABEL"
mkdir -p "$OUT"
RUN=$($CLI launch --new --checkout "$CHECKOUT" --name "pr5758-$LABEL" --print-run)
printf '%s\n' "$RUN" > "$OUT/run-path.txt"
trap '$CLI stop --run "$RUN" > "$OUT/stop.json"' EXIT
run_cli() {
    "$CLI" "$@" --run "$RUN" >> "$OUT/commands.jsonl"
}
run_cli doctor
run_cli api PATCH /api/settings --json '{"agent_settings_diff":{"llm":{"api_key":"qa-pr5758-llm-secret"}},"misc_settings_diff":{"telemetry":{"consent":"granted"}}}' --expect 200 --check llm_api_key_is_set eq true --quiet --save PR5758/seed-settings
run_cli api PUT /api/settings/secrets --json '{"name":"QA_PR5758_TOKEN","value":"qa-pr5758-custom-secret"}' --expect 200 --save PR5758/seed-secret
SINK=$($CLI fixture http-sink --run "$RUN" --name pr5758-telemetry --print-path)
shasum -a 256 "$RUN/home/.openhands/settings.json" "$RUN/home/.openhands/secrets.json" > "$OUT/stores-before.txt"
run_cli restart --rotate-secret-key --env OH_DEFERRED_INIT=true --env OH_TELEMETRY_EXPORTER=http --env "OH_TELEMETRY_HTTP_ENDPOINT=$SINK/telemetry" --env OH_TELEMETRY_FLUSH_DELAY=1
run_cli api GET /api/init --auth none --expect 200 --check state eq dormant --save PR5758/dormant
run_cli logs --grep 'Telemetry initialised' --tail 20
run_cli sink read --name pr5758-telemetry --expect-max 0 --save PR5758/dormant-no-telemetry
jq -n --rawfile session "$RUN/private/session_api_key" --rawfile previous "$RUN/private/previous_secret_key" '{secret_key:($session|rtrimstr("\n")),previous_secret_keys:[($previous|rtrimstr("\n"))]}' > "$RUN/private/init-request.json"
run_cli api POST /api/init --auth init --json-file "$RUN/private/init-request.json" --expect 200 --check state eq ready --save PR5758/init
if [[ "$MODE" == baseline ]]; then
    run_cli api GET /api/settings --expect 200 --check llm_api_key_is_set eq false --quiet --save PR5758/settings-after-init
    run_cli api PATCH /api/settings --json '{"misc_settings_diff":{"qa_pr5758_after_init":true}}' --expect 409 --check detail contains 'encrypted with a different key' --save PR5758/patch-after-init
    run_cli api GET /api/settings/secrets/QA_PR5758_TOKEN --expect 200,404 --save PR5758/secret-after-init
    shasum -a 256 "$RUN/home/.openhands/settings.json" > "$OUT/settings-after-failed-write.txt"
    run_cli restart --restore-secret-key --env OH_DEFERRED_INIT=false
    run_cli api GET /api/settings --header 'X-Expose-Secrets: plaintext' --expect 200 --check llm_api_key_is_set eq true --check agent_settings.llm.api_key eq qa-pr5758-llm-secret --quiet --save PR5758/restored-key-a-settings
else
    run_cli api GET /api/settings --header 'X-Expose-Secrets: plaintext' --expect 200 --check llm_api_key_is_set eq true --check agent_settings.llm.api_key eq qa-pr5758-llm-secret --quiet --save PR5758/settings-after-init
    run_cli api GET /api/settings/secrets/QA_PR5758_TOKEN --expect 200 --check . eq qa-pr5758-custom-secret --save PR5758/secret-after-init
    run_cli api PATCH /api/settings --json '{"misc_settings_diff":{"qa_pr5758_after_init":true}}' --expect 200 --check misc_settings.qa_pr5758_after_init eq true --quiet --save PR5758/patch-after-init
    run_cli api PUT /api/settings/secrets --json '{"name":"QA_PR5758_NEW","value":"qa-pr5758-new-secret"}' --expect 200 --save PR5758/put-after-init
    run_cli logs --grep 'Re-encrypted' --tail 20
    run_cli sink read --name pr5758-telemetry --contains agent_server.server_started --expect-min 1 --wait 15 --save PR5758/telemetry-after-init
    B=$(cat "$RUN/private/session_api_key")
    run_cli restart --env OH_DEFERRED_INIT=false --env "OH_SECRET_KEY=$B"
    run_cli api GET /api/settings --header 'X-Expose-Secrets: plaintext' --expect 200 --check llm_api_key_is_set eq true --check agent_settings.llm.api_key eq qa-pr5758-llm-secret --check misc_settings.qa_pr5758_after_init eq true --quiet --save PR5758/current-key-only-settings
    run_cli api GET /api/settings/secrets/QA_PR5758_NEW --expect 200 --check . eq qa-pr5758-new-secret --save PR5758/current-key-only-new-secret
fi
if [[ "$MODE" == baseline ]]; then
    run_cli api GET /api/settings/secrets/QA_PR5758_TOKEN --expect 200,404 --save PR5758/restored-key-a-secret
else
    run_cli api GET /api/settings/secrets/QA_PR5758_TOKEN --expect 200 --check . eq qa-pr5758-custom-secret --save PR5758/final-original-secret
fi
run_cli doctor
cp -R "$RUN/evidence/PR5758" "$OUT/exchanges"
printf 'Completed %s proof: %s\n' "$MODE" "$OUT"
