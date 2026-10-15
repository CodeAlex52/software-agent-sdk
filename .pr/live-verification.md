# PR #5758 warm-pool persistence verification

The fix rebuilds persistence stores with the initialized config before telemetry
and conversation services read them. Real-process verification reproduced the
failure twice on `8621cf331` and passed twice on `f4dfad4ae`.

| Observation | Before | After |
|---|---|---|
| Init with current key B and previous key A | 200, ready | 200, ready |
| Saved LLM key | Appears missing | Original value readable |
| Settings PATCH | 409 | 200 |
| Saved custom secret | 404 | 200, original value |
| Init re-encryption | Stores retain startup cipher | Both stores re-encrypted |
| Recovery | Restoring A recovers original values | Restart with only B reads original and new values |

[Complete sanitized evidence and reproduction recipe](https://github.com/OpenHands/software-agent-sdk/tree/cfa5562d1ffd7290b125fd8c13fd77bb444ef76a/.pr)
are preserved in the earlier evidence commit, including requests, responses,
file-integrity checks, logs, and process cleanup results.

Runs used macOS source checkouts, real HTTP, persisted files, and a loopback
telemetry receiver. This exercised the warm-pool lifecycle locally; it did not
run a Kubernetes deployment. All credentials were dummy fixtures, no model calls
were needed, and all owned servers and receivers were stopped.

The automated regression retains both rotated-key and already-current-key cases.
It checks startup → init → reads/writes and decrypts both persisted files using
only B before any writes, proving eager re-encryption at init.

The original focused suites passed **513 tests**, with one existing WebSocket
timing skip. Pre-commit passed. Subsequent simplification removes a duplicate
restart and secret-deletion check; production code is unchanged. Both retained
regression cases and pre-commit pass after simplification.
