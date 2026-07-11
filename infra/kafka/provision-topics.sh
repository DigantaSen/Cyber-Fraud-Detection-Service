#!/bin/bash
# ============================================================
# Kafka Topic Provisioner
# Run with: make kafka-topics
# Or: docker compose exec kafka bash /infra/kafka/provision-topics.sh
# ============================================================
# All topics: 12 partitions — allows up to 12 parallel consumer pods
# Retention set per topic type as defined in T3 schema spec
# ============================================================

KAFKA_BIN="/opt/bitnami/kafka/bin"
# The script runs both from the Kafka container (via `make kafka-topics`) and
# from the separate kafka-init container. Docker service DNS works in both;
# localhost only works in the former.
BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"
PARTITIONS=12
REPLICATION=1  # Single broker in local; set to 3 in production

create_topic() {
  local name=$1
  local retention_ms=$2   # -1 = infinite, else milliseconds
  local cleanup_policy=${3:-delete}

  echo "Creating topic: $name"
  $KAFKA_BIN/kafka-topics.sh \
    --bootstrap-server $BOOTSTRAP \
    --create \
    --if-not-exists \
    --topic "$name" \
    --partitions $PARTITIONS \
    --replication-factor $REPLICATION \
    --config retention.ms=$retention_ms \
    --config cleanup.policy=$cleanup_policy \
    --config min.insync.replicas=1
}

echo "=== Provisioning Kafka Topics (12 partitions each) ==="

# Case topics — 7 days
CASE_TTL=$((7 * 24 * 60 * 60 * 1000))
create_topic "case.created"    $CASE_TTL
create_topic "case.updated"    $CASE_TTL
create_topic "case.assigned"   $CASE_TTL
create_topic "case.closed"     $CASE_TTL

# Evidence topics — 14 days
EVIDENCE_TTL=$((14 * 24 * 60 * 60 * 1000))
create_topic "evidence.uploaded"  $EVIDENCE_TTL
create_topic "evidence.deleted"   $EVIDENCE_TTL
create_topic "audio.uploaded"     $EVIDENCE_TTL
create_topic "audio.processed"    $EVIDENCE_TTL

# Prediction topics — 14 days
PRED_TTL=$((14 * 24 * 60 * 60 * 1000))
create_topic "prediction.requested"  $PRED_TTL
create_topic "prediction.completed"  $PRED_TTL
create_topic "prediction.failed"     $PRED_TTL
create_topic "prediction.overridden" $PRED_TTL

# Entity topics — 30 days
ENTITY_TTL=$((30 * 24 * 60 * 60 * 1000))
create_topic "entity.relationship.discovered"  $ENTITY_TTL
create_topic "fraud.ring.node.identified"      $ENTITY_TTL

# Notification topics — 7 days
NOTIF_TTL=$((7 * 24 * 60 * 60 * 1000))
create_topic "notification.requested"  $NOTIF_TTL
create_topic "notification.sent"       $NOTIF_TTL
create_topic "notification.delivered"  $NOTIF_TTL
create_topic "notification.failed"     $NOTIF_TTL
create_topic "mhaalert.sent"           $NOTIF_TTL

# Audit topics — 30 days (immutable by policy)
AUDIT_TTL=$((30 * 24 * 60 * 60 * 1000))
create_topic "audit.recorded"  $AUDIT_TTL

# User/Auth topics — 7 days
AUTH_TTL=$((7 * 24 * 60 * 60 * 1000))
create_topic "user.registered"   $AUTH_TTL
create_topic "user.login.failed" $AUTH_TTL

# Telecom / Interdiction topics — 3 days (high volume, short retention)
TELECOM_TTL=$((3 * 24 * 60 * 60 * 1000))
create_topic "telecom.event.ingested" $TELECOM_TTL
create_topic "callsession.initiated"  $TELECOM_TTL
create_topic "callsession.flagged"    $TELECOM_TTL
create_topic "intervention.requested" $TELECOM_TTL

# Bank transaction topics - 7 days
TXN_TTL=$((7 * 24 * 60 * 60 * 1000))
create_topic "transaction.ingested" $TXN_TTL

# Geospatial topics — 7 days
GEO_TTL=$((7 * 24 * 60 * 60 * 1000))
create_topic "counterfeit.scan.submitted"  $GEO_TTL
create_topic "geo.layer.updated"           $GEO_TTL

# Reporting topics — 30 days
REPORT_TTL=$((30 * 24 * 60 * 60 * 1000))
create_topic "report.generated"              $REPORT_TTL
create_topic "intelligence.package.generated" $REPORT_TTL

# DLQ topics — 7 days (for inspection and replay)
DLQ_TTL=$((7 * 24 * 60 * 60 * 1000))
for topic in case.created case.updated evidence.uploaded prediction.completed \
             notification.requested audit.recorded telecom.event.ingested \
             transaction.ingested callsession.initiated; do
  create_topic "${topic}.DLQ" $DLQ_TTL
done

echo ""
echo "=== Topic provisioning complete ==="
$KAFKA_BIN/kafka-topics.sh --bootstrap-server $BOOTSTRAP --list | sort
