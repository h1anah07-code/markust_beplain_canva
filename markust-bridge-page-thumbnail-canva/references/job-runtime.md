# One job, compact observations, resumable stages

This reference is used once for production or resume. No third shared skill is required. Keep job-specific data outside installed skills. Sources of truth: brief.json (inputs/claims/appeal map), photos/handoff.json (image results), design.json (copy/layout), runtime/ (observed IDs, raw receipts, QA). Do not load all old job files or all skill history on resume.

## Shared brief and photo handoff

Analyze each unchanged video once, retaining transcript/frame timestamps, source hash and selected identity/skin anchor. Verify current official/supplied claims once per job and store source/conditions/date. The brief also records target age/identity exclusions, sourceRole, page appealIds, permissible visual changes and destination. Optional audience/ad details can use stated assumptions. A changed product/source requires renewed evidence; prior-job product facts are not automatically current.

When both skills are invoked, pass this brief to artifact-template-markust and consume its photos/handoff.json with schemaVersion=1, briefFingerprint, sourceRole, identity, assets and qa. Each asset has path, sha256, state, appealIds, approximateViews and provenance; qa records evidence/status and promptsPath. Preserve all three four-angle deliverables. Reuse a verified pair only for its own suitable appeal. Different visualizable appeals may need supplemental pairs; ordinary skin photos cannot prove feel/absorption/barrier function. Existing valid anchor sheets are final assets, not an instruction to generate them again.

## Stage reuse

`scripts/job_state.py` is an offline ledger, not an automatic executor. Its spec file lives at job root:
`{stages:[{id,dependsOn:[],files:[],params:{}}]}` in dependency order. Paths are relative to that spec (absolute is accepted). Stage params include every semantic input that can affect the output. Build these stages only as needed:
- analysis: video files and analysis requirements;
- facts: current evidence files/product identity;
- photo-anchor / photo-APPEAL: selected frame, identity/age/sourceRole, appeal constraints and prompt version; depend on relevant analysis/facts;
- copy: claim evidence, appeal map, destination, language and copy-rule version;
- layout/crops: copy/assets plus geometry, fonts, dimensions, crop recipe and alpha;
- uploads: prepared bytes and current Canva account; record IDs only after access succeeds;
- native-apply: current-design intent and current readback; never use this local cache as proof that external state stayed unchanged;
- final-QA: current native state and preview evidence.

Use `job_state.py plan --spec "$JOB/stages.json" --state "$JOB/runtime/stages.json"`. Record an actually executed stage with `record` plus `--stage ID --outputs FILE... --qa-status passed|failed|unverified`; optionally `--usage-json FILE` for observed toolCalls/inputTokens/outputTokens. Missing measurements remain null, not zero. No fabricated account-percent-to-token conversion.

Only passed stages with matching input/dependency/output hashes are reusable. Changed age invalidates photos and downstream layouts, not the unchanged video transcription. Changed copy need not regenerate photos. Failed/unverified/missing/tampered outputs are never cache hits. Record upstream completion before downstream. One ledger per job; do not race multiple writers. Native ID mappings require fresh observation after copy/reorder/new objects; a new session needs a current transaction. Retry only unresolved operations from current state, never blindly replay accepted batches.

## Compact Canva observations

Use functions.exec orchestration so the raw nested tool response is not appended to model context. Keep result in memory, save the full receipt and request, then emit the projection. Never print entire richtexts/fills/operation arrays/base64 merely to inspect success. Initial mapping needs one compact index; later calls return only targeted/changed elements. Exact text is read on demand when truncated or ambiguous. Save every raw attempt, including failure, with a unique receipt ID.

Load `scripts/receipt_runtime.js` once through a file read; evaluate its `saveReceipt` function in functions.exec (no network/auth in the helper). After the actual Canva call:
```
const report = await saveReceipt({tools, result, request, baseline,
  jobDir: JOB, receiptId: "B-page1-attempt1", skillDir: SKILL, python: PYTHON});
text(report);
```
The bridge safely quotes and writes raw JSON privately without printing it, then calls `canva_adapter.py compact`. `request` is the actual sent arguments or arguments wrapper; `baseline` is the preceding complete state. If that state is already saved, pass `baselinePath` instead of `baseline` to reuse the local file. Keep full state in memory/store for sequential operations and persist the baseline at phase boundaries; avoid copying the same large baseline into every receipt unless needed for diagnostics. Receipt files are local evidence, not public deliverables with signed URLs.

The compact CLI can also replay saved files:
`canva_adapter.py compact --receipt RAW --request REQUEST --baseline BEFORE --out SUMMARY`.
It reports acceptance counts, failures/unknown/missing/excess results, current transaction/pages, target text match and actual geometry/asset IDs, unexpected changes/deletions and unresolved schema. It does not replace full verify or visual QA. Use canva_adapter.py summarize with one expected count per attempt for cumulative history. A successful correction does not erase an earlier failed attempt.

Tool schemas are discovered for the current capability; cached IDs/old argument shapes are not authority. Batch independent reads; serialize dependent edits by page. Reuse returned complete state instead of issuing redundant reads, unless it is incomplete or object structure changed. Do not fetch thumbnails during every small edit: inspect all completed pages, then only those affected by corrections. Every fetched thumbnail must still be shown inline.

## Phase boundaries and final output

Save a small runtime checkpoint with current phase, design ID, frozen team/title, next unresolved action and references to raw evidence. Record transaction status rather than assuming persistence; approvals apply only within their actual scope. A paused/restarted job resumes from evidence and current service state, not the entire historical transcript. Generated file hashes and passed local QA do not establish live Canva state.

Keep final QA and delivery requirements unchanged. Report compact outcomes and links; full raw histories stay local with credentials/signed upload URLs excluded from user-facing reports. Usage comparisons distinguish observed characters, tool calls and measured tokens; do not promise a percentage of account allowance saved.
