# Changelog

## 0.1.1

Two more packs, and two real defects they exposed.

### Added — `eu-label` (XC7)

Food label compliance against the Food Safety Authority of Ireland's published
guidance on Regulation (EU) No. 1169/2011. Eight rules: the x-height thresholds
(1.2 mm, and 0.9 mm below 80 cm²), a missing mandatory particular, unemphasised
allergens, an allergen key outside the Annex II vocabulary, an alcoholic drink
above 1.2% without a strength declaration, and the field-of-vision grouping.

Every citation is `derived`: the FSAI advises on the Regulation, so these are the
authority's words rather than the instrument's own text, and the validator says so
on each run. The corpus is excerpted from pages fetched live, and the build script
refuses to write the pack unless every declared quote is present in the file it
names.

### Added — `filing-requirements` (L10)

Court filing requirements for a civil first-instance case, against 法释〔2015〕8号.
Thirteen rules. A missing item escalates to `review` and never to `fail`, because
Article 7 makes the remedy a one-time written notice to supplement; only the copy
count can fail, because Article 6(4) requires it to match the number of
defendants. It is the only shipped rule that compares two input fields
(`{"ref": ...}`).

### Fixed — a pass reason beside a fail reason

The engine reported both `NO_REQUIREMENT_GAP` ("no departure found") and a rule's
failure on the same document. Both rules were individually correct; reporting them
together is a contradiction. The engine now drops `pass` reasons whenever
something stricter fired.

This belongs in the engine rather than in every pack: a pack cannot reliably
express "no other rule fired", and repeating the condition in each pass rule would
be wrong the first time someone forgot. Doing it centrally also makes the
invariant hold for packs written before the change.

### Fixed — `eu-label`'s allergen rule could never fire

The first version tested the `allergens_declared` **array** for list membership.
`in` / `not_in` take a scalar on the left, so the engine reported `TYPE_ERROR` and
the rule never matched anything. Worse, it looked like caution: an operator that
never fires produces `review`, which is indistinguishable from a deliberately
conservative rule.

The `subset_of` operator was added for this: every element of the array must
appear in the given list. An empty array is a subset of everything, so "no
allergens declared" is not reported as an unmappable key. The plain `in` /
`not_in` operators now say so in their error when handed an array, instead of
leaving the author to guess.

### Added — pack behaviour tests

`tests/test_packs.py`, 40 assertions. Validity is not behaviour: a pack can
validate cleanly and still never fire, which is exactly what happened above. The
new suite drives both packs over records that must pass, must fail, and must
escalate, and includes the boundary cases (exactly 80 cm²; copies equal to the
defendant count; x-height at the threshold).

### Corrections to the design draft's citations

The draft's `eu-label` quotes do not all appear on the pages it cites. The
allergen-list entry is recorded as `11. ***Sesame seeds*** and products thereof`
where the page reads `11. Sesame seeds and products thereof`, and the draft
attributes the small-package `0.9 mm` figure to the FSAI FAQ page, which states
`0.9 cm`. The shipped citations come from the fetched text; both figures and the
disagreement are recorded in `sources/fsai_legibility.md`.

The draft's `filing-requirements` quotes were checked against the fetched text and
all fifteen matched.

### Not shipped, on purpose

`eu-label` carries seven of the draft's twelve rules and `filing-requirements`
carries thirteen. The rest need sources this release did not obtain (the FSAI
shelf-life page for the date-mark rules; Annex IX for the net-quantity unit rule).
A rule whose citation cannot be resolved is not a gate — with `evidence_level:
unavailable` the engine caps the verdict to `review`, so the rule could never
fail. `phocinae_rulepack/packs/eu-label/GAPS.md` lists each omission and what
would close it.

## 0.1.0 — unreleased

First release. The deterministic rule-pack engine, with one shipped pack.

### What it does

* Loads a rule pack (schema `phocinae-rulepack/v1`), validates its schema, resolves
  every citation character-for-character against a declared corpus, and recomputes
  every corpus sha256.
* Runs one document or a whole ledger through the pack and emits a three-state
  verdict (`pass` / `fail` / `review`) with a reason code and citation per fired
  rule.
* Exit codes: `0` all pass, `1` a fail exists, `2` a review exists, `3` usage or
  configuration error **or an empty scan**. Priority is fixed: `3 > 1 > 2 > 0`.
* Zero model calls, zero third-party runtime dependencies, no network access.

### Fail-closed behaviour

* A document no rule matched is `review` (`NO_RULE_MATCHED`); nothing falls
  through to a silent allow.
* A missing field is `review`, never `pass`; a real violation outranks a missing
  field and both are reported.
* A citation whose instrument text was not obtained (`evidence_level:
  unavailable`) **caps** any rule citing it to `review`, with the reason code
  prefixed `CAPPED_`. Such a rule can never reject anyone's paperwork.
* An empty scan fails: no rules, no citations, no input, or a document no rule
  reads are all errors, not successes.

### Shipped pack

* `expense-policy` — 8 rules, 5 citations, 3 corpus files. Reproduces the S15
  (gallery) measured battery at **14/14 with zero model calls**.

### Process notes kept on purpose

Three defects found by building this rather than by reading it, all now covered
by tests:

1. `AnyOf` subclassed `AllOf`, so `isinstance(node, AllOf)` was true for every
   disjunction and **every `any_of` was evaluated as a conjunction**. It silently
   turned "within any category cap" into "within every category cap" and made the
   pass rule never fire (14/14 became 6/14).
2. The YAML subset parser matched a key at the first colon, so
   `origin: https://host/path` was read as a mapping with the key `http`.
3. A `sha256` written as an unquoted run of digits is parsed by YAML as an
   integer, which rejected a legitimate pack with a *type* error.
