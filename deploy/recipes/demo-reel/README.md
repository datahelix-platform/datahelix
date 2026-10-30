# DataHelix `demo-reel` — the populated showcase, with the conversational panel

The [`demo`](../demo/) recipe plus **Reel**, the planning service behind Aperture's
conversational query panel (Aperture ADR-0039). You can type *"which RNA-seq datasets were
aligned to GRCh38?"*, then *"just the ones quantified as TPM"*. Each turn returns a query that
Mosaic has validated, shown in plain language and in the query builder, and it runs only when
you click.

```bash
cd deploy/recipes/demo-reel
make up            # builds (generates + bakes the dataset) and starts both services
make smoke         # one turn end to end: Aperture → Mosaic → Reel → model → Mosaic
open http://localhost:8080/?view=query
```

> Same posture as `demo`: **no auth**, single-user, localhost/trusted network only, and the data
> is **synthetic** and **immutable**. Unlike `demo`, it **calls a hosted model on every chat
> turn**, using your credentials (see [Model credentials](#model-credentials)).

## Shape

Two containers:

| Service | What | Pinned by | Certified? |
|---|---|---|---|
| `demo` | Aperture + Mosaic (`serve --graphql --mcp`) + the baked dataset, one image | Dockerfile, `@sha256` | **yes**: the frontier pair in `certification/composition.lock.json` |
| `reel` | The planner. Mosaic delegates each chat turn to it | docker-compose.yml, `@sha256` | **no**: Reel is not in the composition lock |

Reel gets its own container for three reasons:
- It is the only process that holds model credentials.
- It is the only pin outside the certified lock.
- Separating it keeps the data image an exact certified-pair build, lets Reel be bumped without
  regenerating the dataset, and keeps credentials out of every image layer.

How the containers connect:
- **Aperture → Mosaic.** Aperture reaches the planner only through Mosaic, over the existing
  same-origin `/graphql` (`converseQuerySpec`).
- **Mosaic → Reel.** Mosaic calls Reel at `http://reel:9100/turn`.
- **Reel → Mosaic.** Reel reads its grounding (the schema it plans against) from Mosaic's MCP
  boundary. It does this through an **internal nginx listener on :8100 that proxies `/mcp` and
  nothing else**, and that port is never published.

The internal listener has three effects:
- Mosaic stays bound to loopback.
- Mosaic's MCP Host-header guard (mosaic#214) stays at its default, because nginx presents a
  loopback Host.
- The planner cannot reach REST or GraphQL at all.

Reel plans and never executes (Reel ADR-0007). Mosaic re-validates every QuerySpec it returns
before Aperture sees it, and nothing runs without a click.

## Datasets: `DEMO_DATASET=brainbank|small`

| | `brainbank` *(default)* | `small` |
|---|---|---|
| Schema | [`brainbank-hippo-schema`](https://github.com/VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema) @ `43a93d6`, 86 entity types (same as `demo`) | [`mosaic-demo-small`](https://github.com/BU-Neuromics/mosaic-demo-small) @ `7399694`, 15 entity types |
| Built by | `demo`'s own `build-dataset.sh` (reused, not copied) | that repo's own `generate.py` (`build-small.sh` mirrors its Makefile) |
| Scale | `DEMO_COUNTS` (as `demo`) | fixed, about 8,800 records; `DEMO_COUNTS` does not apply |
| Planner grounding | about 71k prompt tokens per turn | much smaller |
| Matches `demo` screenshots | yes | no |

```bash
DEMO_DATASET=small make up      # switch; both images are cached separately
```

### How the planner holds up on each (measured 2026-10-17, Reel 0.1.0)

`make eval` runs Reel's discovery harness against whatever is running. The case set ships
inside the data image, next to the schema it describes. Each case runs 3 times and counts as
reliable only if all 3 runs pass.

| Dataset × model | Cases reliable | Notes |
|---|---|---|
| brainbank × Haiku 4.5 *(default model)* | 5 / 12 | about 5 s per turn |
| brainbank × Sonnet 5 | 6 / 12; **24 / 27 runs** on the answerable cases | |
| small × Haiku 4.5 | 8 / 22 | its own frozen + new-collections sets |

Reading these numbers:
- **The planner is not more reliable on the small schema it was developed against.**
  Brain-bank holds up, so it is the default.
- **Both negative brain-bank cases (b11, b12) fail only on grading.** The planner correctly says
  the topic is not modelled, then mentions a field it *does* have, and the grader counts any
  named field as a failure.
- **The weak spot is open "what do we have on…" questions.** Haiku often answers with a
  clarifying question instead of naming the field. Concrete filter requests are reliable.

**For screenshots:**
- **Prompts that worked every time** (2 trials each, follow-up turns included):
  - *"which RNA-seq datasets were aligned to GRCh38?"* → *"just the ones quantified as TPM"*
  - *"show me paired-end genome sequencing assays run on Illumina"* → *"with reads longer than
    100 bp"*
- **Mostly reliable:**
  - *"show me donors older than 70 with a post-mortem interval under 24 hours"* → *"now only
    the female ones"*. It came back as an error turn on one of the two trials; just send it
    again.
- **Use a larger dataset.** At default scale two filters often leave one or two rows, because
  800 datasets are spread across about a dozen dataset subtypes. For fuller result tables:

  ```bash
  DEMO_COUNTS="donors=2000 samples=12000 datasets=4000 assays=4000 processes=1500 analyses=800" make up
  ```

## Model credentials

The planner is the only service that calls a model:
- **Default model:** Bedrock `global.anthropic.claude-haiku-4-5`. Credentials come from
  `~/.aws`, mounted read-only (`AWS_DIR` to change), or from `AWS_ACCESS_KEY_ID`/... in the
  environment.
- **Other providers:** set `REEL_MODEL` (a litellm model string) plus `ANTHROPIC_API_KEY` or
  `OPENAI_API_KEY`.
- **Missing credentials:** `make up` refuses to start without any, rather than letting every
  chat turn fail.

```bash
REEL_MODEL=bedrock/global.anthropic.claude-sonnet-5 make up    # better discovery answers; see Known issues
```

The planner runs as **your** UID, not the image's `reel` user, because `~/.aws/credentials` is
normally mode 600 and uid 10001 could not read it through the bind mount.

## Operating it

| Target | |
|---|---|
| `make up` / `down` | Build + start / stop both services |
| `make smoke` | One turn through `/graphql`. Passes on `proposal` or `clarification`; `SMOKE_UTTERANCE=...` to change it |
| `make check-reverses` | Every inverse-declared reverse edge in the baked dataset matches its forward slot (hydrated list, count, `some`); no model calls. Edges come from the schema, so new ones are checked automatically |
| `make eval` | Reel's discovery harness on the baked dataset's cases (`SAMPLES=3`, `EVAL_ARGS="--model ..."`); every case spends model calls |
| `make logs` / `logs-planner` | Follow everything / just the planner |
| `make restart-planner` | Restart Reel; it fetches its grounding once, at startup |
| `make check-pins` | Certified pair == lock; planner digest-pinned, reported **UNCERTIFIED** |
| `make gate` | The ADR-0001 deploy pre-flight, for the certified pair only |

On a cold start the planner exits once or twice with *"Could not reach Mosaic's MCP boundary"*
until Mosaic is listening, then grounds and serves. That's expected: `restart: unless-stopped`
resolves the race. The chat panel appears once Mosaic is up. Turns sent before the planner has
grounded come back as error turns.

## Known issues (Reel 0.1.0)

- **Dropped `status` field.** Sonnet 5 sometimes returns a correct turn but leaves out the
  required `status` field. Reel rejects it, and the panel shows an error turn. It happened on 3
  of 3 runs of one eval case. Haiku seems to do the same occasionally, but Reel doesn't log the
  reason (see the next item).
- **Unexplained 502s.** When a turn fails like this, Reel answers Mosaic with an HTTP 502 and
  logs no reason, so `make logs-planner` shows only `502 Bad Gateway`.
- **Rejected proposals.** *"which datasets were produced by failed analyses?"* is turned down by
  Mosaic's validation (`NOT_PREDICATE_FILTERABLE`). `Dataset.produced_by` targets the abstract
  `Activity`. The panel reports it correctly as an error; avoid it on camera.

## Certification

- **The data image** is the `demo` posture: built FROM the digest-pinned certified pair.
  `make check-pins` fails on drift and `make gate` is the deploy pre-flight.
- **The planner** is digest-pinned but **outside the gate**. `check_pins.py` says so on every
  run rather than passing it silently, and if the lock gains a `reel` entry it is compared like
  the others.
- **Build inputs** (the data generator, both schemas) are pinned separately. The two datasets
  use different linkml-data-gen commits:
  - `small` needs `hints`, which `demo`'s pin (`6d1386f`, merged onto a side branch rather than
    `main`) lacks.
  - linkml-data-gen `main` (`e0454b2`) has `hints` and its own fix for the same id collisions.

## Limitations

Everything in [`demo`'s list](../demo/README.md#limitations), plus:
- Every chat turn is a paid model call carrying the full schema grounding.
- `evals/brainbank.yaml` is a temporary home. Cases belong with the schema they describe
  (Reel's Phase A6), so it should move to `brainbank-hippo-schema` and be pinned from there.
