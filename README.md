# phocinae-rulepack

**Read a ledger, apply one version of a rule pack, and emit only the differences
for a human to review.** Zero model calls. Zero third-party runtime dependencies.

<p>
  <img alt="python" src="https://img.shields.io/static/v1?label=python&message=%3E%3D3.9&color=3776AB&style=flat-square">
  <img alt="deps" src="https://img.shields.io/static/v1?label=runtime%20deps&message=0&color=success&style=flat-square">
  <img alt="model calls" src="https://img.shields.io/static/v1?label=model%20calls&message=0&color=blueviolet&style=flat-square">
  <img alt="License" src="https://img.shields.io/static/v1?label=License&message=Apache-2.0&color=blue&style=flat-square">
</p>

[中文](./README-zh.md)

---

## Why this exists, in one measurement

The same decision model, asked the same question two ways, scored like this on 53
labelled commands:

| how the question was asked | recall on destructive commands |
|---|---|
| "Should this be blocked?" (boolean) | **0.00** — it passed all 31 |
| allow / ask / deny (three-way) | 0.74 |
| harmless / risky / destructive (scale) | 0.97 |

And on a policy-check battery of 14 claims, the **rule kernel scored 14/14 with
zero model calls**, while the same model, asked to approve or reject the claims
directly, rejected **all 8** compliant ones.

The conclusion this package is built on: *"the rule kernel is worth shipping as a
deterministic plugin that uses no model at all."* This is that kernel.

If you want the measurement harness rather than the kernel, see
[`phocinae-formulate`](https://github.com/Phocinae/phocinae-formulate).

## Install

```sh
pip install phocinae-rulepack==0.1.1
```

Python 3.9 or newer. No dependencies. Nothing in this package opens a socket.

## Use

```sh
# validate a pack: schema, citation text, corpus hashes
phocinae-rulepack validate expense-policy

# run one document (JSON or YAML; '-' reads stdin)
phocinae-rulepack check expense-policy claim.json

# run a ledger and get one envelope
phocinae-rulepack check expense-policy ledger.json --format json

# what ships in the box
phocinae-rulepack list --packs-dir ./packs
```

Exit codes are the contract:

| code | meaning |
|---|---|
| `0` | every result is `pass` |
| `1` | at least one `fail` |
| `2` | no `fail`, but at least one `review` (grey zone → a human decides) |
| `3` | usage or configuration error, **or an empty scan** |

Priority is fixed and total: `3 > 1 > 2 > 0`.

## The three-state result

```json
{"rulepack":"expense-policy","verdict":"fail","model_calls":0,
 "reasons":[{"rule":"r2_meal_cap","verdict":"fail","reason_code":"OVER_CATEGORY_CAP",
             "cite":["c2","c4"],"evidence":"matched:r2_meal_cap"}],
 "unmatched_paths":["id"]}
```

* **`review` means a human decides.** It is not "look again later".
* **`pass` requires a rule that says pass.** A document no rule matched is
  `review` (`NO_RULE_MATCHED`) — nothing falls through to a silent allow.
* **A missing field or a wrongly-typed field never becomes `pass`.** Missing
  fields are `review`; they are never treated as compliance.
* **A real violation outranks a missing field.** If one rule finds a breach and
  another cannot be evaluated, the verdict is `fail` and both are reported.
* **`model_calls` is a real counter, and it is always `0`.**

## The evidence model is the point

A rule is only as good as the text behind it, so a citation must say where its
text came from and whether anyone has actually read the instrument:

| `evidence_level` | meaning | can it `fail` something? |
|---|---|---|
| `verbatim` | the quote appears character-for-character in the corpus | yes |
| `derived` | an authority's restatement, not the instrument's own words | yes, with a warning |
| `unavailable` | the instrument text was **not obtained** | **no — the verdict is capped to `review`** |

That cap is the difference between an honest tool and a fake gate. A rule whose
basis nobody has read must not be able to reject a customer's paperwork. The cap
is verified in both directions by the test suite: flip the citation to `derived`
and the same input must move from `review` to `fail`.

`validate` resolves every quote against the corpus and recomputes every
sha256. A one-character change to a quote, or a wrong hash, fails validation.
`--strict` additionally rejects sample corpus and `unavailable` citations.

## Writing a pack

```yaml
schema: phocinae-rulepack/v1
id: my-check
title: What this checks
version: 0.1.0
missing_field_policy: review        # only 'review' is accepted in v1
corpus:
  - path: sources/spec.txt
    role: authority                  # authority | production | sample
    sha256: <64 uppercase hex>
citations:
  - id: c1
    source: Where the text is from
    locator: clause 4.2
    quote: "the exact words, character for character"
    document: sources/spec.txt
    evidence_level: verbatim
rules:
  - id: r1_limit
    when:
      all_of:
        - {field: amount, op: ">", value: 500}
        - {field: receipt, op: "==", value: false}
    then: {verdict: fail, reason_code: OVER_LIMIT, cite: [c1]}
    require_fields: [amount, receipt]
```

The expression language is deliberately small: `field OP value` combined with
`all_of` / `any_of` / `not`, and a `value` may be `{"ref": "other.field"}` to
compare two fields. Operators: `== != < <= > >= in not_in matches exists missing`.

There is **no** arithmetic, no custom function, no loop, and no network access.
If you need a computed value, compute it in the adapter that builds the input
document — that keeps the judgement criterion in the pack, where it can be cited
and tested.

### The two YAML traps worth knowing

Both of these parse into something plausible and wrong, which is why the loader
raises instead of guessing:

```yaml
op: >            # WRONG: a folded block scalar. It swallows the lines below.
op: ">"          # right: quote operators

note: text with a ": " colon inside    # WRONG: YAML wants a new key there
note: "text with a \": \" colon inside"  # right: quote it, or use a block scalar
```

## What ships

| pack | scenario | rules | citations | evidence level |
|---|---|---|---|---|
| `expense-policy` | S15 (the expense pre-approval demo) | 8 | 5 | all `verbatim` |
| `eu-label` | XC7 (food label compliance, Ireland) | 8 | 6 | all `derived` |
| `filing-requirements` | L10 (court filing requirements, civil first instance) | 13 | 15 | all `derived` |

> Naming note: "S15" here is the gallery's S15 expense demo. In the 182-scenario
> inventory S15 is something else (multilingual low-resource expansion).

### Where each pack's text comes from

**`expense-policy`** quotes the policy constants and the rule function of the
measurement script that produced the S15 battery, byte for byte. Everything is
`verbatim`.

**`eu-label`** quotes the Food Safety Authority of Ireland's published guidance on
Regulation (EU) No. 1169/2011. The FSAI advises on the Regulation; these are the
authority's words, not the instrument's own text, so every citation is `derived`
and `validate` says so on each run. `GAPS.md` in the pack directory lists the
rules the design draft carried but this release does not, and what would close
each one.

Two corrections were made to the design draft's citations after fetching the live
pages: the draft's allergen-list entry reads `11. ***Sesame seeds*** and products
thereof` while the page reads `11. Sesame seeds and products thereof`; and the
draft attributes the small-package x-height of `0.9 mm` to the FSAI's FAQ page,
which actually states `0.9 cm`. The `0.9 mm` figure is taken from the FSAI's
General Labelling page, which matches Annex IV to the Regulation. Both figures and
the disagreement are recorded in `sources/fsai_legibility.md` rather than smoothed
over.

**`filing-requirements`** quotes 法释〔2015〕8号 (最高人民法院关于人民法院登记立案
若干问题的规定) as republished on a court website. A re-publication rather than the
legislature's own database, so every citation is `derived`. Its citations were
checked against the fetched text and the design draft's quotes all matched.

Scope note for `filing-requirements`: a missing item escalates to `review`, never
to `fail`. Article 7 makes the remedy a one-time written notice to supplement, so
"something is missing" is not the same fact as "something is wrong". Only the copy
count — which Article 6(4) requires to match the number of defendants — can fail,
because there the recorded value itself is non-compliant.

## Testing

```sh
python tests/run_all.py
```

No network, no model, no third-party packages. The suite exits non-zero when
zero assertions ran — *"a check with nothing to check must not report success"*
is the same rule the engine applies to an empty scan.

Tests never use `tempfile`: scratch goes to `$PHOCINAE_RULEPACK_TMP`, or to a
directory beside the repository.

## What this is not

It is not a compliance, legal, medical or financial conclusion. It reports
differences for a human to review. It is not a model, and it does not call one.

## License

Apache-2.0.
