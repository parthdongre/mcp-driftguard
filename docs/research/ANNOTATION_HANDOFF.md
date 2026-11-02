# Independent annotation completion handoff

The canonical [paper protocol](../PAPER_PROTOCOL.md) and
[labeling guide](../LABELING_GUIDE.md) control this work. The research/source
cutoff remains **2026-10-15T18:06:27Z**. Engineering verification on 17 October does
not extend that scientific cutoff.

## Actual starting point

There are **494 unlabeled primary transitions from 11 repository groups**, plus
**227 separate SDK/reference records**. Exact reproduction covers all 721 records.
There are **zero independently human-labeled transitions**. Automated QA labels,
model suggestions, controlled attack fixtures and raw commit history are not human
ground truth. The private acquisition records remain outside the public repository.

The minimum target remains at least 30 contributing independent primary repository
groups and 500 independently labeled eligible transitions, preferably over 1,000.
This needs at least 19 additional contributing primary groups, with deduplication,
licensing and extraction review; the existing 494 are candidates, not 494 eligible
final labels. Broaden language and source coverage before finalizing splits.

## Human work

1. Give two actual independent annotators the same blinded candidate pack. Use
   distinct stable annotator and annotation IDs. They may inspect source diffs,
   fixed commits and documentation, but not predictions or each other's labels.
2. Run a small diverse practice batch to clarify the labeling guide, then perform
   the independent final labeling. Preserve genuine human rationale and source
   references; do not prefill inferred labels or call generated text human review.
3. Export each session's JSONL from the Research laboratory before closing it.
   Its session remains in memory, so export regularly. QA fixture exports must
   never be mixed into the research corpus.
4. Compare the original exports, inspect unmatched candidates and the rater
   confusion matrix, and adjudicate with references to both original annotation
   IDs and annotator IDs. Undefined kappa stays undefined.
5. Review extraction validity, duplicate lineages and historical licensing. Freeze
   source/label/split hashes and untouched final sources before classifier choice.

The supplied labels must use C0/C1/C2/C3 exactly as defined in the labeling guide.
A legitimate expansion requiring re-consent is not automatically malicious.
Annotation IDs prove record linkage, not authorship or actual independence; retain
the human review provenance separately.

## Validate and export genuine reviewed pairs

After installing the source checkout, run:

```bash
python experiments/score_annotations.py annotations-a.jsonl annotations-b.jsonl \
  --output annotation-agreement.json \
  --candidates candidates.jsonl \
  --adjudications adjudications.jsonl \
  --reviewed-output reviewed-pairs.jsonl
```

The CLI now verifies adjudications against the actual two original exports.
Unknown or mismatched references fail before a reviewed dataset is written.
This structural safeguard does not certify that the files were authored by humans.

## Work after annotation

Use the frozen protocol's independent attacks and five evaluation regimes.
Run matched-threshold baselines, feature/temporal/graph ablations, calibration,
repeated seeds and repository-cluster uncertainty. Keep early false alarms separate
from post-onset detection, and report C2 separately from C3. Archive raw predictions,
versions/configurations and reproducible commands.

Only then finalize paper tables and novelty claims. Current sequential development
fixtures remain `paper_claim_eligible=false`. No detector superiority, reduced
re-consent benefit, final research results or publication readiness is established.
