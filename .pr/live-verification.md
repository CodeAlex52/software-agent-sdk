# PR #5758 warm-pool persistence verification

Verified 2026-10-15 with real Agent Server processes, HTTP requests, persisted
files, and a run-owned loopback HTTP telemetry receiver. No model calls were
needed; all stored credentials are dummy fixtures. Bootstrap/session keys and
encrypted values in retained exchanges are redacted.

Baseline: `8621cf331bf6221ba7dc6bae1d1fd6f84ad58601`.
Fix: `f4dfad4ae15d74bb9fa01929d1aa940279d83798`.

| Observation | Baseline, 2 rounds | Fix, 2 rounds |
|---|---|---|
| Initialize with B and previous A | 200, ready | 200, ready |
| Saved LLM key after init | Appears missing | Original value readable |
| Settings PATCH after init | 409 | 200 |
| Saved custom secret after init | 404 | 200, original value |
| Re-encryption at init | Cached stores retain startup cipher | Both stores report re-encryption |
| Restart with only B | Not applicable | Original LLM key and original/new custom secrets readable |
| Stored data intact | Restoring A recovers original values | Original values remain readable with B |

The common sequence is implemented in
[`warm-pool-rotation.sh`](warm-pool-rotation.sh): seed settings and a custom
secret under A; restart dormant with unrelated startup C and a configured HTTP
telemetry exporter; POST `/api/init` with B plus previous A; read and write
settings/secrets. Fixed runs then restart with only B, without any previous key.
The baseline's failed PATCH also preserved the settings file byte for byte
(`live-proof/baseline-2/file-integrity.json`).

The real process imports `sockets.py`, whose module-level conversation service
initializes both persistence stores before `/api/init`. Telemetry startup also
reads the settings store. This explains why real baseline processes expose the
custom-secret failure as well as the settings failure. The fix resets both
stores before re-encryption and before building the initialized telemetry sink.

`live-proof/results.json` is the compact result ledger. Selected sanitized API
exchanges are under `live-proof/{baseline-1,baseline-2,fixed-1,fixed-3}/exchanges/`.
The retained successful fixed repeats are named `fixed-1` and `fixed-3`; an
interrupted evidence-shell attempt was discarded and replaced with a fresh run.
`health-and-logs.json` captures normal startup/final doctor checks and actual
telemetry/re-encryption logs. Every completed owned run and loopback receiver was
stopped; each retained `stop.json` confirms its port closed.

Reproduce from the fixed checkout after `make build`:

```sh
bash .pr/warm-pool-rotation.sh /path/to/baseline-checkout baseline baseline-repeat
bash .pr/warm-pool-rotation.sh "$PWD" fixed fixed-repeat
```

Automated verification supplied by the implementation owner: **513 passed,
1 skipped**, with 18 existing deprecation warnings, in 192.09 seconds. The
existing skip is `test_security_risk_field_with_live_server` (WebSocket disconnect
timing). The two startup/init regression variants failed on the baseline and
passed on the fix.

```sh
uv run pytest tests/sdk/utils/test_cipher.py tests/sdk/utils/test_pydantic_secrets.py tests/agent_server/test_store_cipher_mismatch.py tests/agent_server/test_config.py tests/agent_server/test_init_router.py tests/agent_server/test_settings_router.py tests/agent_server/telemetry tests/cross/test_remote_conversation_live_server.py -q
```
