# Changelog

## 0.1.2

Documentation, packaging and test coverage for the two 0.1.1 behaviour changes.
No engine behaviour differs from 0.1.1 beyond the fixes listed at the end.

Independent verification of 0.1.1 re-fetched both source pages and compared all
21 citation quotes against them: **every quote was found verbatim, and every quote
is a literal substring of the corpus file it names.** The half-width bracket in
第八条 was preserved rather than normalised. The findings were in the surrounding
material, and they are fixed here.

### Fixed — the allergen corpus note named three keys the pack does not use

The note at the end of `sources/fsai_allergens.md` claimed to list "the key each
allergen is recorded under by the shipped pack", and gave `gluten`, `sesame` and
`sulphites`. The pack uses `cereals_containing_gluten`, `sesame_seeds` and
`sulphur_dioxide_and_sulphites`. An integrator following the note would emit three
keys the rule does not recognise and get `ALLERGEN_KEY_NOT_MAPPABLE` / `review`
instead of a clean evaluation.

The note is now generated from the same list the rule is built from, so the two
cannot drift, and the build script is idempotent (verified by building twice and
comparing digests). All four corpus files were re-hashed.

### Fixed — Annex IV was cited for a number it does not contain

The justification for choosing `0.9 mm` over the FAQ page's `0.9 cm` said the
figure was "in Annex IV to Regulation (EU) No 1169/2011". Annex IV is titled
DEFINITION OF x-HEIGHT and contains no threshold; the `0.9 mm` figure is in
Article 13(3). The pack's stated ground for its choice pointed at the wrong
provision of the very instrument it says it does not quote. Corrected in the
corpus note, the rule note and GAPS.md.

### Fixed — GAPS.md understated what is missing, and was not shipped

It said the draft "carries twelve rules" and that five were left out. The draft
specifies **22**; eight ship and fourteen are absent, so nine omissions were
undocumented — including `r14_net_quantity_not_positive` and
`r16_fbo_name_address_empty`, which would be `fail` rules needing no new source.
All fourteen are now listed with what would close each.

GAPS.md is also referenced twice from the shipped `rulepack.yaml` and once from
this changelog, but was not in the wheel or the sdist: the reader was pointed at a
file that did not travel with the package. It is now package data.

### Fixed — the READMEs did not mention `subset_of`

`subset_of` is the only operator that can test an array against a list, so a pack
author had no way to discover the one thing that works for an array field — which
is the trap 0.1.1 was released to fix. The operator list, its array semantics, the
empty-array rule, the kind-for-kind comparison and the `in` / `not_in` pointer are
now in both READMEs. The published 0.1.1 landing page kept the old ten-operator
list; this release is the fix.

The READMEs also now state the pass-reason invariant, the one 0.1.1 change that can
alter an existing pack's output.

### Added — tests for both engine changes

`tests/test_packs.py` grew from 40 to 61 assertions:

* `subset_of` pinned directly at its boundaries — empty array, element outside the
  list, kind-for-kind comparison (`[1]` is not a subset of `[true]`), nested
  container as undecidable, non-array field, and the `in`-on-an-array message;
* the pass-reason drop, which had **no test at all** and could have been reverted
  with a fully green suite.

### Changed — corpus transcription notes

The corpus files said "quoted verbatim" while normalising the page's non-breaking
spaces and typographic quote marks. They now say "transcribed from", with a note
naming exactly what was normalised, and the FAQ page's URL is recorded alongside
the `0.9 cm` sentence it is quoted from.

### Open — release plumbing

0.1.1 and 0.1.0 were uploaded with `twine` and never tagged, and
`.github/workflows/release.yml` runs only on `v*` tags, so no GitHub release exists
for either. Recorded rather than repaired: the credentials to tag belong to the
publisher.

## 0.1.1

Two more packs, and two real defects they exposed.

> Release note: 0.1.1 is on PyPI, but the repository carries **no `v0.1.1` tag and
> no GitHub release** — `release.yml` only runs `on: push: tags: ["v*"]`, and the
> GitHub release job (`gh release create`) never ran. This changelog is also not
> shipped in the sdist (`pyproject.toml` has no `license-files`/`data-files` entry
> for it), so from a `pip install` there is nothing that describes this release.
> Whoever cuts the next one should also tag 0.1.1 retroactively, or the changes
> above stay unlinkable from the repository.

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

**This is the one 0.1.1 change that can alter the output of an existing pack.**
The `reasons` array of a document that both passes one rule and fails or escalates
another is now shorter by its `pass` entries. Verdicts are not affected: a `pass`
entry is only dropped when the verdict was already going to be `fail` or `review`,
so a document whose every reason is `pass` still reports `pass` with its reasons
intact. `reasons` is never emptied — at least one `fail`/`review` entry always
survives, and there is no input for which the filter can remove all of them. A
consumer that treated "a `pass` reason is present" as "this document is compliant"
must now read `verdict` instead; that reading was always the correct one. The
invariant is documented in the README under "The three-state result".

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
allergens declared" is not reported as an unmappable key. Elements are compared
kind-for-kind, exactly as `in` compares them, so `[1]` is not a subset of
`[true]` and `["1"]` is not a subset of `[1]`. The plain `in` / `not_in` operators
now say so in their error when handed an array, instead of leaving the author to
guess. Only the wording changed there: the reason code (`TYPE_ERROR`) and the
resulting `review` are identical to 0.1.0, so no existing pack's verdicts move.
The new operator is additive, and it is the only thing in 0.1.1 that an older
engine cannot read: a pack using `subset_of` fails validation on 0.1.0 with
`E_EXPR` naming the operator, rather than being silently accepted. The operator
list in the README and in `expr.py`'s own header was brought up to date.

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
