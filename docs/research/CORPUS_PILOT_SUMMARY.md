# Actual private corpus acquisition

Frozen source cutoff: **2026-10-15T18:06:27Z**, the initial request timestamp.
Author/committer timestamps were audited. No third-party MCP runtime or package
was executed/imported; no target credentials were used.

| Measure | Actual count |
|---|---:|
| Candidate repositories considered | 30 |
| Successfully statically processed / explicit skips | 27 /3 |
| Production-source transitions awaiting annotation | **494** |
| Distinct contributing repository groups | **11** |
| Production tool lineages / source files | 194 /30 |
| Separate SDK/reference transitions | 227 |
| Independently human-labeled records | **0** |
| Exact reproduced records | 721 /721 |
| Rejected duplicate IDs / future revisions | 0 /0 |

| Production repository group | Transitions |
|---|---:|
| Snowflake-Labs/mcp | 1 |
| alpacahq/alpaca-mcp-server | 3 |
| datalayer/jupyter-mcp-server | 81 |
| financial-datasets/mcp-server | 3 |
| haris-musa/excel-mcp-server | 6 |
| makeplane/plane-mcp-server | 1 |
| mobile-next/mobile-mcp | 5 |
| neo4j-contrib/mcp-neo4j | 33 |
| oracle/mcp | 89 |
| sooperset/mcp-atlassian | 267 |
| zilliztech/mcp-server-milvus | 5 |

Atlassian contributes ~54% of primary rows. Coverage is 489 Python and 5 TypeScript
transitions. Current-head discovery and unsupported wrappers/dynamic registrations
limit extraction. A mined definition is not a verified runtime schema; real
history is not a benign label or evidence of deployment. Shared SDKs/forks can
undermine independence between repository groups. Review these before evaluation.

The Kubernetes Go server and large Microsoft/AWS collections were explicitly
skipped. Zero extracted transitions elsewhere is not evidence of no evolution.
SDK/test/example/documentation sources are kept out of the primary stratum.
No classifier metrics follow from acquisition.

The private handoff contains JSONL, two annotation-ready shards under 900 KiB,
upstream commits, extraction-source hashes, licenses, commands, summaries and
reproduction evidence. Raw candidates/source mirrors are not committed here.
Historical/file-level licensing still requires review before redistribution.

From a matching code checkout:

```bash
python experiments/reproduce_frozen_corpus.py \
  --evidence /absolute/path/to/private-handoff/corpus \
  --workspace /absolute/path/to/local-public-repository-checkouts \
  --output /absolute/path/to/reproduction-output
```

The reproducer verifies eight recorded extraction-source hashes and pinned
upstream origins/commits. Missing histories require explicit `--fetch`; modified
checkouts are rejected. Only Git and this project's static extractor run. Complete
records are compared with the frozen primary+reference union. The current offline
run exactly reproduced all 721 records; final benchmark eligibility remains false.
