# Team destination and preservation

Read for production/revision/team setup; not discussion/calibration. [team-folders.json](team-folders.json) holds administrator-confirmed A/B/C folder IDs/links in one MARKUST Canva workspace. Access to all folders does not identify a user's team. Never distribute account IDs, credentials, personal profiles or job runtime with the skill.

## Personal selection and setup

`scripts/team_routing.py` (Python 3.10+, standard library) reads the map relative to its installed location. Personal selection lives outside the skill at `${CODEX_HOME:-~/.codex}/markust/bridge-thumbnail-canva.json`: `{schemaVersion:1,defaultTeam:"A"|"B"|"C"}`. Each computer/OS user/CODEX_HOME has its own selection; never bundle/reset it on update. This is a local skill-owned file, not a built-in Codex setting.

Use the current installed path as SKILL_DIR:
```
python3 "$SKILL_DIR/scripts/team_routing.py" resolve
python3 "$SKILL_DIR/scripts/team_routing.py" set-team --team C
```
The second command is an example only; use the user's selected team. Interpret resolve:
- `needs_team_selection`: reuse an explicit current-job choice, otherwise ask “처음 한 번만 설정할게요. 소속 팀은 A팀·B팀·C팀 중 어디인가요?” Persist with set-team and resolve again; never assume A.
- `needs_folder_registration`: retain the team; obtain its administrator-approved folder link. No root/other-team/replacement-folder fallback.
- `error`: explain the configuration/access error; never reset corrupt settings silently.
- `ready_for_canva_check`: local configuration only, not service access/move permission.

A default-team change affects new jobs only. Confirm stored selection; do not move past work or change a frozen job without explicit instruction. `--profile` is for isolated tests/explicit migration, never per-job or inside-skill personal storage. If persistence is blocked, retain the answer for this job and report cross-chat persistence incomplete.

Only for explicit administrator registration: check the supplied link via current Canva, then run `team_routing.py register-folder --team B --folder-url "$ADMIN_FOLDER_URL"`. It validates distinct URL/ID bindings, preserves other teams and updates only the shared map. A null ID/link pair means unconfigured. Redistribute the common map after a change; personal defaults stay separate. One account's access failure is not a reason to change a shared destination. Setup alone needs no product, image or production.

## Resolve, check and freeze

Resolve current account/link ID from live tool schema, using an already-confirmed account choice. Ask only if multiple viable connections remain ambiguous. Account label/name/folder access never determines team.

Before creating/copying a design, call list_folder_items for that account and exact mapped folder; inspect isError/error fields even if transport succeeds. An empty successful listing confirms read access only. On denial/disconnection, continue independent local preparation and explain missing access; do not create a design in an unconfirmed destination context.

Freeze the route with:
```
python3 "$SKILL_DIR/scripts/team_routing.py" resolve --out "$JOB_DIR/runtime/routing.json"
```
Save live link ID/preflight receipt separately. The helper rejects a conflicting existing route. Resume from the frozen route; explicit rerouting requires fresh access and a recorded route revision retaining prior evidence. Account/routing IDs do not belong in canonical design.json.

## Revision source

List selected-folder designs with item_types:["design"], following continuation tokens on the same account/folder until the exact source ID is found or exhausted. Titles are insufficient; failed listings do not prove absence.

If present, native-revision.md selects preservation: explicit comparison requests keep original/revised page pairs; in-place wording changes use a verified whole-design backup and retain page count. If absent, copy_design the entire source (omit page_numbers) and edit only that independent copy. Preserve source/folder/pages, reread new IDs and verify copied content. The untouched source can supply whole-design preservation evidence; no redundant extra backup/page pairs unless the requested deliverable requires them. File only the final copy.

## Final filing

After actual preview QA, required approval, commit and saved title/page-count/order verification:
1. Freshly list the frozen folder's designs, following pagination. If the final exact design ID is already present, skip moving it.
2. Otherwise move_item_to_folder with that final item_id, exact frozen to_folder_id and current job account. This changes location; it is not publication/copy. Never move temporary sources, assets, revision originals or references.
3. Inspect full response for errors, then freshly list and confirm exact membership. A successful move alone is insufficient. If still absent, mark unverified and inspect UI rather than repeating moves.
4. Save team, folder link/ID, final design ID, account, preflight, move attempt or already-present evidence and post-save listing in runtime/application log. Use passed/failed/unverified, retaining failures after correction.

For item_in_multiple_folders, use Canva UI only when the exact final design/destination and permission are clear, then recheck membership. Denied, missing, disconnected or ambiguous states cannot fall back to root/another team. Report the precise incomplete filing step and preserve job files. Deliver the final edit/folder links only as verified.
