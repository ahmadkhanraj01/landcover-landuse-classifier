# Land Cover / Land Use Classification of `public.records` — Options & Plan

_Date: 2026-10-02_

## Goal

Classify every record in `public.records` (using `title` + `abstract`) into:

1. **Land Cover**: taxonomy in `LandCover_Types.csv` (LUCAS-style, 3 levels: 8 L1 classes A–H, ~76 leaves)
2. **Land Use**: taxonomy in `LandUse_Types.csv` (HILUCS-style, 3 levels: 4 L1 classes U1–U4, ~33 leaves)

The two classifications are produced and stored **separately**.

## Data facts

- `public.records`: **25,130 rows**; every row has a `title` and an `abstract`.
- Key: `id` (uuid); also unique `identifier`.
- Existing junction-table pattern: `record_subject`, `record_organization`, etc.

## Nature of the task

Records are publications/datasets, not map polygons. The question per record is
*"which land cover / land use does this study cover?"*:

- **Multi-label**: a study can cover several classes (e.g. cropland + grassland).
- **Variable depth**: most abstracts support L1/L2 (e.g. `B10 Cereals`), few a leaf (e.g. `B13 Barley`).
  Assign the deepest level the text clearly supports.
- **"None" is valid**: many soil papers don't concern a specific land cover/use.

## Local hardware

| Resource | Value |
|---|---|
| GPU | NVIDIA GTX 1650 Ti, 4 GB VRAM |
| RAM | 15 GB (~7 GB free) |
| CPU | Intel i7-10750H, 12 threads |

Installed Ollama models: `qwen2.5:3b` (1.9 GB), `llama3.2:3b` (2.0 GB), `gemma3:4b` (3.3 GB),
`qwen2.5:7b` (4.7 GB, doesn't fully fit in VRAM), `gemma4:e2b` (7.2 GB, too big),
`nomic-embed-text` (274 MB, embeddings).

## Options compared

Timings are rough estimates for this machine; to be confirmed in the pilot.

| # | Option | Cost | Time for 25k (est.) | Expected accuracy | Multi-label / "none" | Evidence (why) | Data stays local | Available now | Setup effort |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Keyword rules** (term lists per class) | Free | Minutes | Low–medium: misses synonyms, fires on mentions | Yes / Yes | Matched keyword | ✅ | ✅ | Medium (building the term lists) |
| 2 | **Embedding similarity** (`nomic-embed-text`) | Free | < 1 hour | Low–medium: topic similarity, not precise | Via threshold / via threshold | ❌ | ✅ | ✅ | Low |
| 3 | **GLiNER2.5-Decide** (340M, cascade) | Free | ~1 hour | Medium; good at L1, unknown at deeper levels | Yes / Via threshold | ❌ (scores only) | ✅ | ✅ | Low–medium |
| 4 | **Ollama `qwen2.5:3b`** (cascade + JSON schema) | Free | ~1–3 days | Medium; okay at L1, shaky at deeper levels | Yes / Yes | ✅ (quality varies) | ✅ | ✅ | Medium |
| 5 | **Ollama `qwen2.5:7b`** (partly on CPU) | Free | ~1 week+ | Medium–good | Yes / Yes | ✅ | ✅ | ✅ | Medium |
| 6 | **Jev API** (TypeSafe AI) | ~$5 total ($0.042 / 1M input tokens) | Hours | Unknown: no public benchmarks | Unknown | ❌ (probabilities only) | ❌ | ⏳ Waitlist | Medium |
| 7 | **Claude API** (Batches + prompt caching) | Paid; most expensive here, measure in pilot | Hours (batch) | Highest; best at telling "study is about" from "mentions" | Yes / Yes | ✅ Quotes from the abstract | ❌ | ✅ | Low–medium |
| 8 | **Hybrid:** GLiNER / embeddings first, LLM only for unclear cases | Free (Ollama fallback) or low (Claude fallback) | Hours | Good | Yes / Yes | Partly (for fallback cases) | ✅ with an Ollama fallback | ✅ | Medium–high |

### Notes per option

- **GLiNER2.5-Decide** ([model card](https://huggingface.co/fastino/GLiNER2.5-Decide)): DeBERTa-v3-large encoder, Apache 2.0,
  supports multi-label classification and label descriptions. Its model card says it does **not** support
  hierarchical classification, and reports 60.2% exact match on its own benchmark. Labels likely share the
  input with the text, so use a **cascade** (L1 → L2 within the hit branch → L3) to keep each call small (≤ ~10 labels).
- **Ollama models**: only models ≤ ~3 GB run fully on the 4 GB GPU. Use Ollama's JSON-schema `format`
  with an enum of valid codes so the model can't invent codes. Put the taxonomy at the start of the prompt
  so the cached prefix can be reused between calls.
- **Jev** ([announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev)): API only, early access via a waitlist.
  The post doesn't say whether it supports multi-label output or custom taxonomies, or how it handles data retention.
- **Claude API**: most reliable for subtle cases and gives auditable evidence quotes. Data leaves the machine.
- **Embeddings (`nomic-embed-text`)**: weak alone, but a cheap **pre-filter** to skip irrelevant
  records and restrict which branches the slower classifier must check.

### Quick read

- **Fastest free start:** option 3 (GLiNER).
- **Best free quality:** option 8, with GLiNER first and `qwen2.5:7b` only for low-confidence records.
- **Best quality overall:** option 7 (Claude).
- **Not recommended as the main method:** options 1 and 2 on their own (too imprecise) and option 6 (not available yet, unproven).

## Pipeline (same for every option)

Only step 3 changes between options. Everything else is reused.

1. **Snapshot**: export `id, identifier, title, abstract` from `public.records` to JSONL/Parquet.
   Later steps work on this frozen copy.
2. **Lookup tables**: load both CSVs into `landcover_types` / `landuse_types`
   (`code, level, parent_code, description`).
3. **Classifier**: one of the options above. Land cover and land use are classified separately
   (optionally in one call with two separate output fields, to halve run time).
   Rules: deepest supported level, multi-label allowed, empty result when nothing fits.
4. **Evaluate on a gold set**: hand-label ~150–200 records (mix of clear, ambiguous and "none" cases).
   Measure precision / recall / F1 at L1 and L2 per option.
5. **Full run** with the chosen option. Keep the raw outputs on disk.
6. **Store results** in new tables; `public.records` is not modified:

   ```sql
   record_landcover(record_id uuid REFERENCES records(id) ON DELETE CASCADE,
                    code text, level int, confidence real, evidence text,
                    model text, run_id text, classified_at timestamptz)
   record_landuse  (same columns)
   ```

7. **Review & maintain**: spot-check low-confidence labels and the label distribution.
   For new harvests, classify only records with no result yet, or whose `updated_at` is later than `classified_at`.

## Decision criteria

- If **GLiNER** reaches **≥ ~0.8 F1 at L1**: use it for everything; send low-confidence records to an LLM or a person.
- If not: compare `qwen2.5:7b` (free, slow) vs Claude (paid, fast) on the same gold set.

## Next steps

1. Create the snapshot and lookup tables.
2. Hand-label the gold set (~150 records).
3. Run a 50-record pilot: GLiNER vs `qwen2.5:3b` (and Claude, if a paid API is acceptable).
4. Choose an option from the measured accuracy and timing; run the full set.
