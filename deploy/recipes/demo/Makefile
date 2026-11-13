# DataHelix demo recipe — operator entry points. See README.md.

REPO_ROOT := ../../..

.PHONY: check-pins gate up down logs check-reverses

## Static pin check: Dockerfile digests == certified composition lock.
check-pins:
	python3 check_pins.py

## Certified-frontier pre-flight (platform ADR-0001).
gate: check-pins
	$(REPO_ROOT)/certification/scripts/deploy_gate.sh $(REPO_ROOT)/certification/composition.lock.json

up:
	docker compose up -d --build
	@echo "demo up — http://localhost:$${DEMO_PORT:-8080} (populated Aperture) /docs (API)"

down:
	docker compose down

logs:
	docker compose logs -f demo

## Reverse-edge parity on the running dataset: every inverse-declared reverse
## must match its forward slot (hydrated list, count, `some`). Edges come from
## the schema, so newly declared reverses are checked automatically.
check-reverses:
	docker compose exec -T demo python - /project < check_reverse_edges.py
