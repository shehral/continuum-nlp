# Smoke Tests — Known Issues & Verification Notes

## Runtime verification status

The agent that wrote these tests could not execute pytest itself (bash
sandbox blocked `pytest`, `python -c`, `curl`). The user should run Layer 1
once from their shell to confirm all tests pass before demo day.

Expected green run:

```bash
cd apps/api && .venv/bin/pytest tests/smoke/ -m smoke -v
```

## Expected pass count

| Test file | Test count | Est. runtime |
|---|---|---|
| test_health.py | 3 | <1s |
| test_graph_data.py | 4 | <2s |
| test_decision_detail.py | 2 | ~3s (20 decisions) |
| test_embeddings_dim.py | 2 | <2s |
| test_indexes_exist.py | 3 | <1s |
| test_ask_pipeline.py | 8 (6 parametrized + 2) | 3-8 min (LLM) |
| **Total** | **22** | **~5-10 min** |

## Anticipated real issues (not bugs in the tests)

1. **test_ask_pipeline.py on host Ollama** may exceed the 180s httpx
   timeout for a cold-start llama3.2. If any query times out, warm the
   model first: `curl -s http://localhost:11434/api/generate -d '{"model":"llama3.2","prompt":"hi"}'`.

2. **test_health_ready_all_deps_healthy** will fail if any of the three
   docker dependencies (postgres/neo4j/redis) went down between boot and
   the test run. Check `docker compose ps` — should show 4 healthy.

3. **test_vector_indexes_are_768_dimensional** reads from
   `SHOW VECTOR INDEXES`. If Neo4j returns the `options.indexConfig` under
   a differently-cased key in your Neo4j version, the dim check may falsely
   fail. Fallback: inspect via `CALL db.indexes()` manually.

## Environment overrides

- `API_BASE_URL` (default: `http://localhost:8000`)
- `SMOKE_NEO4J_URI` (default: `bolt://localhost:7688`)
- `SMOKE_NEO4J_USER` (default: `neo4j`)
- `SMOKE_NEO4J_PASSWORD` (default: `neo4jpassword`)

Set these to point smoke tests at the GCP deployment on demo day:

```bash
API_BASE_URL=http://<gcp-ip>:8000 \
SMOKE_NEO4J_URI=bolt://<gcp-ip>:7688 \
  .venv/bin/pytest tests/smoke/ -m smoke -v
```
