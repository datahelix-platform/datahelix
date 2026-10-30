# DataHelix demo-reel recipe — operator entry points. See README.md.

REPO_ROOT := ../../..

DEMO_DATASET ?= brainbank
DEMO_PORT    ?= 8080
AWS_DIR      ?= $(HOME)/.aws

# The planner runs as the invoking user so it can read a mode-600
# ~/.aws/credentials through the bind mount (see docker-compose.yml).
DOCKER_UID := $(shell id -u)
DOCKER_GID := $(shell id -g)
ENV = DEMO_DATASET=$(DEMO_DATASET) DEMO_PORT=$(DEMO_PORT) AWS_DIR=$(AWS_DIR) \
      DOCKER_UID=$(DOCKER_UID) DOCKER_GID=$(DOCKER_GID)

.PHONY: check-pins gate up down logs logs-planner restart-planner smoke eval check-reverses

## Static pin check: certified pair == lock; planner digest-pinned (uncertified).
check-pins:
	python3 check_pins.py

## Certified-frontier pre-flight (platform ADR-0001) — for the data image's pair.
gate: check-pins
	$(REPO_ROOT)/certification/scripts/deploy_gate.sh $(REPO_ROOT)/certification/composition.lock.json
	@echo "gate covers mosaic + aperture only — the reel planner is not certified"

## Build (generates + bakes the chosen dataset) and start both services.
up: _credentials
	env $(ENV) docker compose up -d --build
	@echo ""
	@echo "demo-reel up ($(DEMO_DATASET)) — http://localhost:$(DEMO_PORT)"
	@echo "  the chat panel appears once the planner has grounded ('make logs-planner');"
	@echo "  'make smoke' sends one turn end to end"

down:
	docker compose down

logs:
	docker compose logs -f

## Follow the planner: grounding fetch, per-turn model calls, failures.
logs-planner:
	docker compose logs -f reel

## Restart the planner (it fetches its grounding once, at startup).
restart-planner:
	docker compose restart reel

## One discovery turn through the public /graphql seam, the way Aperture's
## panel sends it. Passes on a 'proposal' or 'clarification' — either means
## Aperture -> Mosaic -> Reel -> model -> Mosaic re-validation all worked.
## An 'error' turn, or no converseQuerySpec at all, fails.
SMOKE_UTTERANCE ?= what do we know about how old the donors were?
smoke:
	@printf '%s' '$(SMOKE_UTTERANCE)' | python3 -c 'import json,sys; print(json.dumps({"query": "mutation($$u: String!) { converseQuerySpec(utterance: $$u) { turn { status message querySpec } } }", "variables": {"u": sys.stdin.read()}}))' \
	| curl -sS --max-time 200 -X POST http://localhost:$(DEMO_PORT)/graphql \
		-H 'Content-Type: application/json' --data-binary @- \
	| python3 -c 'import json,sys; r = json.load(sys.stdin); \
errs = r.get("errors"); \
sys.exit("smoke FAIL: " + json.dumps(errs)[:600] + "\n  (no converseQuerySpec? the planner is not wired: MOSAIC_EXON_URL unset)") if errs else None; \
t = r["data"]["converseQuerySpec"]["turn"]; \
print("turn status:", t["status"]); print("message:", " ".join(t["message"].split())[:500]); \
print("querySpec:", json.dumps(t["querySpec"])[:500]) if t.get("querySpec") else None; \
sys.exit(0 if t["status"] in ("proposal", "clarification") else "smoke FAIL: " + t["status"] + " turn — make logs-planner")'

## Score the planner on the baked dataset's discovery cases (Reel's harness;
## every case spends model calls, SAMPLES per case). The cases ship inside the
## data image at /project/evals/discovery.yaml, alongside the schema they
## describe, so this always grades the dataset that is actually running.
SAMPLES ?= 3
eval:
	@mkdir -p .eval
	docker compose exec -T demo cat /project/evals/discovery.yaml > .eval/discovery.yaml
	env $(ENV) docker compose run --rm --no-deps -T \
		-v "$(CURDIR)/.eval:/evals:ro" --entrypoint python \
		reel -m reel.evals.run --cases /evals/discovery.yaml -n $(SAMPLES) $(EVAL_ARGS)

# Fail before a ten-minute build, not on the first chat turn.
_credentials:
	@if [ -n "$$ANTHROPIC_API_KEY$$OPENAI_API_KEY$$AWS_ACCESS_KEY_ID" ] \
	   || [ -f "$(AWS_DIR)/credentials" ] || [ -f "$(AWS_DIR)/config" ]; then :; else \
		echo "demo-reel: no model credentials found — the planner would fail every turn." >&2; \
		echo "  Bedrock (default model): an AWS profile in $(AWS_DIR), or AWS_ACCESS_KEY_ID/..." >&2; \
		echo "  Other providers: REEL_MODEL plus ANTHROPIC_API_KEY or OPENAI_API_KEY" >&2; \
		exit 1; \
	fi

## Reverse-edge parity on the running dataset: every inverse-declared reverse
## must match its forward slot (hydrated list, count, `some`). Edges come from
## the schema, so newly declared reverses are checked automatically.
check-reverses:
	docker compose exec -T demo python - /project < ../demo/check_reverse_edges.py
