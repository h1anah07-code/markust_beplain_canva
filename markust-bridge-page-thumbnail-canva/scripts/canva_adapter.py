#!/usr/bin/env python3
"""Offline source-JSON compiler and evidence verifier for native Canva edits.

This module performs no network I/O and never starts, applies, or commits edits.
Every binding ID must come from the current connected account, a real saved
Canva readback, or an upload manifest. A ready request still needs to be sent by
the agent through the currently available Canva tool.

Examples (paths and IDs are supplied at runtime):
  canva_adapter.py compile --design JOB/design.json --readback JOB/before.json \
    --link-id OBSERVED_LINK --transaction-id OBSERVED_TRANSACTION \
    --upload-manifest JOB/uploads.json --out JOB/plan.json
  canva_adapter.py verify --design JOB/design.json --plan JOB/plan.json \
    --readback JOB/after.json --receipt JOB/apply.json --out JOB/verification.json
  canva_adapter.py summarize --receipt JOB/apply.json --expected-count 12 \
    --out JOB/receipt-summary.json

Mapping: {"pages": {"source-page-id": "observed-page-id"},
          "elements": {"source-element-id": "observed-element-id"},
          "deleteNativeElements": {"source-page-id": ["reviewed-extra-id"]}}
Uploads: {"assets": {"source-asset-or-graphic-element-id": "uploaded-asset-id"},
          "pageBackgrounds": {"source-page-id": "uploaded-solid-background-id"}}
Native metadata cached in source JSON is not used as an implicit mapping.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

VERSION = "1.0.0"
GRAPHICS = {"rectangle", "ellipse", "frame"}
LIMITATIONS = {
    "fontFamily": "The editing API used by this compiler cannot set font family; inherited family is not verified per element.",
    "letterSpacing": "The editing API used by this compiler cannot set or verify letter spacing.",
    "numericZ": "No arbitrary numeric layer reorder/readback is available. Inspect actual stacking visually.",
    "textHeight": "Text height is automatic. Only width is resized, after formatting; source height is a layout limit.",
    "crop": "Prepared assets cover the complete viewport. Internal Canva fill crop transforms still require visual inspection.",
    "graphics": "Prepared rectangles/ellipses/frames are separate editable images, not guaranteed native vector shapes.",
    "nativeOpacity": "Prepared viewport/graphic alpha already includes source opacity. Native opacity must be 1; existing fill opacity requires readback or UI verification.",
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def walk(value):
    """Read MCP text envelopes as well as ordinary JSON; never execute content."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return
        yield from walk(decoded)


def first_field(value, names):
    for obj in walk(value):
        for name in names:
            if obj.get(name) is not None:
                return obj[name]
    return None


def numeric(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def normalize_text(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", value).strip().casefold()


def plain_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces = [plain_text(v) for v in value]
        return "".join(v for v in pieces if v is not None) if any(v is not None for v in pieces) else None
    if isinstance(value, dict):
        for name in ("plain_text", "plainText", "text", "content", "runs", "paragraphs"):
            if name in value:
                found = plain_text(value[name])
                if found is not None:
                    return found
    return None


def element_text(obj):
    if isinstance(obj.get("regions"), list):
        value = plain_text(obj["regions"])
        return value.replace("\\n", "\n").replace("\\r", "\r") if value is not None else None
    for name in ("text", "text_content", "textContent", "plain_text", "plainText", "rich_text", "richText"):
        if name in obj:
            value = plain_text(obj[name])
            if value is not None:
                return value
    return None


def object_id(obj, kind):
    return next((obj[n] for n in (kind + "_id", kind + "Id", "id") if isinstance(obj.get(n), str) and obj[n]), None)


def element_box(obj):
    container = obj.get("containerElement", obj.get("container_element", {}))
    if isinstance(container, dict):
        pos = container.get("position", {})
        dim = container.get("dimension", container.get("dimensions", {}))
        if isinstance(pos, dict) and isinstance(dim, dict):
            result = {"x": numeric(pos.get("left", pos.get("x"))), "y": numeric(pos.get("top", pos.get("y"))),
                      "width": numeric(dim.get("width")), "height": numeric(dim.get("height"))}
            if all(v is not None for v in result.values()):
                return result
    for candidate in (obj, obj.get("box"), obj.get("bounds"), obj.get("geometry"), obj.get("boundingBox")):
        if isinstance(candidate, dict):
            result = {"x": numeric(candidate.get("x", candidate.get("left"))), "y": numeric(candidate.get("y", candidate.get("top"))),
                      "width": numeric(candidate.get("width")), "height": numeric(candidate.get("height"))}
            if all(v is not None for v in result.values()):
                return result
    return None


def native_kind(obj):
    if element_text(obj) is not None:
        return "text"
    name = str(obj.get("type", obj.get("element_type", obj.get("elementType", "")))).lower()
    if any(n in obj for n in ("asset_id", "assetId")) or any(n in name for n in ("image", "photo", "fill", "media")):
        return "image"
    if any(n in name for n in ("shape", "rect", "ellipse", "line", "frame")):
        return "shape"
    return "unknown"


def native_elements(obj):
    found = {}
    for name in ("elements", "text_elements", "textElements", "children", "richtexts", "fills", "media_elements", "mediaElements"):
        for item in walk(obj.get(name, [])):
            eid = object_id(item, "element")
            kind = native_kind(item)
            if eid and kind != "unknown":
                record = {"id": eid, "type": kind, "text": element_text(item), "box": element_box(item), "raw": item}
                if eid not in found or len(item) > len(found[eid]["raw"]):
                    found[eid] = record
    return list(found.values())


def parse_readback(value, source="", page_index_base=1):
    pages = {}
    transaction = first_field(value, ("transaction_id", "transactionId"))
    link = first_field(value, ("link_id", "linkId"))
    for obj in walk(value):
        for key in ("pages", "design_pages", "designPages"):
            for offset, page in enumerate(obj.get(key, []) if isinstance(obj.get(key), list) else []):
                if not isinstance(page, dict) or not object_id(page, "page"):
                    continue
                pid = object_id(page, "page")
                index = next((page[k] for k in ("page_index", "pageIndex", "page_number", "index") if k in page), offset + page_index_base)
                entry = {"id": pid, "index": index, "elements": native_elements(page), "raw": page,
                         "transactionId": transaction, "linkId": link, "readbackFile": source}
                if pid not in pages or len(entry["elements"]) > len(pages[pid]["elements"]):
                    pages[pid] = entry
        if obj.get("page_id") or obj.get("pageId"):
            elements = native_elements(obj)
            if elements:
                pid = object_id(obj, "page")
                entry = {"id": pid, "index": obj.get("page_index", obj.get("pageIndex", page_index_base)), "elements": elements,
                         "raw": obj, "transactionId": transaction, "linkId": link, "readbackFile": source}
                if pid not in pages or len(elements) > len(pages[pid]["elements"]):
                    pages[pid] = entry
    for obj in walk(value):
        if not any(isinstance(obj.get(k), list) for k in ("richtexts", "fills")):
            continue
        for page in pages.values():
            selected = {key: [e for e in obj.get(key, []) if isinstance(e, dict) and e.get("page_index", e.get("pageIndex")) == page["index"]] for key in ("richtexts", "fills")}
            merged = {e["id"]: e for e in page["elements"]}
            merged.update({e["id"]: e for e in native_elements(selected)})
            page["elements"] = list(merged.values())
    return list(pages.values())


def combine_readbacks(responses, page_index_base=1):
    """Latest nonempty state wins; reject accidentally mixing different designs."""
    pages = {}
    for name, response in responses:
        for page in parse_readback(response, name, page_index_base):
            old = pages.get(page["index"])
            if old and old["id"] != page["id"]:
                raise ValueError("Different native page IDs share an index across readbacks. Supply snapshots from one design only.")
            if old is None or page["elements"]:
                pages[page["index"]] = page
    if len({p["id"] for p in pages.values()}) != len(pages):
        raise ValueError("A native page ID occurs at multiple indices.")
    ids = [e["id"] for p in pages.values() for e in p["elements"]]
    if len(ids) != len(set(ids)):
        raise ValueError("A native element ID occurs on multiple pages.")
    return [pages[k] for k in sorted(pages)]


def signature(page):
    covered = {"pageId": page["id"], "pageIndex": page["index"], "rawPage": page["raw"],
               "elements": sorted((e["raw"] for e in page["elements"]), key=lambda e: object_id(e, "element") or "")}
    return {"pageIndex": page["index"], "nativePageId": page["id"], "elementCount": len(page["elements"]), "sha256": digest(covered),
            "coveredFields": "Strict complete raw page and editable-element fields returned by Canva; unreturned properties remain unverified."}


def kind(element):
    return "rectangle" if element.get("type") == "rect" else element.get("type")


def semantic(element):
    fields = ("text", "box", "color", "align", "fill", "opacity", "rotationDegrees", "stroke", "strokeWidthPx", "assetId", "crop")
    result = {name: element[name] for name in fields if name in element}
    result["type"] = kind(element)
    if "font" in element:
        result["font"] = {k: element["font"].get(k) for k in ("requestedFamily", "sizePx", "weight", "lineHeight", "lineHeightPx", "letterSpacingPx")}
    return result


def near_box(a, b, tolerance=1):
    return bool(a and b and all(abs(a[k] - b[k]) <= tolerance for k in ("x", "y", "width", "height")))


def match_element(source, candidates, used, explicit=None, canvas=None):
    available = [n for n in candidates if n["id"] not in used]
    if explicit:
        found = next((n for n in available if n["id"] == explicit), None)
        return found, "reviewed_explicit_mapping" if found else "explicit_id_absent_from_target_page_or_already_used"
    typ = kind(source)
    if typ == "text":
        exact = [n for n in available if n["type"] == "text" and normalize_text(n["text"]) == normalize_text(source.get("text"))]
        if len(exact) == 1:
            return exact[0], "unique_normalized_text"
        candidates = exact
    else:
        candidates = [n for n in available if n["type"] == "image" or (typ in GRAPHICS and n["type"] == "shape")]
    exact_box = [n for n in candidates if near_box(source.get("box"), n.get("box"), 0.001)]
    if len(exact_box) == 1:
        return exact_box[0], "unique_exact_geometry"
    if candidates and source.get("box") and canvas:
        def distance(n):
            if not n.get("box"):
                return math.inf
            a, b = source["box"], n["box"]
            return (abs(a["x"]-b["x"])+abs(a["width"]-b["width"]))/canvas["width"] + (abs(a["y"]-b["y"])+abs(a["height"]-b["height"]))/canvas["height"]
        ranked = sorted(candidates, key=distance)
        first = distance(ranked[0]); second = distance(ranked[1]) if len(ranked) > 1 else math.inf
        if first <= 0.06 and second - first >= 0.025:
            return ranked[0], "unique_near_geometry_and_exact_text" if typ == "text" else "unique_near_geometry"
    return None, "missing_or_ambiguous_native_match"


def asset_id(manifest, key):
    value = manifest.get("assets", manifest).get(key) if key else None
    if isinstance(value, dict):
        value = value.get("canvaAssetId", value.get("asset_id"))
    return value if isinstance(value, str) and value.strip() else None


def validate_design(design):
    if not isinstance(design.get("pages"), list) or not design["pages"]:
        raise ValueError("Source design must contain pages.")
    canvas = design.get("canvas", {})
    if not all(numeric(canvas.get(k)) and canvas[k] > 0 for k in ("width", "height")):
        raise ValueError("Canvas requires positive width/height.")
    page_ids = [p.get("id") for p in design["pages"]]
    elements = [e for p in design["pages"] for e in p.get("elements", [])]
    element_ids = [e.get("id") for e in elements]
    if any(not isinstance(v, str) or not v for v in page_ids + element_ids) or len(set(page_ids)) != len(page_ids) or len(set(element_ids)) != len(element_ids):
        raise ValueError("Every source page/element needs a unique nonempty stable ID.")
    for e in elements:
        b = e.get("box", {})
        if kind(e) not in {"text", "image"} | GRAPHICS or any(numeric(b.get(k)) is None for k in ("x", "y", "width", "height")) or b["width"] <= 0 or b["height"] <= 0:
            raise ValueError("Unsupported element type or invalid box: " + e["id"])
        if kind(e) == "text" and (not isinstance(e.get("text"), str) or not isinstance(e.get("font"), dict)):
            raise ValueError("Text requires resolved copy and font: " + e["id"])
    if canvas.get("pages") is not None and canvas["pages"] != len(design["pages"]):
        raise ValueError("canvas.pages does not match source page count.")


def compile_plan(design, native_pages, mapping=None, upload_manifest=None, *, baseline=None,
                 protected_pages=(), link_id=None, transaction_id=None, insert_elements=(), source_pages=None, font_scale=1, line_height_unit="ratio"):
    validate_design(design)
    if numeric(font_scale) is None or font_scale <= 0 or line_height_unit not in ("ratio", "omit"):
        raise ValueError("font_scale must be positive; line_height_unit must be ratio or omit.")
    mapping, uploads = mapping or {}, upload_manifest or {}
    protected = set(protected_pages); insertions = set(insert_elements)
    source_filter = set(source_pages) if source_pages else None
    if len({p["index"] for p in native_pages}) != len(native_pages) or len({p["id"] for p in native_pages}) != len(native_pages):
        raise ValueError("Native pages must have unique observed IDs and indices.")
    observed_ids = [e["id"] for p in native_pages for e in p["elements"]]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("Native element IDs must be unique across pages.")
    by_index = {p["index"]: p for p in native_pages}; by_page_id = {p["id"]: p for p in native_pages}
    protected_ids = {e["id"] for p in native_pages if p["index"] in protected for e in p["elements"]}
    assets = {a["id"]: a for a in design.get("assets", [])}
    originals = {e["id"]: e for p in (baseline or {}).get("pages", []) for e in p.get("elements", [])}
    baseline_pages = {p["id"]: p for p in (baseline or {}).get("pages", [])}
    plan = {"adapterVersion": VERSION, "status": "compiled_not_applied", "requests": [], "mappings": [], "issues": [],
            "limitations": LIMITATIONS, "protectedPageIndices": sorted(protected), "protectedSignatures": [],
            "protectedSourceSignatures": [], "backgroundMappings": [], "scopeCheck": {"protectedElementIdsTargeted": []},
            "provenance": {"externalCallsMade": 0, "idSource": "real readbacks/runtime bindings and upload manifests"},
            "assumptions": {"fontSizeScale": font_scale, "fontSizePolicy": "Source sizePx multiplied by runtime scale; default 1 is the observed tool convention, not a universal unit conversion.", "lineHeightInput": line_height_unit}}

    def issue(sid, code, detail, severity="blocking", **extra):
        plan["issues"].append(dict(sourceId=sid, code=code, severity=severity, detail=detail, **extra))

    for index in sorted(protected):
        if index not in by_index or not by_index[index]["elements"]:
            issue("document", "protected_page_readback_missing", "Protected pages require a complete real native readback.", pageIndex=index)
        else:
            plan["protectedSignatures"].append(signature(by_index[index]))
    if not native_pages:
        issue("document", "real_readback_required", "No requests can be bound without a real native readback.")
    source_ids = {p["id"] for p in design["pages"]}
    element_ids = {e["id"] for p in design["pages"] for e in p["elements"]}
    for requested in (source_filter or set()) - source_ids:
        issue("document", "source_page_filter_unknown", "Requested source page is absent from the source design.", requestedSourceId=requested)
    for requested in insertions - element_ids:
        issue("document", "insert_element_unknown", "Requested insertion element is absent from the source design.", requestedSourceId=requested)
    bindings = {}
    for offset, source_page in enumerate(design["pages"], 1):
        mapped = mapping.get("pages", {}).get(source_page["id"])
        native_page = by_page_id.get(mapped) if mapped else (by_index.get(offset) if len(native_pages) == len(design["pages"]) else None)
        if native_page:
            bindings.setdefault(native_page["id"], []).append(source_page["id"])
        if offset in protected and len(native_pages) == len(design["pages"]):
            plan["protectedSourceSignatures"].append({"sourcePageId": source_page["id"], "sha256": digest(source_page)})
            if baseline and source_page["id"] in baseline_pages and source_page != baseline_pages[source_page["id"]]:
                issue("document", "protected_source_page_changed", "Protected source page differs from the supplied baseline; no editing request is ready.", sourcePageId=source_page["id"])
    duplicate_page_sources = {sid for ids in bindings.values() if len(ids) > 1 for sid in ids}
    for source_index, page in enumerate(design["pages"], 1):
        if source_filter and page["id"] not in source_filter:
            continue
        start = len(plan["issues"]); operations = []; used = set()
        explicit_page = mapping.get("pages", {}).get(page["id"])
        native = by_page_id.get(explicit_page) if explicit_page else (by_index.get(source_index) if len(native_pages) == len(design["pages"]) else None)
        is_protected_source = source_index in protected and len(native_pages) == len(design["pages"])
        if not native:
            issue(page["id"], "native_page_unmapped", "Supply an observed page mapping, or complete matching source/native page counts.")
            plan["requests"].append({"sourcePageId": page["id"], "nativePageId": None, "readyToSend": False, "blockedBy": [i["code"] for i in plan["issues"][start:]], "arguments": None})
            continue
        duplicate_binding = page["id"] in duplicate_page_sources
        if duplicate_binding:
            issue(page["id"], "duplicate_native_page_binding", "Multiple source pages resolve to the same native page. Resolve page correspondence before sending any affected request.")
        if not native["elements"]:
            issue(page["id"], "editable_page_readback_missing", "Page metadata alone does not prove native editable elements.")
        if native["index"] in protected and not is_protected_source:
            issue(page["id"], "protected_target_page", "An editable source page maps to a protected native page.")
        if is_protected_source and native["index"] not in protected:
            issue(page["id"], "protected_source_remapped", "A protected source page maps outside the protected native pages.")
        tid, lid = transaction_id or native.get("transactionId"), link_id or native.get("linkId")
        if not is_protected_source and transaction_id and native.get("transactionId") and transaction_id != native["transactionId"]:
            issue(page["id"], "transaction_binding_contradiction", "Runtime transaction ID disagrees with the real readback. Obtain a current readback; no request is ready.")
        if not is_protected_source and link_id and native.get("linkId") and link_id != native["linkId"]:
            issue(page["id"], "account_binding_contradiction", "Runtime account link disagrees with the real readback. Obtain a matching account readback.")
        if not is_protected_source and (not tid or not lid):
            issue(page["id"], "runtime_binding_missing", "Observed account link and active transaction IDs are required.")
        background = uploads.get("pageBackgrounds", {}).get(page["id"])
        if isinstance(background, dict):
            background = background.get("canvaAssetId", background.get("asset_id"))
        observed_background = next((n for n in native["elements"] if n["id"] == native["id"] and n["type"] == "image"), None)
        can_edit = not is_protected_source and native["index"] not in protected and not duplicate_binding
        if background and can_edit:
            if observed_background:
                operations.append({"type": "update_fill", "element_id": observed_background["id"], "asset_id": background, "asset_type": "image", "alt_text": "Source JSON solid page background"})
                plan["backgroundMappings"].append({"sourcePageId": page["id"], "nativePageId": native["id"], "nativeElementId": observed_background["id"], "expectedAssetId": background})
            else:
                issue(page["id"], "background_fill_unmapped", "A supplied background asset requires the observed native page background fill ID.")
        if can_edit and not background:
            issue(page["id"], "page_background_review", "No background replacement was compiled. Inspect reconstructed background against source; native background color is not set directly.", "review")
        for e in sorted(page["elements"], key=lambda e: e.get("z", 0)):
            original_id = e.get("originalElementId")
            old = originals.get(original_id) if original_id else None
            if original_id and old is None:
                issue(e["id"], "baseline_element_missing", "originalElementId must resolve in --baseline.")
                continue
            reference = old or e
            explicit = mapping.get("elements", {}).get(e["id"])
            if explicit in protected_ids and can_edit:
                issue(e["id"], "protected_target_element", "Explicit mapping targets a protected native element; no such operation is emitted.")
                continue
            reserved_explicit = {mapping.get("elements", {}).get(other["id"]) for other in page["elements"]}
            reserved_explicit.discard(None)
            unavailable = used | (reserved_explicit - {explicit})
            matched, method = match_element(reference, native["elements"], unavailable, explicit, design["canvas"])
            typ = kind(e)
            new_insert = e["id"] in insertions
            transition = old is not None and kind(old) == "text" and typ == "image"
            if explicit and not matched:
                issue(e["id"], "explicit_element_mapping_invalid", method)
                continue
            if not matched and not (new_insert and typ in {"image"} | GRAPHICS):
                issue(e["id"], "native_element_unmapped", method)
                continue
            if new_insert and matched and not transition:
                issue(e["id"], "insert_element_already_mapped", "Explicit insertion also matched an existing element. Resolve intent before creating a duplicate.")
                continue
            native_id = matched["id"] if matched else None
            if matched:
                used.add(native_id)
            entry = {"sourcePageId": page["id"], "sourceElementId": e["id"], "originalElementId": original_id,
                     "nativePageId": native["id"], "pageIndex": native["index"], "nativeElementIdBefore": native_id,
                     "nativeElementTypeBefore": matched["type"] if matched else None, "matchMethod": method,
                     "observedBoxBefore": matched["box"] if matched else None,
                     "observedAssetIdBefore": first_field(matched["raw"], ("asset_id", "assetId")) if matched else None,
                     "protected": is_protected_source, "sourceType": typ}
            plan["mappings"].append(entry)
            unchanged = old is not None and semantic(old) == semantic(e)
            photo = typ == "image" and assets.get(e.get("assetId"), {}).get("kind", "photo") == "photo"
            entry["photoPreservationRequired"] = bool(photo and (unchanged or is_protected_source))
            if not can_edit or unchanged:
                entry["unchangedRevision"] = unchanged
                continue
            box = e["box"]
            element_viewport = asset_id(uploads, e["id"]) if typ == "image" else None
            aid = (element_viewport or asset_id(uploads, e.get("assetId"))) if typ == "image" else asset_id(uploads, e["id"])
            if aid:
                entry["uploadManifestKey"] = e["id"] if element_viewport or typ in GRAPHICS else e.get("assetId")
                entry["preparedViewportEvidence"] = "per_element_prepared_viewport_upload" if element_viewport else "source_prepared_flag" if e.get("crop", {}).get("preparedAssetIsViewport") else "full_logo_or_graphic_asset"
                if element_viewport or typ in GRAPHICS:
                    entry["expectedNativeOpacity"] = 1
            if typ == "text":
                if matched["type"] != "text":
                    issue(e["id"], "native_text_type_mismatch", "Source text must map to a native text element.")
                    continue
                f = e["font"]
                if numeric(f.get("sizePx")) is None or f["sizePx"] <= 0 or not isinstance(e.get("color"), str):
                    issue(e["id"], "text_style_unresolved", "Text needs positive sizePx and a resolved color.")
                    continue
                formatting = {"color": e["color"], "font_size": f["sizePx"] * font_scale, "font_weight": "bold" if f.get("weight", 400) >= 600 else "normal",
                              "text_align": {"left": "start", "right": "end", "center": "center"}.get(e.get("align", "left"), "start"), "list_marker": "none", "list_level": 0}
                if line_height_unit == "ratio" and f.get("lineHeight") is not None:
                    formatting["line_height"] = f["lineHeight"]
                else:
                    issue(e["id"], "line_height_inherited", "No line-height ratio command was emitted; inspect the inherited native line spacing.", "review")
                operations.extend([{"type": "replace_text", "element_id": native_id, "text": e["text"]},
                                   {"type": "format_text", "element_id": native_id, "formatting": formatting},
                                   {"type": "resize_element", "element_id": native_id, "width": box["width"], "preserve_aspect_ratio": False},
                                   {"type": "position_element", "element_id": native_id, "left": box["x"], "top": box["y"]}])
                if f.get("weight", 400) not in (400, 700):
                    issue(e["id"], "binary_weight_approximation", "Only normal/bold is supported; requested numeric weight is approximated.", "review")
            else:
                fill_fields = ("fill", "opacity", "stroke", "strokeWidthPx", "assetId", "crop")
                fill_changed = old is None or transition or any(old.get(k) != e.get(k) for k in fill_fields)
                geometry_only = old is not None and not fill_changed and kind(old) == typ
                if not aid and not geometry_only:
                    issue(e["id"], "uploaded_asset_missing", "Supply a real uploaded asset ID for this image or source graphic.")
                    continue
                if typ == "image" and photo and not (element_viewport or e.get("crop", {}).get("preparedAssetIsViewport")):
                    issue(e["id"], "prepared_viewport_required", "Photo placement requires a prepared full-viewport crop; no arbitrary Canva crop command is available.")
                    continue
                if matched and matched["type"] != "image" and not transition and not (geometry_only and typ in GRAPHICS and matched["type"] == "shape"):
                    issue(e["id"], "native_fill_type_mismatch", "Prepared graphic/photo fill replacement needs a native image fill; native shape recoloring is not exposed.")
                    continue
                if box["height"] < 5:
                    issue(e["id"], "graphic_height_below_observed_minimum", "Native image resize required at least 5 px in the tested tool. Adjust source or inspect current tool capability.")
                    continue
                if transition or not matched:
                    if transition:
                        operations.append({"type": "delete_element", "element_id": native_id})
                        entry["deletedNativeElementIds"] = [native_id]
                    operations.append({"type": "insert_fill", "page_id": native["id"], "asset_id": aid, "asset_type": "image",
                                       "alt_text": "Source JSON prepared " + typ, "left": box["x"], "top": box["y"], "width": box["width"], "height": box["height"],
                                       "opacity": 1 if element_viewport or typ in GRAPHICS else e.get("opacity", 1), "rotation": e.get("rotationDegrees", 0)})
                    entry.update(insertion=True, insertedNativeElementId=None, expectedAssetId=aid, requiresPostInsertReadback=True)
                    issue(e["id"], "inserted_id_and_stacking_review", "Resolve the new element ID from actual readback and inspect stacking; numeric z is not applied.", "review")
                else:
                    operations.extend([{"type": "resize_element", "element_id": native_id, "width": box["width"], "height": box["height"], "preserve_aspect_ratio": False},
                                       {"type": "position_element", "element_id": native_id, "left": box["x"], "top": box["y"]}])
                    if not geometry_only:
                        operations.append({"type": "update_fill", "element_id": native_id, "asset_id": aid, "asset_type": "image", "alt_text": "Source JSON prepared " + typ})
                        entry["expectedAssetId"] = aid
                        if entry.get("expectedNativeOpacity") == 1:
                            issue(e["id"], "native_opacity_review", LIMITATIONS["nativeOpacity"], "review")
                    else:
                        entry["expectedAssetId"] = entry["observedAssetIdBefore"]
        # Deletion is opt-in, membership checked, and follows a verified solid background update.
        reserved = used | {native["id"]}
        for eid in mapping.get("deleteNativeElements", {}).get(page["id"], []):
            if not can_edit:
                issue(page["id"], "protected_deletion_blocked", "Reviewed deletion targets a protected page.")
            elif eid in protected_ids or eid in reserved or not any(n["id"] == eid for n in native["elements"]):
                issue(page["id"], "reviewed_deletion_invalid", "Deletion ID is protected, mapped/reserved, or absent from the target page.")
            elif not (background and observed_background):
                issue(page["id"], "reviewed_deletion_requires_background", "Replace the native page background with its source solid asset before removing reconstructed extra panels.")
            else:
                operations.append({"type": "delete_element", "element_id": eid})
        targeted = [o["element_id"] for o in operations if o.get("element_id") in protected_ids]
        if targeted or any(o.get("page_id") in {p["id"] for p in native_pages if p["index"] in protected} for o in operations):
            raise AssertionError("Compiler attempted to target a protected page/element.")
        blockers = [i["code"] for i in plan["issues"][start:] if i["severity"] == "blocking"]
        blockers += [i["code"] for i in plan["issues"] if i["sourceId"] == "document" and i["severity"] == "blocking"]
        plan["requests"].append({"sourcePageId": page["id"], "nativePageId": native["id"], "protected": is_protected_source,
                                 "readyToSend": bool(can_edit and operations and not blockers and tid and lid), "blockedBy": sorted(set(blockers)),
                                 "arguments": {"link_id": lid, "transaction_id": tid, "page_index": native["index"], "operations": operations,
                                               "user_intent": "Apply the source design JSON to this native editable page; preserve declared protected pages."}})
    plan["summary"] = {"requestCount": len(plan["requests"]), "readyRequestCount": sum(r["readyToSend"] for r in plan["requests"]),
                       "operationCount": sum(len(r["arguments"]["operations"]) for r in plan["requests"] if r["arguments"]),
                       "blockingIssueCount": sum(i["severity"] == "blocking" for i in plan["issues"]), "reviewIssueCount": sum(i["severity"] == "review" for i in plan["issues"]), "appliedOperationCount": 0}
    if plan["summary"]["blockingIssueCount"]:
        plan["status"] = "compiled_with_blocked_requests"
    return plan


def summarize_receipt(value, expected_count=None):
    """A successful envelope alone is never an operation-success receipt."""
    if expected_count is not None and (not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0):
        raise ValueError("Expected operation count must be a nonnegative integer.")
    groups, seen_lists = [], set()
    for obj in walk(value):
        for key in ("edit_operation_results", "editOperationResults"):
            group = obj.get(key)
            if isinstance(group, list) and id(group) not in seen_lists:
                seen_lists.add(id(group)); groups.append(group)
    records = [record for group in groups for record in group]
    top_error = any(obj.get("isError") is True for obj in walk(value))
    successes, failures, unknown = [], [], []
    for index, record in enumerate(records):
        status = str(record.get("status", "")).lower() if isinstance(record, dict) else ""
        if status in ("failure", "failed", "error") or (isinstance(record, dict) and (record.get("success") is False or record.get("isError") is True)):
            failures.append({"resultIndex": index, "record": record})
        elif status in ("success", "succeeded") or (isinstance(record, dict) and record.get("success") is True and not status):
            successes.append(index)
        else:
            unknown.append({"resultIndex": index, "record": record})
    missing = max(0, expected_count - len(records)) if expected_count is not None else None
    excess = max(0, len(records) - expected_count) if expected_count is not None else None
    confirmed = expected_count is not None and len(records) == expected_count and len(successes) == expected_count and not top_error
    return {"status": "all_attempted_operations_confirmed_success" if confirmed else "top_level_error" if top_error else "failed_or_unconfirmed_operations",
            "attemptedOperationCount": expected_count, "returnedOperationCount": len(records), "successCount": len(successes), "failureCount": len(failures),
            "unknownResultCount": len(unknown), "missingOperationResultCount": missing, "excessOperationResultCount": excess,
            "topLevelError": top_error, "allAppliedConfirmed": confirmed, "failures": failures, "unknownResults": unknown}


def summarize_attempts(receipts, expected_counts=None):
    if expected_counts is not None and len(expected_counts) != len(receipts):
        raise ValueError("Provide one expected operation count per receipt attempt, in the same order.")
    attempts = [dict(receiptFile=name, **summarize_receipt(value, expected_counts[i] if expected_counts is not None else None)) for i, (name, value) in enumerate(receipts)]
    known = expected_counts is not None
    summary = {"attemptCount": len(attempts), "attemptedOperationCount": sum(expected_counts) if known else None,
               "returnedOperationCount": sum(a["returnedOperationCount"] for a in attempts), "successCount": sum(a["successCount"] for a in attempts),
               "failureCount": sum(a["failureCount"] for a in attempts), "unknownResultCount": sum(a["unknownResultCount"] for a in attempts),
               "missingOperationResultCount": sum(a["missingOperationResultCount"] for a in attempts) if known else None,
               "topLevelErrorCount": sum(a["topLevelError"] for a in attempts),
               "allAppliedConfirmed": bool(attempts and known and all(a["allAppliedConfirmed"] for a in attempts))}
    return {"status": "all_attempted_operations_confirmed_success" if summary["allAppliedConfirmed"] else "failed_or_unconfirmed_attempts", "summary": summary, "attempts": attempts,
            "note": "Include every attempt, including failed and corrected retries. Missing expected counts leave total attempts unconfirmed."}



def apply_operation_evidence(report, receipt_summary=None):
    """Combine current-state evidence with operation history without hiding either.

    A corrected failure can leave a valid current state. Its historical failure
    remains in the receipt counts and must not be labeled all-operations-success.
    Missing receipts/counts never establish operation acceptance or commitment.
    """
    report["readbackStatus"] = report.get("readbackStatus", report["status"])
    report["readbackSummary"] = dict(report["summary"])
    failed_readback = bool(report["readbackSummary"]["fail"])
    prefix = "readback_discrepancies" if failed_readback else "readback_passed"
    if receipt_summary is None:
        report["operationAcceptanceStatus"] = "not_confirmed_no_receipts"
        report["operationSummary"] = {
            "attemptCount": 0, "attemptedOperationCount": None,
            "returnedOperationCount": None, "successCount": None,
            "failureCount": None, "unknownResultCount": None,
            "missingOperationResultCount": None, "topLevelErrorCount": None,
            "allAppliedConfirmed": False,
        }
        report["status"] = prefix + "_operation_acceptance_unconfirmed_no_receipts"
    else:
        report["operationReceipts"] = receipt_summary
        counts = receipt_summary["summary"]
        report["operationSummary"] = dict(counts)
        if counts["allAppliedConfirmed"]:
            report["operationAcceptanceStatus"] = "all_attempted_operations_confirmed_success"
            report["status"] = prefix + "_operation_receipts_confirmed"
        else:
            has_failures = bool(counts["failureCount"] or counts["topLevelErrorCount"])
            unknown = bool(counts["unknownResultCount"] or counts["missingOperationResultCount"] or counts["attemptedOperationCount"] is None)
            report["operationAcceptanceStatus"] = ("history_contains_failures_and_unconfirmed_results" if has_failures and unknown else
                                                   "history_contains_failures" if has_failures else "operation_results_unconfirmed")
            report["status"] = prefix + "_operation_history_failed_or_unconfirmed"
    report["operationEvidenceNote"] = "Current-state readback checks and operation history are separate evidence. Corrected failures remain counted; neither report proves commit/save."
    return report


def verify_plan(design, native_pages, plan, tolerance=1):
    validate_design(design)
    by_id = {p["id"]: p for p in native_pages}
    sources = {e["id"]: e for p in design["pages"] for e in p["elements"]}
    source_pages = {p["id"]: p for p in design["pages"]}
    checks, mappings = [], []
    def check(sid, field, expected, observed, status, **extra):
        checks.append(dict(sourceId=sid, field=field, expected=expected, observed=observed, status=status, **extra))
    blocked = sum(i.get("severity") == "blocking" for i in plan.get("issues", []))
    check("document", "compileBlockingIssues", 0, blocked, "pass" if blocked == 0 else "fail")
    for before_bg in plan.get("backgroundMappings", []):
        page = by_id.get(before_bg["nativePageId"])
        bg = next((n for n in page["elements"] if n["id"] == before_bg["nativeElementId"]), None) if page else None
        actual = first_field(bg["raw"], ("asset_id", "assetId")) if bg else None
        check(before_bg["sourcePageId"], "pageBackgroundAssetId", before_bg["expectedAssetId"], actual, "unverified" if actual is None else "pass" if actual == before_bg["expectedAssetId"] else "fail")
    for wanted in plan.get("protectedSourceSignatures", []):
        page = source_pages.get(wanted["sourcePageId"])
        actual = digest(page) if page else None
        check(wanted["sourcePageId"], "protectedSourceObjectSignature", wanted["sha256"], actual, "pass" if actual == wanted["sha256"] else "fail")
    for wanted in plan.get("protectedSignatures", []):
        page = by_id.get(wanted["nativePageId"])
        actual = signature(page)["sha256"] if page and page["elements"] else None
        check(wanted["nativePageId"], "protectedNativeReturnedFieldSignature", wanted["sha256"], actual, "unverified" if actual is None else "pass" if actual == wanted["sha256"] else "fail")
    for before in plan.get("mappings", []):
        sid = before["sourceElementId"]; source = sources.get(sid); page = by_id.get(before["nativePageId"])
        if not source:
            check(sid, "sourceElementPresent", True, False, "fail");continue
        for field, wanted in (("font.family", source.get("font", {}).get("requestedFamily")), ("font.letterSpacingPx", source.get("font", {}).get("letterSpacingPx", 0))):
            if kind(source) == "text":
                check(sid, field, wanted, None, "unverified", reason="Not applied/read back by this compiler's editing API.")
        check(sid, "layer.numericZ", source.get("z"), None, "unverified", reason=LIMITATIONS["numericZ"])
        if not page or not page["elements"]:
            check(sid, "nativeEditableReadback", True, None, "unverified");continue
        natives = {n["id"]: n for n in page["elements"]}
        native = natives.get(before.get("nativeElementIdBefore"))
        if before.get("insertion"):
            for eid in before.get("deletedNativeElementIds", []):
                check(sid, "replacedElementDeleted", False, eid in natives, "pass" if eid not in natives else "fail")
            candidates = [n for n in page["elements"] if n["type"] == "image" and first_field(n["raw"], ("asset_id", "assetId")) == before["expectedAssetId"] and near_box(n["box"], source["box"], tolerance)]
            # An inserted ID is resolved only from a unique observed post-edit asset+box.
            native = candidates[0] if len(candidates) == 1 else None
            check(sid, "insertedNativeIdResolved", "unique observed asset and box", native["id"] if native else None, "pass" if native else "fail")
        if not native:
            check(sid, "nativeElementPresent", True, False, "fail");continue
        actual_asset = first_field(native["raw"], ("asset_id", "assetId"))
        if before.get("expectedNativeOpacity") is not None:
            actual_opacity = first_field(native["raw"], ("opacity",))
            wanted_opacity = before["expectedNativeOpacity"]
            check(sid, "image.nativeOpacity", wanted_opacity, actual_opacity,
                  "unverified" if actual_opacity is None else "pass" if actual_opacity == wanted_opacity else "fail",
                  reason=LIMITATIONS["nativeOpacity"])
        mappings.append({"sourceElementId": sid, "nativeElementId": native["id"], "nativePageId": page["id"], "pageIndex": page["index"],
                         "nativeElementType": native["type"], "observedBox": native["box"], "observedText": native["text"], "observedAssetId": actual_asset})
        expected_kinds = ["text"] if kind(source) == "text" else ["image", "shape"] if kind(source) in GRAPHICS else ["image"]
        check(sid, "nativeEditableElementType", expected_kinds, native["type"], "pass" if native["type"] in expected_kinds else "fail")
        for field in ("x", "y", "width", "height"):
            actual = native["box"].get(field) if native["box"] else None; wanted = source["box"][field]
            automatic = kind(source) == "text" and field == "height"
            ok = actual is not None and (actual <= wanted + tolerance if automatic else abs(actual-wanted) <= tolerance)
            check(sid, "automaticTextHeightWithinLayout" if automatic else "box."+field, wanted, actual, "unverified" if actual is None else "pass" if ok else "fail", **({"textHeightPolicy": "automatic", "overflowPx": max(0, actual-wanted) if actual is not None else None} if automatic else {}))
        if kind(source) == "text":
            check(sid, "text", source["text"], native["text"], "pass" if source["text"] == native["text"] else "fail")
            f = source["font"]
            fields = (("font.sizePx", f.get("sizePx", 0) * plan.get("assumptions", {}).get("fontSizeScale", 1), ("font_size", "fontSize")), ("color", source.get("color"), ("color",)),
                      ("font.weight", "bold" if f.get("weight",400)>=600 else "normal", ("font_weight", "fontWeight")),
                      ("align", {"left":"start","right":"end","center":"center"}.get(source.get("align","left")), ("text_align", "textAlign")),
                      ("font.lineHeight", f.get("lineHeight"), ("line_height", "lineHeight")))
            for field, wanted, names in fields:
                actual = first_field(native["raw"], names)
                ok = abs(actual-wanted)<=0.01 if numeric(actual) is not None and numeric(wanted) is not None else actual == wanted
                check(sid, field, wanted, actual, "unverified" if actual is None or wanted is None else "pass" if ok else "fail")
        if before.get("expectedAssetId"):
            check(sid, "preparedAssetId", before["expectedAssetId"], actual_asset, "unverified" if actual_asset is None else "pass" if actual_asset == before["expectedAssetId"] else "fail")
        if kind(source) == "image":
            check(sid, "image.internalFillCrop", "full prepared viewport", None, "unverified", reason=LIMITATIONS["crop"])
        if before.get("photoPreservationRequired"):
            check(sid, "photo.nativeIdUnchanged", before["nativeElementIdBefore"], native["id"], "pass" if native["id"] == before["nativeElementIdBefore"] else "fail")
            expected_asset = before.get("observedAssetIdBefore")
            check(sid, "photo.assetIdUnchanged", expected_asset, actual_asset, "unverified" if not expected_asset or not actual_asset else "pass" if expected_asset == actual_asset else "fail")
            check(sid, "photo.geometryUnchanged", before["observedBoxBefore"], native["box"], "unverified" if not before["observedBoxBefore"] or not native["box"] else "pass" if near_box(before["observedBoxBefore"], native["box"], 1e-6) else "fail")
    counts = {s:sum(c["status"]==s for c in checks) for s in ("pass","fail","unverified")}
    report = {"adapterVersion":VERSION,"status":"readback_discrepancies" if counts["fail"] else "supported_checks_passed_with_unverified_fields",
            "summary":counts,"checks":checks,"postEditMappings":mappings,"limitations":LIMITATIONS,"commitStatus":"not_confirmed_by_offline_verifier",
            "visualReviewRequired":True,"note":"Successful requests or supported checks do not prove unavailable fields or a committed/saved design."}
    return apply_operation_evidence(report)


def index_list(values):
    result=[]
    for value in values or []:
        result.extend(int(v) for v in str(value).split(",") if v)
    if any(v<1 for v in result):
        raise ValueError("Protected page indices must be positive, 1-based native/source indices.")
    return sorted(set(result))



def compact_receipt(value, request=None, baseline=None):
    """Lossless raw receipt stays on disk; project decisions, not repeated state."""
    args = (request or {}).get("arguments", request or {})
    ops = args.get("operations")
    status = summarize_receipt(value, len(ops) if ops is not None else None)
    states = [o for o in walk(value) if all(isinstance(o.get(k), list) for k in ("pages", "richtexts", "fills"))]
    # A changed schema must not silently produce a success-only summary.
    out = {"acceptance": status, "stateAvailable": len(states) == 1,
           "verification": "geometry/text readback only; fonts, layers and visual QA remain separate"}
    out["errors"] = [{k: o[k] for k in ("error", "errors", "message") if k in o}
                     for o in walk(value) if o.get("isError") or o.get("error") or o.get("errors")]
    if len(states) != 1:
        out["inspectionRequired"] = "Expected one complete state; inspect raw receipt and current schema."
        return out
    state = states[0]
    out["pages"] = [{k: p.get(k) for k in ("page_id", "page_number")} for p in state["pages"]]
    if state.get("transaction"):
        out["transaction"] = state["transaction"]
    targets = {op.get("element_id") for op in ops or [] if op.get("element_id")}
    inserted_pages = {op["page_id"] for op in ops or [] if op["type"] == "insert_fill"}
    basestates = [o for o in walk(baseline) if all(isinstance(o.get(k), list) for k in ("pages", "richtexts", "fills"))] if baseline else []
    before = {e["element_id"]: e for e in basestates[0]["richtexts"] + basestates[0]["fills"]} if len(basestates) == 1 else {}
    current = {e["element_id"]: e for e in state["richtexts"] + state["fills"]}
    if baseline is not None and len(basestates) != 1:
        out["inspectionRequired"] = "Baseline schema is incomplete or ambiguous."
    if len(current) != len(state["richtexts"]) + len(state["fills"]):
        out["inspectionRequired"] = "Duplicate element IDs in readback."
    out["pageStructureChanged"] = bool(len(basestates) == 1 and state["pages"] != basestates[0]["pages"])
    unexpected = [eid for eid, e in current.items() if eid in before and e != before[eid] and eid not in targets]
    deleted = sorted(set(before) - set(current))
    out["unexpectedChangedIds"] = unexpected
    out["removedIds"] = deleted
    expected_deleted = {op["element_id"] for op in ops or [] if op["type"] == "delete_element"}
    out["unexpectedRemovedIds"] = sorted(set(deleted) - expected_deleted)
    added = set(current) - set(before) if before else set()
    insertion_indices = {p["page_number"] for p in state["pages"] if p["page_id"] in inserted_pages}
    out["unexpectedAddedIds"] = sorted(eid for eid in added if current[eid]["page_index"] not in insertion_indices)
    if inserted_pages and before:
        for pid in inserted_pages:
            indices = {p["page_number"] for p in state["pages"] if p["page_id"] == pid}
            found = sum(current[eid]["page_index"] in indices for eid in added)
            expected = sum(op["type"] == "insert_fill" and op["page_id"] == pid for op in ops)
            if found != expected:
                out["inspectionRequired"] = "Inserted element count/page differs from request; resolve raw state."

    out["missingTargetIds"] = sorted(targets - set(current) - {op["element_id"] for op in ops or [] if op["type"] == "delete_element"})
    wanted = targets | set(unexpected)
    if ops is None:  # One initial index for binding, never repeated after every edit.
        wanted = set(current)
    elif inserted_pages:
        page_indices = {p["page_number"] for p in state["pages"] if p["page_id"] in inserted_pages}
        wanted |= {eid for eid,e in current.items() if eid not in before and e["page_index"] in page_indices}
        if not before:
            out["inspectionRequired"] = "Insertion candidates need a baseline for unique binding."
    records = []
    for eid in sorted(wanted & set(current)):
        e = current[eid]
        item = {"id": eid, "page": e["page_index"], "box": e.get("containerElement")}
        if "asset_id" in e:
            item["assetId"] = e["asset_id"]
        if e.get("regions"):
            actual = "".join(r.get("text", "") for r in e["regions"])
            replacement = next((op["text"] for op in reversed(ops or []) if op["type"] == "replace_text" and op["element_id"] == eid), None)
            item["textMatchesRequested"] = actual == replacement if replacement is not None else None
            if replacement is None or actual != replacement:
                item["text"] = actual if eid in unexpected or replacement is not None else actual[:180]
                item["textTruncated"] = len(actual) > 180 if replacement is None and eid not in unexpected else False
        records.append(item)
    out["elements"] = records
    # Compare final requested properties, without treating unsupported/omitted fields as passed.
    desired = {}
    unverified = set()
    for op in ops or []:
        eid, typ = op.get("element_id"), op["type"]
        target = desired.setdefault(eid, {}) if eid else {}
        if typ == "replace_text": target["text"] = op["text"]
        elif typ == "find_and_replace_text":
            previous = target.get("text", "".join(r.get("text", "") for r in before.get(eid, {}).get("regions", [])))
            if previous.count(op["find_text"]) == 1: target["text"] = previous.replace(op["find_text"], op["replace_text"], 1)
            else: unverified.add("find_and_replace_text: exact baseline needed")
        elif typ == "position_element": target.update({k: op[k] for k in ("left", "top") if k in op})
        elif typ == "resize_element": target.update({k: op[k] for k in ("width", "height") if k in op})
        elif typ == "update_fill": target["asset_id"] = op.get("asset_id")
        elif typ not in ("delete_element",): unverified.add(typ)
    failures, checked = [], 0
    for eid, properties in desired.items():
        record = current.get(eid, {})
        box = record.get("containerElement", {})
        observed = {**box.get("position", {}), **box.get("dimension", {}), "asset_id": record.get("asset_id"),
                    "text": "".join(r.get("text", "") for r in record.get("regions", []))}
        for key, expected in properties.items():
            actual = observed.get(key)
            equal = math.isclose(actual, expected, abs_tol=.01) if key in ("left", "top", "width", "height") and numeric(actual) is not None else actual == expected
            checked += 1
            if not equal: failures.append({"elementId": eid, "property": key, "expected": expected, "actual": actual})
    out["propertyChecks"] = {"checked": checked, "failed": failures, "unverifiedOperationTypes": sorted(unverified)}
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=parser.add_subparsers(dest="command",required=True)
    compile_parser=sub.add_parser("compile",help="Compile without sending or applying requests")
    compile_parser.add_argument("--design",required=True);compile_parser.add_argument("--readback",action="append",required=True)
    compile_parser.add_argument("--mapping");compile_parser.add_argument("--upload-manifest");compile_parser.add_argument("--baseline")
    compile_parser.add_argument("--protected-pages",nargs="*",default=[]);compile_parser.add_argument("--source-page",action="append")
    compile_parser.add_argument("--insert-element",action="append",default=[]);compile_parser.add_argument("--link-id");compile_parser.add_argument("--transaction-id")
    compile_parser.add_argument("--font-scale",type=float,default=1);compile_parser.add_argument("--line-height-unit",choices=("ratio","omit"),default="ratio")
    compile_parser.add_argument("--page-index-base",type=int,choices=(0,1),default=1);compile_parser.add_argument("--out",required=True)
    verify=sub.add_parser("verify",help="Verify real native readback; unavailable fields remain unverified")
    verify.add_argument("--design",required=True);verify.add_argument("--plan",required=True);verify.add_argument("--readback",action="append",required=True)
    verify.add_argument("--receipt",action="append",default=[]);verify.add_argument("--expected-count",type=int,nargs="+")
    verify.add_argument("--page-index-base",type=int,choices=(0,1),default=1);verify.add_argument("--tolerance",type=float,default=1);verify.add_argument("--out",required=True)
    summary=sub.add_parser("summarize",help="Summarize every attempt, including failures and missing results")
    summary.add_argument("--receipt",action="append",required=True);summary.add_argument("--expected-count",type=int,nargs="+");summary.add_argument("--out",required=True)
    compact=sub.add_parser("compact",help="Summarize raw receipt plus changed native state; retain raw file")
    compact.add_argument("--receipt",required=True);compact.add_argument("--request");compact.add_argument("--baseline");compact.add_argument("--out",required=True)
    args=parser.parse_args(argv)
    if args.command=="compact":
        result=compact_receipt(load(args.receipt),load(args.request) if args.request else None,load(args.baseline) if args.baseline else None)
        save(args.out,result)
        print(json.dumps(result,ensure_ascii=False))
        problem = any(result.get(k) for k in ("inspectionRequired", "missingTargetIds", "unexpectedChangedIds", "unexpectedRemovedIds", "unexpectedAddedIds", "pageStructureChanged", "errors")) or bool(result.get("propertyChecks", {}).get("failed"))
        return 0 if not problem and (not args.request or result["acceptance"]["allAppliedConfirmed"]) else 1
    if args.command=="compile":
        pages=combine_readbacks([(name,load(name)) for name in args.readback],args.page_index_base)
        result=compile_plan(load(args.design),pages,load(args.mapping) if args.mapping else {},load(args.upload_manifest) if args.upload_manifest else {},
                            baseline=load(args.baseline) if args.baseline else None,protected_pages=index_list(args.protected_pages),link_id=args.link_id,
                            transaction_id=args.transaction_id,insert_elements=args.insert_element,source_pages=args.source_page,font_scale=args.font_scale,line_height_unit=args.line_height_unit)
    elif args.command=="verify":
        result=verify_plan(load(args.design),combine_readbacks([(name,load(name)) for name in args.readback],args.page_index_base),load(args.plan),args.tolerance)
        if args.receipt:
            apply_operation_evidence(result,summarize_attempts([(name,load(name)) for name in args.receipt],args.expected_count))
    else:
        result=summarize_attempts([(name,load(name)) for name in args.receipt],args.expected_count)
    save(args.out,result)
    console={"output":args.out,"status":result["status"]}
    if args.command == "verify":
        console.update(readbackStatus=result["readbackStatus"], readbackSummary=result["readbackSummary"],
                       operationAcceptanceStatus=result["operationAcceptanceStatus"], operationSummary=result["operationSummary"])
    else:
        console["summary"]=result["summary"]
    print(json.dumps(console,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
