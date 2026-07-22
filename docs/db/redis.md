# Redis Key Manifest

> **Authentication:** The Redis instance requires a password. Use `change_me_redis` when connecting (`-a change_me_redis` with `redis-cli`, or `redis://:change_me_redis@redis:6379/0` in connection strings).

| Key pattern | Type | TTL | Owner | Purpose |
|---|---|---:|---|---|
| `auth:denylist:{jti}` | string | remaining JWT expiry | Auth | Revoked access tokens |
| `auth:fail:{email}` | counter | 10 min | Auth | Login brute-force protection |
| `auth:lock:{email}` | string | 15 min | Auth | Soft lock after 5 failed logins |
| `auth:mfa:{token}` | JSON string | 5 min | Auth | MFA login continuation |
| `session:refresh:{tokenHash}` | JSON string | refresh expiry | Auth | Refresh token lookup |
| `bot:session:{sessionId}:lang={lang_code}` | JSON string | 30 min | Bot | Multi-turn conversation state |
| `idempotency:{service}:{key}` | JSON string | 24 h | All mutating APIs | Return original response on retry |
| `fusion:weights` | hash | none | Orchestrator | Live model weights |
| `fusion:enabled_models` | set | none | Orchestrator | Live model enablement |
| `fusion:confidence_threshold` | string | none | Orchestrator | HITL threshold |
| `fusion:per_model_timeout_ms` | string | none | Orchestrator | Per-model timeout |
| `rate:{scope}:{identity}:{window}` | counter | window length | Kong/BFFs | Per-user and per-IP rate limits |
| `sse:last-event:{userId}` | string | 30 min | Notification | SSE reconnect cursor |
