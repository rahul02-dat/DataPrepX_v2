.PHONY: up down migrate migrate-down test test-go test-py lint

DATABASE_URL ?= postgresql://dataprepx:dataprepx_dev_only@localhost:5432/dataprepx?sslmode=disable
MIGRATIONS_DIR = infra/postgres/migrations

up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

down:
	docker compose down

migrate:
	migrate -path $(MIGRATIONS_DIR) -database "$(DATABASE_URL)" up

migrate-down:
	migrate -path $(MIGRATIONS_DIR) -database "$(DATABASE_URL)" down 1

sync-schemas:
	cp shared/schemas/*.json services/gateway-go/internal/jobs/schemas/

check-schema-sync:
	git diff --exit-code services/gateway-go/internal/jobs/schemas/ || \
	(echo "Error: gateway-go's embedded schema copy is out of sync with shared/schemas/. Run 'make sync-schemas' and commit." && exit 1)

test: test-go test-py

test-go:
	cd services/gateway-go && go test ./...

test-py:
	cd services/ml-engine-py && pytest tests/ -v
	cd services/agent-orchestrator && pytest tests/ -v

lint:
	cd services/gateway-go && gofmt -l . && golangci-lint run || true
	cd services/ml-engine-py && ruff check . && black --check .
	cd services/agent-orchestrator && ruff check . && black --check .