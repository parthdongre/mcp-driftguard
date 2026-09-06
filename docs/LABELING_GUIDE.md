# DriftGuard Dataset Labeling Guide

This guide defines the annotation protocol for the paper dataset. The target is not simply "safe" versus "malicious". DriftGuard separates semantically equivalent changes, benign maintenance, legitimate capability expansion that should trigger re-consent, and malicious/suspicious drift.

## Unit of annotation

Annotators receive:

- repository/server/tool identity;
- previous approved tool definition;
- current tool definition;
- field-level structural diff;
- raw and canonical representations;
- repository commit/release context when available.

The label belongs to the **transition** from the old definition to the new definition, not to the new definition in isolation.

## C0 - No meaningful change

Use `C0` when the update does not materially change tool meaning, contract, authority, scope, destination, or security posture.

Typical evidence:

- formatting or JSON key-order changes;
- whitespace-only changes;
- semantically equivalent restatement;
- metadata change with no operational meaning.

Do not use C0 merely because the text difference is small.

## C1 - Benign maintenance

Use `C1` when the update is meaningful but remains within the previously approved capability envelope.

Typical evidence:

- clearer documentation;
- typo correction;
- bug-fix wording;
- additional examples;
- safe optional parameter that does not increase authority;
- narrowing a constraint or scope;
- output-description clarification.

If the change creates a new power, broader scope, new destination, new sensitive input, or destructive effect, consider C2 instead.

## C2 - Legitimate capability expansion requiring re-consent

Use `C2` when the change appears legitimate in project context but exceeds the previously approved capability envelope.

Examples:

- read-only tool becomes able to modify files;
- tool can newly access a broader repository/path scope;
- tool adds network transmission;
- new credential/token parameter is required for a legitimate integration;
- new email/payment/database capability is added as a documented feature;
- new destructive action is intentionally introduced and disclosed.

The key distinction is:

> legitimate does not mean safe to silently inherit prior consent.

C2 exists to evaluate whether a system can learn a **consent boundary**, not only a maliciousness boundary.

## C3 - Malicious or suspicious semantic drift

Use `C3` when there is evidence of poisoning, covert escalation, deceptive tool-selection manipulation, exfiltration, unauthorized sensitive access, or another security-significant change that should not be accepted through normal re-consent.

Typical evidence:

- hidden or deceptive prompt instructions;
- "ignore previous instructions" / policy override content;
- cross-tool shadowing or steering intended to manipulate tool choice;
- covert external upload/disclosure not implied by the original purpose;
- credential collection unrelated to legitimate function;
- malicious or deceptive defaults;
- unauthorized destructive/execute capability;
- schema text designed to conceal material authority from the user/host.

A large capability expansion is not automatically C3. Where legitimate intent is plausible but cannot be established, mark the item for adjudication rather than inventing intent.

## Required evidence tags

Annotators should record one or more structured evidence tags, such as:

- `formatting_only`
- `semantic_equivalence`
- `documentation_clarification`
- `bug_fix`
- `optional_non_sensitive_parameter`
- `constraint_narrowing`
- `new_capability`
- `broader_scope`
- `new_sensitive_parameter`
- `new_external_destination`
- `new_destructive_effect`
- `new_execution_effect`
- `credential_access`
- `data_disclosure`
- `hidden_instruction`
- `cross_tool_steering`
- `policy_override`
- `malicious_default`
- `uncertain_intent`

## Annotation workflow

1. Read the old definition without the new definition and summarize the approved capability envelope.
2. Read the new definition.
3. Inspect structural changes by field.
4. Record capability additions/removals separately from textual changes.
5. Assign evidence tags.
6. Assign C0/C1/C2/C3.
7. Write a one- or two-sentence rationale.
8. Mark uncertainty or second-review requirement.

Do not use model predictions as annotation evidence for the primary human-labeled test set.

## Two-annotator protocol

For the manually reviewed subset:

- two annotators label independently;
- calculate raw agreement and Cohen's kappa;
- disagreements involving C2/C3 are always adjudicated;
- preserve both original labels and the adjudicated label;
- the adjudicator must provide a written rationale.

## Leakage rules

Train/validation/test splits are performed at repository level. Multiple versions, generated variants, and attack transformations derived from one repository must remain in the same split.

Attack-family-held-out evaluation should additionally keep selected attack families entirely outside training.

## Synthetic data policy

Synthetic or controlled mutations must be identified as such. They must not be represented as real incidents. The primary benchmark should report results separately for:

- real benign history;
- controlled benign transformations;
- synthetic attacks;
- real incidents, if independently verifiable;
- low-and-slow trajectories.

## Important limitation

Tool-definition text cannot prove runtime behavior or developer intent. Labels describe the security significance of observed definition evolution under available evidence. Runtime verification is complementary and should be discussed as such in the paper.
