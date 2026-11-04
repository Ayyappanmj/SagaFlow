.PHONY: up down seed test test-unit test-e2e lint bench frontend
up:        ; docker compose up --build -d
down:      ; docker compose down
seed:      ; sh scripts/seed.sh
test:      ; sh scripts/run_tests.sh all
test-unit: ; sh scripts/run_tests.sh unit
test-e2e:  ; sh scripts/run_tests.sh e2e
lint:      ; ruff check backend scripts benchmarks
bench:     ; PYTHONPATH=backend python benchmarks/bench_core.py 300
frontend:  ; cd frontend && npm install && npm run build
