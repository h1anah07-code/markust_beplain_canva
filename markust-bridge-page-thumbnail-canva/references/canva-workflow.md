# New-set native Canva workflow

For new sets or authorized layout changes. Wording replacements/additions use native-revision.md instead. No live Canva session is needed to test the local scripts.

## Brief and preparation

1. Resolve current account, team access and frozen date/title once (team-routing.md). Read job-runtime.md for brief/handoff, reuse and receipt handling. Discover only needed Canva capabilities; do not print the full tool catalog or script sources.
2. Establish appeal-specific photos and verified copy before geometry. Read the technical sections of design-json.md needed to populate assets/design-template.json; select assets/focused-benefit-template.json only for structure 05. Templates are deliberately incomplete and historical geometry is a starting point. Keep source JSON intent separate from runtime IDs.
3. Use Python 3.10+ with Pillow; locate the bundled workspace runtime if required. Resolve current local fonts. Run `render.py --design "$JOB/design.json" --output "$JOB/preview" --validate-only`, then render without that flag. Inspect all requested local pages against approved-quality.md, including meaningful support, natural crop and readable type. The renderer does not shrink or rewrite text; fix copy/boxes deliberately.

## Native construction route

Prefer an accessible, compatible native scaffold that has the required page structure/editable elements and can reproduce the approved composition. Copy it independently, preserve its source, replace current-job copy/photos and inspect inherited fonts/layers. Do not search indefinitely for a template or copy unrelated styling to save work. Observe all IDs in the new copy.

If no compatible scaffold is verified, convert each local page using current image-to-design capability. Correct its reconstructed objects; do not deliver its raw first approximation or a whole-page bitmap. Replace image placeholders with original prepared crops and logo. Combine pages with native page-grid copy/paste, not screenshot paste. Check count/order/content after merge; if merge returns unchanged content, use the native route instead of identical retries. No PPTX intermediary. Reread IDs after every copy/merge/reorder; all four pages must be in one final design. Keep temporary source designs unless deletion is authorized.

## Assets and editing

- Read the current upload schema. Use local asset_file only if supported; otherwise use a fresh create_upload_url and one raw-byte POST with Content-Type application/octet-stream, not multipart. Never probe/reuse a failed single-use URL. `upload_assets.py` handles private queues and records failures; no invented URL host or local path in URL-only fields.
- Use render-manifest.json's actual absolute paths for elementImages/graphics/backgrounds. Upload deduplication is allowed only for byte-identical prepared assets, same current account and verified accessible IDs. Changed crop/size/alpha produces a new asset. Original source photos/logo stay untouched.
- Exact prepared viewport crops avoid unsupported arbitrary API cropping. Resize the viewport before update_fill. Logo contain padding preserves RGBA alpha and proportions; no white badge. Exported graphic alpha already includes opacity, so native opacity is 1; unreturned inherited opacity needs visual/UI checking.
- Save raw current readback, explicit JSON→native page/element mapping and upload manifest. Ambiguous/missing/stale/cross-page IDs block the affected edit, not a reason to guess. Missing native text or unsupported font/layer controls use Canva UI, followed by readback. Verify actual insertion page.
- Compile via canva_adapter.py using current readback/mappings/uploads and explicit font scale (observed starting value 1, not a universal conversion). Send only readyToSend requests. Supported text sequence is replace → format → width-only resize → position; Canva computes text height. Do not force local height or assume local font means native font. Clear inherited list styling where appropriate.
- For a layout revision, pass the prior canonical design as --baseline and bind each retained element through originalElementId. The compiler skips semantically unchanged source elements; use --source-page for only affected pages. Fresh readback/verification still checks external state.
- Batch supported operations per page. Revisions skip proven unchanged elements; no full-reformat loop for a single changed line. Save and compact each response using job-runtime.md, check every operation result and actual affected geometry. Missing/unknown/partial results remain unresolved. Retain failed attempts and their resolution records.

CLI entrypoints (use --help for arguments, not source reads): `canva_adapter.py compile`, `verify`, `summarize`, `compact`. Existing compile/verify input contracts remain in design-json.md. Keep native font family, letter spacing, stacking and opacity explicitly unverified when not exposed; use UI/actual visual evidence for required properties.

## QA and save

Check all final actual Canva pages once at useful small size and native detail: current appeal/copy rules, official transparent top-left logo, 0°–45° source poses, correct state labels, focused anatomical matching, native editability, line breaks/height, explanation, alignment, natural crops, no clipping/overlap/accidental voids. A photo-first page needs useful copy above and below its inset. Numeric acceptance, returned-property verification and visual/UI verification are separate evidence types.

After correction, re-fetch/reinspect only affected pages unless a shared change affects the set. Display every fetched thumbnail inline every time. Keep successful unchanged preview evidence; never omit final page QA to reduce calls. Show the complete final set for any tool-required save approval. Commit only approved changes and record its receipt. Then verify actual frozen MM.DD title, count/order/edit link and exact membership in the frozen folder. Skip redundant moves when already present. Do not move sources/references or publish ads/sites. Failed connection/filing remains an explicit incomplete step, with prepared files preserved.
