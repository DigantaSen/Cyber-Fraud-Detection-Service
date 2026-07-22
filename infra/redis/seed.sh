#!/bin/bash
# infra/redis/seed.sh
# Seeds the 4 fusion:* Redis keys with spec-correct defaults.
# Idempotent — safe to run on every docker compose up.
#
# Default weights from T13 spec (Execution.md line 779) and §12.2:
#   scam-nlp: 0.40, counterfeit-cv: 0.20, graph-analyzer: 0.25, audio-analyzer: 0.15
# Confidence threshold: 0.60 (NFR-8.1, Execution.md line 779)
# Per-model timeout: 60000ms (raised from original T13 spec of 2000ms —
# 2s was fine for fast local/rule-based models but is far too short now that
# counterfeit-cv and audio-analyzer make real Groq API calls, which routinely
# take several seconds to tens of seconds. Flagged to the team; revisit if a
# real-time SLA depends on the original 2000ms figure.)

set -e
REDIS_HOST="${REDIS_HOST:-redis}"

echo "Seeding Redis fusion keys on host: $REDIS_HOST"

redis-cli -h "$REDIS_HOST" -a "change_me_redis" SET fusion:confidence_threshold "0.60"
redis-cli -h "$REDIS_HOST" -a "change_me_redis" SET fusion:per_model_timeout_ms "60000"
redis-cli -h "$REDIS_HOST" -a "change_me_redis" HSET fusion:weights \
    scam-nlp       0.40 \
    counterfeit-cv 0.20 \
    graph-analyzer 0.25 \
    audio-analyzer 0.15
redis-cli -h "$REDIS_HOST" -a "change_me_redis" SADD fusion:enabled_models \
    scam-nlp graph-analyzer audio-analyzer counterfeit-cv

echo "Done. Current fusion:weights:"
redis-cli -h "$REDIS_HOST" -a "change_me_redis" HGETALL fusion:weights
echo "Enabled models:"
redis-cli -h "$REDIS_HOST" -a "change_me_redis" SMEMBERS fusion:enabled_models
echo "Confidence threshold: $(redis-cli -h "$REDIS_HOST" -a "change_me_redis" GET fusion:confidence_threshold)"
echo "Per-model timeout ms: $(redis-cli -h "$REDIS_HOST" -a "change_me_redis" GET fusion:per_model_timeout_ms)"
