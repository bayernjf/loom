# Master Data Backfill · Business Operator Guide (plain guide, no technical details)

> **Purpose**: Before private beta acceptance, business / ops fill the "four certifiable items" in the **real deployment database** so the platform can produce the first real `final_id`.
> **Scope**: This is the **plain business version** extracted from `docs/19_private_beta主数据录入模板.md` — it removes endpoints / JSON / field-level technical details and keeps only: what you do, in what order, and which fields to fill.
> **Technical readers**: Field meanings, endpoints, and payload validation are in docs/19 (§1–§5). This document does not require you to understand APIs or code.
> **Red line**: Every `【business to fill】` must be supplied with real values by the business side; engineering will not fill them. Leaving a field empty is better than guessing — the self-check script tells you what is missing.

---

## 1. Remember: this needs two people

- **Data entry person (you)**: provide and write the "four items".
- **Chain-run / adjudication person** (eng / ops): runs the content-production chain end to end and adjudicates at the Gate, producing the freeze and compliance report.
- Without someone running the chain, the first `final_id` cannot be produced; and data fabricated by engineering **does not count** (violates the no-fabrication rule).
- After you finish "data entry + self-check", hand the product info to the chain-run person.

---

## 2. Before you start

1. A running environment (staging / real deployment) connected to a **real database**.
2. Database connection string (provided by engineers): `LOOM_DATABASE_DSN`.
3. An `operations` access token — **only needed for the final issuance step** (prepared by the chain-run person).
4. A **platform code** you define yourself (uppercase short code, e.g. `EXAMPLE`), used consistently across the system. The original platform catalog is lost; you define the type names.

---

## 3. Steps

### Step 0 · Set platform code + pick the first product
- Set a platform code (e.g. `EXAMPLE`); use it for every "platform" field below.
- Pick a **real product** as the vehicle for the first `final_id`.

### Step 1 · Create the product space
- Register the product per the ops SOP (docs/21 stage 1); you get a **product space id**. All later materials hang off it.

### Step 2 · Fill the "four items" in one go using the template
- Engineers give you `seed_master_data_template.py`. It ships with placeholders; replace each with a real business value (fields in Section 4):
  - **Publish slot**: at least platform / code / name / type; scores, risk, source URL etc. **may be left empty**.
  - **PCP platform config**: platform + template code (one of four); leave weights empty for defaults.
  - **Three packages (strategy / structure / expression)**: one each.
- Run a "preview" first to see what will be written, **without actually writing**; only write for real once confirmed.
- ⚠️ If placeholders are unfinished, the script **refuses to run**, preventing "to-be-filled" values from being written to the DB.

### Step 3 · Self-check "are we ready to issue"
- After entry, run `check_master_data.py`:
  - Shows **ready** = all four items present; you can proceed to the chain run.
  - Shows **what is missing** (e.g. "missing PCP", "packages incomplete") = fill the gap and re-run.
  - The script **separately flags** whether the "sensitive-domain dictionary" is empty — for the first batch, **deliberately avoid** industries you intend to manage as sensitive categories, or you'll get stuck waiting on legal review (see Section 5 ⚠️).

### Step 4 · Hand off to the chain-run person (critical, don't skip)
- Give them **product space id / platform / slot code / goal**; they run the content-production chain and adjudicate at the Gate.

### Step 5 · Issuance (chain-run person)
- They call the issuance API with a token; success produces `final_id`. If rejected, the system reports which guard failed; fill the gap and re-run (no silent failure).

---

## 4. Fields you need to fill

> Fill with real business judgment (the script and full template explain each key). **Do not fabricate** — empty is better than wrong.

### Table 1 · Publish slot (at least 4 required, rest optional)
| Field | Required | Note | Fill |
|---|---|---|---|
| platform | required | matches Step 0 | `【business to fill】` |
| code | required | unique | `【business to fill】` |
| name | required | display name | `【business to fill】` |
| slot_type | required | your type code | `【business to fill】` |
| max chars / min·max duration | optional | not gating | leave empty |
| four-dim scores (traffic/safe/conv/load) | optional | human score, **not gating** | leave empty |
| risk / source_url / gate | optional | not gating | leave empty |

### Table 2 · PCP platform config (one per product×platform)
| Field | Required | Note | Fill |
|---|---|---|---|
| platform | required | same as Step 0 | `【business to fill】` |
| template_code | required | one of four: short_video / community / photo_text / ecommerce | `【business to fill】` |
| weights | leave empty | use template default | skip |

### Table 3 · Three packages (one each, active)
| Package | Required keys |
|---|---|
| Strategy CSP | goal / stage / angle / intensity / cta / emotion |
| Structure CSTP | struct |
| Expression CEP | tone / perspective / explicit / soften |

---

## 5. ⚠️ Two common pitfalls

1. **Don't wait on these**: four-dim scores, risk, source URL, durations, gate, fit-weight matrix, slot_type_defaults — **none of them gate issuance**. Don't solicit scoring from business for the first batch; listing those in the first-batch scope is the most common **false blocker** that keeps master data from arriving.
2. **Avoid sensitive-category industries**: there is a "sensitive-domain dictionary", currently empty ⇒ first batch passes by default. But once compliance enables a sensitive category, a matched product becomes a 48h legal-review todo. For the first batch, **deliberately avoid** industries you intend to enable as sensitive.

---

## 6. Completion criteria

A `final_id` exists in the system whose materials and audit trail point to **real business data** (not test, not engineering-fabricated) ⇒ first batch complete.

---

## 7. Audit traceability reminder

Write a **real, identifiable operator** on every write (e.g. "ops-Alice"), don't share one account name across people — later reconciliation depends on it.

---

> This document and `docs/19_private_beta主数据录入模板.md` share one source: 19 is the full technical version (endpoints / JSON / payload validation), this is the plain business version (steps + field tables). On conflict, 19 wins; for the authoritative "what's enough to issue" decision, always trust the `check_master_data.py` self-check result.
>
> **中文版 (Chinese version)**: `docs/19_业务方回填指引.md`
