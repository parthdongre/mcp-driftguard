# Temporal MCP Corpus Construction Protocol

This document defines how DriftGuard constructs the real-history side of the research benchmark. The goal is a reproducible corpus of **tool-definition transitions over time**, not a collection of current MCP servers.

## Research object

For one repository/server/tool lineage, the primary object is:

```text
T0 -> T1 -> T2 -> ... -> Tn
```

where each `Ti` is a canonicalized tool definition observed in Git history after a schema-relevant change. Pairwise examples are adjacent transitions `Ti -> Ti+1`; trajectory experiments preserve the longer sequence.

The miner preserves:

- repository identity;
- source path;
- tool name;
- commit SHA;
- commit timestamp;
- canonical tool definition;
- schema hash;
- adjacent old/new lineage.

## Safety rule: target repositories are never executed

Corpus construction must not import, install, initialize, or execute code from a target MCP repository.

Permitted operations are limited to:

- cloning/fetching public Git history;
- reading repository files as text;
- `git show` over historical blobs;
- Python AST parsing;
- conservative static TypeScript/JavaScript parsing;
- JSON parsing;
- deterministic canonicalization and diff extraction.

This rule is both a security boundary and a reproducibility requirement. A repository whose effective tool schema can only be recovered by executing its code is reported as an extractor coverage gap rather than dynamically loaded.

## Public source selection

The initial source manifest is `data/public_corpus_sources.json`.

Selection seeks a mixture of:

- Python and TypeScript MCP ecosystems;
- direct SDK registration and abstraction-heavy registration;
- vendor-maintained and independent projects;
- multiple application domains;
- non-trivial version histories.

Official SDK repositories are useful parser-validation/reference sources, but they must not be counted as independent production-server repositories when reporting cross-repository generalization.

Repository selection is not intended to imply that a listed project is malicious or vulnerable. Real history is collected primarily to characterize benign maintenance and legitimate capability evolution.

## Static discovery and extractor coverage

`discover_mcp_sources()` scans a local clone for likely tool-definition sources and classifies each relevant file as:

- `extractable`: the conservative static extractor recovered at least one tool definition;
- `unsupported_pattern`: registration syntax was observed but the extractor could not safely recover the definition;
- `parse_error`: the candidate source could not be parsed by the current static method.

The corpus builder records these counts per repository. Unsupported files must not disappear silently from the methodology.

This lets the paper report an extraction-coverage limitation separately from model accuracy.

## Current supported patterns

### Python

The static Python extractor supports common `@mcp.tool(...)` definitions using the AST, including:

- function docstrings;
- primitive type annotations;
- `Optional`, `Literal`, unions and common containers;
- `Annotated[T, Field(description=...)]` metadata;
- literal defaults;
- simple module-level literal bindings such as `NAME = "workspace"` used by `name=NAME`.

Dynamic helper calls, runtime-generated schemas, wrapped callables whose effective signature depends on configuration, and arbitrary annotation constructors remain intentionally partial or unsupported.

### TypeScript / JavaScript

The static TypeScript extractor supports common literal `server.registerTool(...)` calls and a conservative subset of Zod input schemas.

Dynamic tool names, imported/computed configuration, class/registry abstractions, and arbitrary expressions are reported as coverage gaps rather than evaluated.

### JSON

Nested JSON values are searched recursively for MCP-like tool definitions containing a tool name and input schema.

## Building the corpus

The reproducible entry point is:

```bash
python experiments/build_public_corpus.py
```

Useful constrained runs include:

```bash
python experiments/build_public_corpus.py --only datalayer/jupyter-mcp-server
python experiments/build_public_corpus.py --max-repos 3
python experiments/build_public_corpus.py --no-network
```

The builder produces:

- an unlabeled JSONL annotation-candidate queue;
- a JSON summary of repository-level extractor coverage and mined history counts.

The local clone workspace is operational input and should not be committed as part of the benchmark.

## Candidate construction

For every tool lineage, identical consecutive canonical schema hashes are collapsed. Adjacent schema-changing versions become `AnnotationCandidate` records.

Candidates include deterministic diff facts such as:

- parameters added/removed;
- required fields added/removed;
- type/default/enum changes;
- newly observed sensitive terms;
- URLs and external destinations;
- cross-tool references;
- imperative terms;
- changed semantic fields.

These facts are **annotation aids only**. They do not assign C0/C1/C2/C3 ground truth.

## Human annotation

Real-history candidates are independently reviewed according to `docs/LABELING_GUIDE.md`.

The required protocol is:

1. two independent annotators review the same transition;
2. record C0/C1/C2/C3, evidence tags, and rationale;
3. calculate raw agreement and Cohen's kappa;
4. adjudicate disagreements;
5. always surface C2-vs-C3 disagreements explicitly;
6. preserve annotator identities/IDs and adjudication rationale in the research artifact.

`src/driftguard/annotation_workflow.py` provides dependency-free agreement, disagreement, and adjudication-to-dataset utilities.

The detector's own predictions must not be used as annotation evidence for the primary human-reviewed test set.

## Provenance discipline

A reviewed Git-history transition uses provenance `real_history` unless stronger evidence justifies a narrower claim.

In particular:

- C0/C1 observed in Git history need not be renamed as a special incident type;
- C2 can represent a real, legitimate capability expansion;
- a suspicious C3 label from definition evidence alone is **not automatically a verified real-world malicious incident**;
- `real_incident` should be reserved for independently verifiable incident evidence.

This distinction prevents the benchmark from converting suspicious text into unsupported claims about developer intent or runtime behavior.

## Leakage control

All versions, transitions, generated variants, and attack transformations derived from one repository remain in the same repository-level split.

The benchmark freezes train/validation/test repository assignments before final model comparison. Thresholds are selected using validation data only. Selected attack families are additionally held out from training for robustness evaluation.

## Synthetic attack side

Real Git history alone is not expected to contain enough verified malicious evolution for controlled evaluation. The malicious side therefore includes clearly labeled synthetic or controlled transformations derived from documented threat families.

Synthetic trajectories must:

- remain schema-shaped;
- preserve explicit attack-family provenance;
- never be described as observed incidents;
- include low-and-slow sequences where individual adjacent steps can remain below a local threshold while cumulative capability changes become security-significant.

Results should be broken out by provenance rather than reporting only one pooled score.

## Dataset freeze checklist

Before a paper result is considered final:

- freeze the repository source manifest;
- record source repository commit heads used for acquisition;
- freeze the annotation candidate set;
- freeze adjudicated human labels;
- record raw agreement and Cohen's kappa;
- freeze repository split and attack-family holdout manifests;
- freeze validation-selected thresholds;
- archive experiment seeds and model identifiers;
- report extractor coverage and exclusions;
- rerun the full artifact from a clean environment.

## Limitations to report

Static tool-definition recovery is not equivalent to runtime behavior verification. Some MCP servers compute names, schemas, descriptions, annotations, or wrapped signatures dynamically. DriftGuard intentionally treats such cases as extractor limitations rather than executing untrusted code to obtain a more complete schema.

The real-history corpus also does not establish malicious intent from Git diffs alone. Labels represent the security significance of observed definition evolution under available evidence, with stronger incident claims requiring independent verification.
