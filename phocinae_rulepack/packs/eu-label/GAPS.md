# Known gaps in `eu-label` 0.1.0

The design draft carries twelve rules. Seven ship. The other five are listed here
rather than shipped with citations nobody can resolve, because a rule whose source
cannot be checked is not a gate.

| draft rule | why it is absent | what would close it |
|---|---|---|
| `r6_use_by_without_storage_conditions` | cites the FSAI shelf-life page, which was not obtained for this release | fetch `fsai.ie/.../shelf-life/labelling`, quote the storage-conditions sentence, set `evidence_level: derived` |
| `r7_date_mark_wording_invalid` | same page | same |
| `r8_date_numeric_form_unverifiable` | same page | same |
| `r9_language_not_english` | cites "In Ireland, food information must be provided in English." That sentence is on the General Labelling page and is verifiable; it is omitted here only because a single-member-state language rule escalates rather than fails and adds little. | add a corpus file holding the sentence and a `review` rule |
| `r11_net_quantity_unit_not_in_vocabulary` | cites Annex IX to Regulation (EU) No 1169/2011, whose text was not obtained. Cited as `unavailable` the engine would cap the verdict to `review`, so the rule could never fail. | obtain Annex IX, then either set `verbatim` (rule becomes a `fail`) or keep it capped and say so |

## Corrections to the design draft

The draft's `eu-label` citation quotes were checked against the live pages and
several do not appear on them. For example the draft records the allergen list
entry as `11. ***Sesame seeds*** and products thereof`, while the published page
reads `11. Sesame seeds and products thereof`. The shipped citations are taken from
the fetched pages, not from the draft.

The draft also attributes the "0.9 mm" figure for small packages to the FSAI's FAQ
page. That page states `0.9 cm`. The General Labelling page states `0.9 mm`, which
matches Annex IV to the Regulation, so the General Labelling page is cited. Both
figures and the disagreement are recorded in
`sources/fsai_legibility.md` so a reader can see the choice rather than infer it.
