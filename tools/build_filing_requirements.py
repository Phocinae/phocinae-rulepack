# -*- coding: utf-8 -*-
"""Write the `filing-requirements` pack: computed hash, every quote verified.

Source: 法释〔2015〕8号, fetched from the court website. The transcript is a
re-publication rather than the legislature's own database, so every citation is
``derived``.
"""
import hashlib
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PACK = (r"D:\Projects\phociane-project\_work\build\phocinae-rulepack"
        r"\phocinae_rulepack\packs\filing-requirements")
SOURCE = os.path.join(PACK, "sources", "fa_shi_2015_8_excerpt.md")
URL = "http://htzy.nmgfy.gov.cn/article/detail/2015/04/id/1600350.shtml"

with open(SOURCE, "r", encoding="utf-8") as handle:
    corpus = handle.read()
print("corpus: %d bytes  sha256=%s" % (len(corpus.encode("utf-8")),
                                       hashlib.sha256(corpus.encode("utf-8")).hexdigest()[:16]))

CITATIONS = [
    ("c_art1", "第一条",
     "人民法院对依法应该受理的一审民事起诉、行政起诉和刑事自诉，实行立案登记制。"),
    ("c_art4", "第四条", "民事起诉状应当记明以下事项："),
    ("c_art4_1", "第四条(一)",
     "（一）原告的姓名、性别、年龄、民族、职业、工作单位、住所、联系方式，法人或者其他组织的名称、住所和法定代表人或者主要负责人的姓名、职务、联系方式；"),
    ("c_art4_2", "第四条(二)",
     "（二）被告的姓名、性别、工作单位、住所等信息，法人或者其他组织的名称、住所等信息；"),
    ("c_art4_3", "第四条(三)", "（三）诉讼请求和所根据的事实与理由；"),
    ("c_art4_4", "第四条(四)", "（四）证据和证据来源；"),
    ("c_art4_5", "第四条(五)", "（五）有证人的，载明证人姓名和住所。"),
    ("c_art6", "第六条", "当事人提出起诉、自诉的，应当提交以下材料："),
    ("c_art6_1", "第六条(一)",
     "（一）起诉人、自诉人是自然人的，提交身份证明复印件；起诉人、自诉人是法人或者其他组织的，提交营业执照或者组织机构代码证复印件、法定代表人或者主要负责人身份证明书；法人或者其他组织不能提供组织机构代码的，应当提供组织机构被注销的情况说明；"),
    ("c_art6_2", "第六条(二)",
     "（二）委托起诉或者代为告诉的，应当提交授权委托书、代理人身份证明、代为告诉人身份证明等相关材料；"),
    ("c_art6_3", "第六条(三)",
     "（三）具体明确的足以使被告或者被告人与他人相区别的姓名或者名称、住所等信息；"),
    ("c_art6_4", "第六条(四)", "（四）起诉状原本和与被告或者被告人及其他当事人人数相符的副本；"),
    ("c_art6_5", "第六条(五)", "（五）与诉请相关的证据或者证明材料。"),
    ("c_art7", "第七条",
     "当事人提交的诉状和材料不符合要求的，人民法院应当一次性书面告知在指定期限内补正。"),
    ("c_art8", "第八条(一)",
     "(一)对民事、行政起诉，应当在收到起诉状之日起七日内决定是否立案；"),
]

print("\n=== quote verification ===")
bad = []
for cid, locator, quote in CITATIONS:
    ok = quote in corpus
    print("  %-12s %-10s %s" % (cid, locator, "OK" if ok else "NOT FOUND"))
    if not ok:
        bad.append(cid)
if bad:
    print("\nFAIL: %r" % bad)
    sys.exit(1)
print("  all %d quotes resolve" % len(CITATIONS))

sha = hashlib.sha256(corpus.encode("utf-8")).hexdigest().upper()

lines = []
add = lines.append
add("schema: phocinae-rulepack/v1")
add("id: filing-requirements")
add("title: 法院立案材料要件审查（民事一审）")
add("version: 0.1.2")
add("scenario: L10")
add("description: |")
add("  读一份立案材料清单，对一版要件表，输出缺项与不符项供人复核。")
add("  不作法律结论、不判断是否应当受理与不予受理。")
add("  依据：法释〔2015〕8 号，逐字语料见 sources/fa_shi_2015_8_excerpt.md。")
add("")
add("  证据等级全部为 derived：语料取自法院官网转载版本，属权威转录，")
add("  不是全国人大法规库原件。validate 会逐条提示这一点。")
add("")
add("  核心口径：要件缺失 → review。依据第七条「应当一次性书面告知在指定期限内补正」")
add("  ——缺项对应的动作是告知补正，不是不予受理，所以本 pack 不判 fail。")
add("  份数不足 → fail：第六条(四)要求副本人数相符，这是记录值本身不符合。")
add("missing_field_policy: review")
add("input_schema:")
add("  type: object")
add("  required: [case, complaint]")
add("  properties:")
add("    case:")
add("      type: object")
add("      properties:")
add("        type: {type: string}")
add("        court: {type: string}")
add("    complaint:")
add("      type: object")
add("      properties:")
add("        present: {type: boolean}")
add("        plaintiff_identity_complete: {type: boolean}")
add("        defendant_identity_complete: {type: boolean}")
add("        claims_and_facts: {type: boolean}")
add("        evidence_and_sources: {type: boolean}")
add("        witness_details_required: {type: boolean}")
add("        witness_details_present: {type: boolean}")
add("        copies_submitted: {type: number}")
add("        defendants_count: {type: number}")
add("        attachments:")
add("          type: object")
add("          properties:")
add("            identity_proof: {type: boolean}")
add("            authority_of_agent: {type: boolean}")
add("            service_address_for_defendant: {type: boolean}")
add("            evidence_materials: {type: boolean}")
add("enum_domains:")
add("  case.type: [civil_first_instance, administrative_first_instance, "
    "criminal_self_prosecution, other]")
add("corpus:")
add("  - path: sources/fa_shi_2015_8_excerpt.md")
add("    role: authority")
add("    title: 最高人民法院关于人民法院登记立案若干问题的规定（节选）")
add("    sha256: %s" % sha)
add("    url: %s" % URL)
add("    retrieved: \"2026-10-14\"")
add("citations:")
for cid, locator, quote in CITATIONS:
    add("  - id: %s" % cid)
    add("    source: 法释〔2015〕8号（最高人民法院关于人民法院登记立案若干问题的规定）")
    add("    locator: %s" % locator)
    add("    quote: \"%s\"" % quote)
    add("    document: sources/fa_shi_2015_8_excerpt.md")
    add("    evidence_level: derived")
add("rules:")
add("  # ---- out of scope -----------------------------------------------------")
add("  - id: r1_out_of_scope_case_type")
add("    when:")
add("      not:")
add("        field: case.type")
add("        op: in")
add("        value: [civil_first_instance, administrative_first_instance, "
    "criminal_self_prosecution]")
add("    then: {verdict: review, reason_code: OUT_OF_SCOPE_CASE_TYPE, cite: [c_art1]}")
add("    require_fields: [case.type]")
add("    note: 本 pack 覆盖第一条列明的三类一审；其余案件类型转人工。")
add("  # ---- missing items escalate, they do not fail --------------------------")
add("  - id: r2_complaint_absent")
add("    when: {field: complaint.present, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art6]}")
add("    require_fields: [complaint.present]")
add("  - id: r3_plaintiff_identity_incomplete")
add("    when: {field: complaint.plaintiff_identity_complete, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art4_1]}")
add("    require_fields: [complaint.plaintiff_identity_complete]")
add("  - id: r4_defendant_identity_incomplete")
add("    when: {field: complaint.defendant_identity_complete, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art4_2]}")
add("    require_fields: [complaint.defendant_identity_complete]")
add("  - id: r5_claims_and_facts_absent")
add("    when: {field: complaint.claims_and_facts, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art4_3]}")
add("    require_fields: [complaint.claims_and_facts]")
add("  - id: r6_evidence_sources_absent")
add("    when: {field: complaint.evidence_and_sources, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art4_4]}")
add("    require_fields: [complaint.evidence_and_sources]")
add("  - id: r7_witness_named_but_details_absent")
add("    when:")
add("      all_of:")
add("        - {field: complaint.witness_details_required, op: \"==\", value: true}")
add("        - {field: complaint.witness_details_present, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art4_5]}")
add("    require_fields: [complaint.witness_details_required, complaint.witness_details_present]")
add("  - id: r8_identity_proof_absent")
add("    when: {field: complaint.attachments.identity_proof, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art6_1]}")
add("    require_fields: [complaint.attachments.identity_proof]")
add("  - id: r9_authority_of_agent_absent")
add("    when: {field: complaint.attachments.authority_of_agent, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art6_2]}")
add("    require_fields: [complaint.attachments.authority_of_agent]")
add("    note: 该项只在委托起诉或代为告诉时才是要件；未委托时把本字段记为 true。")
add("  - id: r10_defendant_address_absent")
add("    when: {field: complaint.attachments.service_address_for_defendant, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art6_3]}")
add("    require_fields: [complaint.attachments.service_address_for_defendant]")
add("  - id: r11_evidence_materials_absent")
add("    when: {field: complaint.attachments.evidence_materials, op: \"!=\", value: true}")
add("    then: {verdict: review, reason_code: MISSING_REQUIRED_ITEM, cite: [c_art6_5]}")
add("    require_fields: [complaint.attachments.evidence_materials]")
add("  # ---- the one deterministic failure: copies must match the party count --")
add("  - id: r12_copies_fewer_than_defendants")
add("    when: {field: complaint.copies_submitted, op: \"<\", value: {ref: complaint.defendants_count}}")
add("    then: {verdict: fail, reason_code: COPIES_FEWER_THAN_DEFENDANTS, cite: [c_art6_4]}")
add("    require_fields: [complaint.copies_submitted, complaint.defendants_count]")
add("    note: |")
add("      第六条(四)要求「起诉状原本和与被告或者被告人及其他当事人人数相符的副本」。")
add("      份数不足是记录值本身不符合要求，不是「没记录」，所以判 fail 而不是 review。")
add("      本 pack 只有这一条规则用字段间比较 {\"ref\": ...}。")
add("  # ---- the pass rule ----------------------------------------------------")
add("  - id: r13_requirements_present")
add("    when:")
add("      all_of:")
add("        - {field: complaint.present, op: \"==\", value: true}")
add("        - {field: complaint.plaintiff_identity_complete, op: \"==\", value: true}")
add("        - {field: complaint.defendant_identity_complete, op: \"==\", value: true}")
add("        - {field: complaint.claims_and_facts, op: \"==\", value: true}")
add("        - {field: complaint.evidence_and_sources, op: \"==\", value: true}")
add("        - {field: complaint.attachments.identity_proof, op: \"==\", value: true}")
add("        - {field: complaint.attachments.evidence_materials, op: \"==\", value: true}")
add("    then: {verdict: pass, reason_code: NO_REQUIREMENT_GAP, cite: [c_art6, c_art7]}")
add("    require_fields: [complaint.present, complaint.plaintiff_identity_complete, "
    "complaint.defendant_identity_complete, complaint.claims_and_facts, "
    "complaint.evidence_and_sources, complaint.attachments.identity_proof, "
    "complaint.attachments.evidence_materials]")
add("    note: |")
add("      逐条写出「要件齐备」而不是依赖聚合，以免日后聚合语义变化时静默放行。")
add("      只在要件层面判定；本 pack 不对是否应当受理发表意见。")
add("notes:")
add("  - >-")
add("    本 pack 只输出差异供人复核，不是法律意见，不判断是否应当受理、")
add("    不予受理或不予立案。")
add("  - >-")
add("    「要件缺失判 review」是刻意的：第七条的补正告知才是缺项对应的动作。")
add("    只有份数不足这种记录值本身不合规的情形才判 fail。")

os.makedirs(PACK, exist_ok=True)
with open(os.path.join(PACK, "rulepack.yaml"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines) + "\n")
print("\nwrote rulepack.yaml (%d lines)" % len(lines))
