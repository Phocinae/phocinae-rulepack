# Changelog

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
