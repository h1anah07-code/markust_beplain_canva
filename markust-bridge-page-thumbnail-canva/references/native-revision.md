# Native wording replacements and whitespace additions

Preserve current theme, fonts/sizes, existing geometry, photo crops and page sequence. No image generation, re-upload, full reconstruction or full-format pass for wording work. Read copy rules once. Resolve source and team via team-routing.md.

## Preserve first

- Explicit original/revised comparison request: duplicate pages, use the requested order (otherwise interleaved), reread IDs and protect originals with --protected-pages.
- In-place wording replacement/addition: make a whole-design backup, record source/backup metadata and complete readbacks, and verify equivalent returned content/geometry plus omitted visual properties. Retain the existing page count. If editing a copy because the source is outside the target folder, the untouched original is preservation evidence; do not make an extra backup unnecessarily.
- Capture a complete baseline BEFORE new text creation or changes. IDs in a copy may differ. Never use a matching title as source identity.

Canonical design.json uses `mode: copy-only` or `copy-add`, `title`, `preservation: paired-pages | whole-design-backup`, and pages with stable IDs. Runtime mapping is `{pages:{stablePageId:observedPageId},elements:{stableEditId:observedElementId}}`. Current IDs never go into canonical design intent.

A page's `edits` list contains `{id, find, replace}` for exact text substitutions. Omit unchanged substitutions before compilation; if nothing changed, send no edit request. Each find must occur exactly once inside one rich-text region. Multiple edits may target different regions of the same box. Do not replace whole mixed-style boxes or globally format existing text. Native reflow is expected; shorten/rephrase before considering any style change.

A page's `additions` list contains `{id, text, box:{x,y,width}, formatting:{font_size,color,font_weight,text_align,line_height,...}}`. Use current supported body formatting; font family must be inherited or set/checked through UI. Only newly created native TEXT elements may bind additions; existing elements must remain unchanged. New width/position are intentional; text height must come from actual Canva reflow.

## Create missing text only

Prefer a purpose-built add-text tool if available. Otherwise select the intended page in Canva UI, inspect its visible canvas, click a real blank area inside that page, then add/paste the text. A page-list/AX click may scroll without changing insertion ownership. Immediately reread and verify the new element's page ID and index; wrong-page/off-canvas insertion must be corrected before compilation. Never infer IDs from creation order. Save all additions in one fresh readback when the UI batch is complete.

## Compile and verify

```
python3 "$SKILL/scripts/copy_only.py" compile --design "$JOB/design.json" --readback "$JOB/runtime/current.json" --mapping "$JOB/runtime/mapping.json" --link-id "$LINK" --transaction-id "$TX" --out "$JOB/runtime/copy-plan.json" [preservation arguments]
```

- Paired pages: `--protected-pages` followed by actual original indices.
- Whole-design: `--backup-evidence FILE`. Its object contains sourceDesign and backupDesign (observed get_design/copy metadata with id/page_count), sourceReadback and backupReadback (complete native snapshots). IDs must differ; source content must match the pre-edit baseline and backup returned content must match, ignoring only generated IDs/roundoff. This does not verify omitted fonts/layers.
- Additions also require `--baseline-readback FILE` from before UI creation. New IDs must match exactly the declared additions; pages/photos/original text/graphics cannot change.
- If current readback omits transaction metadata, `--transaction-readback FILE` uses that same transaction's start receipt. Do not invent/reuse stale IDs.

Send only readyToSend requests, compact receipts using job-runtime.md, then:
```
python3 "$SKILL/scripts/copy_only.py" verify --plan "$JOB/runtime/copy-plan.json" --readback "$JOB/runtime/final.json" --out "$JOB/runtime/copy-verification.json"
```

The verifier checks expected text/position, added widths/page bounds, all untouched records, graphics and page structure. Empty shape records in richtexts are preserved, never treated as text targets. Unknown schema, wrong page, ambiguous matches or altered originals block completion. Formatting acceptance is not proof of appearance; inspect actual font inheritance, wrapping, new-text readability, overlap and photo preservation. Corrections use latest readback and retain the original baseline for cumulative verification.

Finish with all final-page actual preview evidence, tool-required approval, commit, metadata and folder verification as in SKILL.md. Fetch corrected pages only when unchanged previews already exist; show each fetched thumbnail inline.
