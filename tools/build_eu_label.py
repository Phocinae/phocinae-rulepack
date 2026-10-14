# -*- coding: utf-8 -*-
"""Write the `eu-label` pack: computed hashes, and every quote verified against
the corpus file it names.

Rule scope for 0.1.0 is narrower than the design draft, on purpose. The draft
carries twelve rules; three of them (date-mark wording, date form, use-by storage
conditions) cite a page this build has not fetched, and the unit rule cites
Annex IX, whose text was not obtained. A pack whose citations cannot be resolved
is not a gate, so those rules are left out and listed as known gaps rather than
shipped with quotes nobody can check.
"""
import hashlib
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PACK = (r"D:\Projects\phociane-project\_work\build\phocinae-rulepack"
        r"\phocinae_rulepack\packs\eu-label")
SRC = os.path.join(PACK, "sources")

CORPUS = [
    ("sources/fsai_mandatory_particulars.md", "authority",
     "FSAI · Food Information to Consumers — mandatory particulars (a)-(l)",
     "https://www.fsai.ie/business-advice/labelling/food-information-to-consumers"),
    ("sources/fsai_allergens.md", "authority",
     "FSAI · the 14 allergens listed in Annex II",
     "https://www.fsai.ie/business-advice/labelling/food-information-to-consumers"),
    ("sources/fsai_allergen_display.md", "authority",
     "FSAI · how allergen information must be displayed",
     "https://www.fsai.ie/business-advice/labelling/food-information-to-consumers"),
    ("sources/fsai_legibility.md", "authority",
     "FSAI · Labelling - General Labelling — minimum font size",
     "https://www.fsai.ie/business-advice/labelling/labelling-general-labelling"),
]

CITATIONS = [
    ("c_mand_a_l", "fsai_mandatory_particulars.md",
     "FSAI · Food Information to Consumers（Regulation (EU) No. 1169/2011 释义）",
     "What mandatory information must appear on the label of a prepacked food? (a)-(l)",
     "(l) a nutrition declaration"),
    ("c_field_of_vision", "fsai_mandatory_particulars.md",
     "FSAI · 同上（同视野要求脚注）",
     "What mandatory information must appear on the label of a prepacked food? (footnote)",
     "*must appear in the same field of vision"),
    ("c_allergens_14", "fsai_allergens.md",
     "FSAI · 同上（Annex II 过敏原清单）",
     "What are the 14 allergens?",
     "The 14 allergens as listed in Annex II are as follows:"),
    ("c_allergen_emphasis", "fsai_allergen_display.md",
     "FSAI · 同上（过敏原标注方式）",
     "How must allergen information be displayed on the label?",
     "They must be emphasised through being typeset in a way that clearly distinguishes "
     "them from the rest of the list of ingredients, for example by means of font, style "
     "or background colour."),
    ("c_font_12", "fsai_legibility.md",
     "FSAI · Labelling - General Labelling（最小字号）",
     "Minimum Font Size",
     "in characters using a font size where the x-height is equal to or greater than 1.2 mm"),
    ("c_font_09", "fsai_legibility.md",
     "FSAI · 同上（小包装阈值）",
     "Minimum Font Size",
     "In case of packaging or containers, the largest surface of which has an area of less "
     "than 80 cm2, the x-height of the font size must be equal to or greater than 0.9 mm."),
]

ALLERGEN_VOCAB = [
    "celery", "cereals_containing_gluten", "crustaceans", "eggs", "fish", "lupin",
    "milk", "molluscs", "mustard", "nuts", "peanuts", "sesame_seeds", "soybeans",
    "sulphur_dioxide_and_sulphites",
]

MANDATORY_FIELDS = [
    "name", "ingredients_list", "quantity_of_ingredients", "net_quantity", "date_mark",
    "storage_conditions", "fbo_name_address", "country_of_origin", "instructions_for_use",
    "nutrition_declaration",
]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def read(name):
    with open(os.path.join(SRC, name), "r", encoding="utf-8") as handle:
        return handle.read()


bodies = {}
failures = []
for path, _role, _title, _url in CORPUS:
    name = os.path.basename(path)
    if not os.path.isfile(os.path.join(PACK, path.replace("/", os.sep))):
        failures.append("missing corpus file %s" % path)
        continue
    bodies[name] = read(name)

print("=== quote verification (each against the file it names) ===")
for cid, filename, _source, _locator, quote in CITATIONS:
    body = bodies.get(filename)
    ok = body is not None and quote in body
    print("  %-22s %-34s %s" % (cid, filename, "OK" if ok else "NOT FOUND"))
    if not ok:
        failures.append("citation %s: quote absent from %s" % (cid, filename))
        print("        quote: %r" % quote[:120])
if failures:
    for failure in failures:
        print("FAIL %s" % failure)
    sys.exit(1)
print("  all %d quotes resolve\n" % len(CITATIONS))

lines = []
add = lines.append

add("schema: phocinae-rulepack/v1")
add("id: eu-label")
add("title: Food label compliance check (FSAI guidance on Regulation (EU) No. 1169/2011)")
add("version: 0.1.1")
add("scenario: XC7")
add("description: |")
add("  Read a label data table, one row per SKU, against the FSAI's published guidance")
add("  on Regulation (EU) No. 1169/2011, and emit only the differences for a human to")
add("  review. It reaches no compliance conclusion and makes no model calls.")
add("")
add("  Every citation is evidence_level: derived. The FSAI advises on the Regulation;")
add("  these are the authority's restatement, not the instrument's own text, and the")
add("  validator warns accordingly. Nothing here is quoted from the Regulation itself.")
add("")
add("  Scope note: this pack does not carry the date-mark rules (wording, numeric form,")
add("  use-by storage conditions) or the net-quantity unit rule. Their bases -- the FSAI")
add("  shelf-life page and Annex IX -- were not obtained for this release, and a rule")
add("  whose source cannot be resolved is not a gate. See GAPS.md.")
add("missing_field_policy: review")
add("input_schema:")
add("  type: object")
add("  required: [sku, fields, allergens_declared, allergens_emphasised, x_height_mm, "
    "package_area_cm2, vision]")
add("  properties:")
add("    sku: {type: string}")
add("    fields:")
add("      type: object")
add("      properties:")
for field in MANDATORY_FIELDS:
    add("        %s: {type: boolean}" % field)
add("    alcohol_by_volume_pct: {type: number}")
add("    allergens_declared: {type: array, items: {type: string}}")
add("    allergens_emphasised: {type: boolean}")
add("    net_quantity: {type: object, properties: {value: {type: number}, unit: {type: string}}}")
add("    x_height_mm: {type: number}")
add("    package_area_cm2: {type: number}")
add("    vision:")
add("      type: object")
add("      properties:")
add("        name: {type: string}")
add("        net_quantity: {type: string}")
add("        alcohol_strength: {type: string}")
add("enum_domains:")
add("  net_quantity.unit: [g, kg, ml, cl, l]")
add("corpus:")
for path, role, title, url in CORPUS:
    name = os.path.basename(path)
    add("  - path: %s" % path)
    add("    role: %s" % role)
    add("    title: %s" % title)
    add("    sha256: %s" % sha(bodies[name]))
    add("    url: %s" % url)
    add("    retrieved: \"2026-10-14\"")
add("citations:")
for cid, filename, source, locator, quote in CITATIONS:
    add("  - id: %s" % cid)
    add("    source: %s" % source)
    add("    locator: %s" % locator)
    add("    quote: \"%s\"" % quote.replace('"', '\\"'))
    add("    document: sources/%s" % filename)
    add("    evidence_level: derived")

add("rules:")
add("  # ---- legibility: the x-height thresholds ------------------------------")
add("  - id: r1_font_too_small_large_pack")
add("    when:")
add("      all_of:")
add("        - {field: package_area_cm2, op: \">=\", value: 80}")
add("        - {field: x_height_mm, op: \"<\", value: 1.2}")
add("    then: {verdict: fail, reason_code: XHEIGHT_BELOW_1_2MM, cite: [c_font_12]}")
add("    require_fields: [x_height_mm, package_area_cm2]")
add("  - id: r2_font_too_small_small_pack")
add("    when:")
add("      all_of:")
add("        - {field: package_area_cm2, op: \"<\", value: 80}")
add("        - {field: x_height_mm, op: \"<\", value: 0.9}")
add("    then: {verdict: fail, reason_code: XHEIGHT_BELOW_0_9MM_SMALL_PACK, cite: [c_font_09]}")
add("    require_fields: [x_height_mm, package_area_cm2]")
add("    note: |")
add("      The FSAI's FAQ page states this figure as \"0.9 cm\" while its General")
add("      Labelling page states \"0.9 mm\". Annex IV to the Regulation says 0.9 mm, so")
add("      0.9 mm is used; the discrepancy is recorded in the corpus file rather than")
add("      smoothed over.")
add("  # ---- mandatory particulars -------------------------------------------")
add("  - id: r3_missing_mandatory_particular")
add("    when:")
add("      any_of:")
for field in MANDATORY_FIELDS:
    add("        - {field: fields.%s, op: \"!=\", value: true}" % field)
add("    then: {verdict: fail, reason_code: MANDATORY_PARTICULAR_MISSING, cite: [c_mand_a_l]}")
add("    require_fields: [fields.name, fields.ingredients_list, fields.net_quantity, "
    "fields.date_mark, fields.nutrition_declaration]")
add("    note: |")
add("      Only five of the ten bits are required to be present before this rule is")
add("      evaluated. The other five are checked when recorded, but their absence means")
add("      the table does not say either way -- which is a MISSING_FIELD review, not a")
add("      finding of non-compliance.")
add("  - id: r4_allergens_not_emphasised")
add("    when: {field: allergens_emphasised, op: \"==\", value: false}")
add("    then: {verdict: fail, reason_code: ALLERGENS_NOT_EMPHASISED, cite: [c_allergen_emphasis]}")
add("    require_fields: [allergens_emphasised]")
add("  - id: r5_allergen_key_outside_annex_ii")
add("    when:")
add("      not:")
add("        field: allergens_declared")
add("        op: subset_of")
add("        value: [%s]" % ", ".join(ALLERGEN_VOCAB))
add("    then: {verdict: review, reason_code: ALLERGEN_KEY_NOT_MAPPABLE, cite: [c_allergens_14]}")
add("    require_fields: [allergens_declared]")
add("    note: |")
add("      A declared key outside this vocabulary is not a breach: it may be voluntary")
add("      information, a spelling variant, or a language difference. It escalates to a")
add("      human rather than failing.")
add("")
add("      `subset_of` means every declared key appears in the list. `in` / `not_in`")
add("      cannot express this because they take a scalar on the left: passing the array")
add("      itself is a TYPE_ERROR, so the rule would never fire while looking cautious.")
add("      An empty declaration is a subset of everything, so \"no allergens declared\" is")
add("      not reported as an unmappable key.")
add("  - id: r6_alcohol_strength_required")
add("    when:")
add("      all_of:")
add("        - {field: alcohol_by_volume_pct, op: \">\", value: 1.2}")
add("        - {field: fields.alcohol_strength, op: \"!=\", value: true}")
add("    then: {verdict: fail, reason_code: ALCOHOL_STRENGTH_NOT_DECLARED, cite: [c_mand_a_l]}")
add("    require_fields: [alcohol_by_volume_pct, fields.alcohol_strength]")
add("  - id: r7_same_field_of_vision")
add("    when:")
add("      any_of:")
add("        - {field: vision.name, op: \"!=\", value: {ref: vision.net_quantity}}")
add("        - {field: vision.name, op: \"!=\", value: {ref: vision.alcohol_strength}}")
add("    then: {verdict: fail, reason_code: NOT_SAME_FIELD_OF_VISION, cite: [c_field_of_vision]}")
add("    require_fields: [vision.name, vision.net_quantity, vision.alcohol_strength]")
add("    note: |")
add("      The three values are field-of-vision group identifiers: equal means the same")
add("      view. The footnote in the cited text exempts the date mark from this rule")
add("      under the current rules, so the date mark is deliberately not compared here.")
add("  # ---- the pass rule ---------------------------------------------------")
add("  - id: r8_label_within_guidance")
add("    when:")
add("      all_of:")
add("        - {field: x_height_mm, op: \"exists\"}")
add("        - {field: package_area_cm2, op: \"exists\"}")
add("        - {field: allergens_emphasised, op: \"==\", value: true}")
add("        - {field: sku, op: \"exists\"}")
add("    then: {verdict: pass, reason_code: NO_GUIDANCE_DEPARTURE, cite: [c_mand_a_l, c_font_12]}")
add("    require_fields: [x_height_mm, package_area_cm2, allergens_emphasised, sku]")
add("    note: |")
add("      Written out explicitly rather than left to aggregation, so that a later change")
add("      to the aggregation rule cannot silently turn \"nothing matched\" into a pass.")
add("notes:")
add("  - >-")
add("    This pack reports differences from published guidance. It is not a legal")
add("    opinion and does not certify a label.")
add("  - >-")
add("    Every rule cites at least one entry in citations, and every citation resolves")
add("    character-for-character against a file in corpus.")
add("  - >-")
add("    Scope is deliberately narrower than the design draft: see GAPS.md for the")
add("    rules that were left out and what would close each one.")

with open(os.path.join(PACK, "rulepack.yaml"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines) + "\n")
print("wrote rulepack.yaml (%d lines)" % len(lines))

with open(os.path.join(PACK, "GAPS.md"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("""# Known gaps in `eu-label` 0.1.0

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
""")
print("wrote GAPS.md")
