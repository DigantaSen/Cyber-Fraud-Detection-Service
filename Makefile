# ============================================================
# AI Fraud Detection Platform — Makefile
# ============================================================
# Windows users: install make via `winget install GnuWin32.Make`
# or use the PowerShell equivalents in scripts/
# ============================================================

.PHONY: up down ps logs logs-service shell migrate \
        kafka-topics opensearch-index kong-reload reset help

## ── Start / Stop ────────────────────────────────────────────

up: ## Start all infrastructure services
	@echo "Starting platform infrastructure..."
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d --build
	@echo ""
	@echo "Waiting for all services to be healthy..."
	@docker compose ps
	@echo ""
	@echo "  Grafana:            http://localhost:3000  (admin/admin)"
	@echo "  Kong Gateway:       http://localhost:8000"
	@echo "  Kong Admin:         http://localhost:8001"
	@echo "  MinIO Console:      http://localhost:9001  (minioadmin/change_me_minio)"
	@echo "  OpenSearch Dash:    http://localhost:5601"
	@echo "  Kafka:              localhost:29092"
	@echo "  Neo4j Browser:      http://localhost:7474"
	@echo "  Prometheus:         http://localhost:9090"

down: ## Stop and remove all containers (keeps volumes)
	docker compose down

down-v: ## Stop and remove containers AND volumes (data loss!)
	@echo "WARNING: This will delete ALL data. Ctrl+C to cancel..."
	@sleep 3
	docker compose down -v

reset: down-v up ## Full reset: destroy all data + restart

## ── Status / Logs ───────────────────────────────────────────

ps: ## Show container status and health
	docker compose ps

logs: ## Tail logs from all services
	docker compose logs -f --tail=50

logs-service: ## Tail logs from one service: make logs-service s=kafka
	docker compose logs -f --tail=100 $(s)

## ── Database ─────────────────────────────────────────────────

migrate: ## Run Alembic migrations for all backend services
	@echo "Running migrations..."
	@for service in auth case evidence notification reporting audit inference-orchestrator; do \
		echo "Migrating: $$service"; \
		docker compose exec $$service alembic upgrade head 2>/dev/null || echo "  ($$service not running yet — skip)"; \
	done

## ── Kafka ────────────────────────────────────────────────────

kafka-topics: ## Provision all Kafka topics with 12 partitions
	@echo "Provisioning Kafka topics..."
	docker compose exec kafka /bin/bash /infra/kafka/provision-topics.sh

kafka-list: ## List all Kafka topics
	docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list

kafka-describe: ## Describe a topic: make kafka-describe t=case.created
	docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic $(t)

kafka-dlq: ## List messages in DLQ: make kafka-dlq t=case.created.DLQ
	docker compose exec kafka kafka-console-consumer.sh \
		--bootstrap-server localhost:9092 \
		--topic $(t) \
		--from-beginning \
		--max-messages 20

## ── Kong ─────────────────────────────────────────────────────

kong-reload: ## Reload Kong config without restart
	docker compose exec kong kong reload

kong-validate: ## Validate kong.yml before reloading
	docker compose run --rm kong kong config parse /etc/kong/kong.yml

## ── OpenSearch ───────────────────────────────────────────────


opensearch-index: ## Create the local case and evidence indexes if absent
	@for index in case_index evidence_index; do \
		curl -fsS http://localhost:9200/$$index > /dev/null || \
		curl -fsS -X PUT http://localhost:9200/$$index \
			-H 'Content-Type: application/json' \
			-d '{"settings":{"number_of_shards":1,"number_of_replicas":0}}'; \
	done

opensearch-health: ## Check OpenSearch cluster health
	curl -s http://localhost:9200/_cluster/health | python -m json.tool

## ── Utility ──────────────────────────────────────────────────

shell: ## Open shell in a service: make shell s=kafka
	docker compose exec $(s) /bin/sh

health: ## Check health of all services
	@echo "Service health status:"
	@docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
