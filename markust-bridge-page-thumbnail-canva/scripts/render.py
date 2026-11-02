#!/usr/bin/env python3
"""Render editable design JSON locally with Pillow; never alter source assets.

python render.py --design /job/design.json --output /job/rendered --validate-only
python render.py --design /job/design.json --output /job/rendered

Font files, copy, geometry, colors, spacing, and crops come from the job JSON.
Validation is read-only. Prepared crops and previews are written under --output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


class DesignError(ValueError):
    """Actionable invalid-source error, including the source element/asset ID."""


def fail(message: str) -> None:
    raise DesignError(message)


def number(value: Any, name: str, minimum: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        fail(f"{name}: expected a finite number")
    if minimum is not None and value < minimum:
        fail(f"{name}: expected at least {minimum}")
    return float(value)


def local_path(root: Path, value: str, name: str, *, relative_only: bool = False) -> Path:
    if not isinstance(value, str) or not value or "://" in value:
        fail(f"{name}: set a local file path")
    path = Path(value).expanduser()
    if relative_only and path.is_absolute():
        fail(f"{name}: asset localPath must be relative to the job JSON")
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def output_path(root: Path, value: str, name: str) -> Path:
    path = local_path(root, value, name, relative_only=True)
    if not path.is_relative_to(root.resolve()):
        fail(f"{name}: output path escapes --output")
    return path


def color(value: Any, opacity: float = 1) -> tuple[int, int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        fail(f"Invalid color {value!r}; use #RRGGBB or #RRGGBBAA")
    alpha = int(value[7:9], 16) if len(value) == 9 else 255
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) + (round(alpha * opacity),)


def opacity_for(element: dict) -> float:
    opacity = number(element.get("opacity", 1), f"{element['id']}.opacity", 0)
    if opacity > 1:
        fail(f"{element['id']}.opacity: maximum is 1")
    return opacity


def font_for(element: dict, root: Path) -> ImageFont.FreeTypeFont:
    config = element.get("font", {})
    size = number(config.get("sizePx"), f"{element['id']}.font.sizePx", 1)
    path = local_path(root, config.get("localPath"), f"{element['id']}.font.localPath")
    if not path.is_file():
        fail(f"{element['id']}: local font does not exist: {path}")
    index = config.get("localFaceIndex", 0)
    if not isinstance(index, int) or index < 0:
        fail(f"{element['id']}.font.localFaceIndex: expected a nonnegative integer")
    try:
        return ImageFont.truetype(str(path), max(1, round(size)), index=index)
    except (OSError, ValueError) as exc:
        fail(f"{element['id']}: cannot load selected font/face: {exc}")


def line_metrics(line: str, font: ImageFont.FreeTypeFont, tracking: float) -> dict:
    """Visible glyph bounds at a shared left baseline; no font-metric padding."""
    if not line:
        return {"box": (0.0, 0.0, 0.0, 0.0), "positions": []}
    if tracking == 0:
        return {"box": tuple(float(v) for v in font.getbbox(line, anchor="ls")), "positions": None}
    positions = [font.getlength(line[:i + 1]) - font.getlength(ch) + tracking * i for i, ch in enumerate(line)]
    bounds = []
    for ch, x in zip(line, positions):
        left, top, right, bottom = font.getbbox(ch, anchor="ls")
        bounds.append((x + left, top, x + right, bottom))
    return {"box": (min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)), "positions": positions}


def text_layout(element: dict, root: Path) -> dict:
    text = element.get("text")
    if not isinstance(text, str) or not text.strip():
        fail(f"{element['id']}: fill the text placeholder before production rendering")
    font = font_for(element, root)
    config = element["font"]
    size = number(config["sizePx"], f"{element['id']}.font.sizePx", 1)
    leading = config.get("lineHeightPx")
    if leading is None:
        leading = size * number(config.get("lineHeight", 1.15), f"{element['id']}.font.lineHeight", 0.01)
    leading = number(leading, f"{element['id']}.font.lineHeightPx", 0.01)
    tracking = number(config.get("letterSpacingPx", 0), f"{element['id']}.font.letterSpacingPx")
    lines = text.split("\n")
    metrics = [line_metrics(line, font, tracking) for line in lines]
    visible = [(i, m["box"]) for i, m in enumerate(metrics) if lines[i]]
    top = min(i * leading + b[1] for i, b in visible)
    bottom = max(i * leading + b[3] for i, b in visible)
    width = max(m["box"][2] - m["box"][0] for m in metrics)
    height = bottom - top
    box = element["box"]
    if width > box["width"] + 1e-6 or height > box["height"] + 1e-6:
        fail(f"{element['id']}: text overflows its box; visible {width:.3f}x{height:.3f}px, box {box['width']}x{box['height']}px. Revise copy, explicit line breaks, box, or JSON font size; no automatic shrinking is applied.")
    if element.get("align", "left") not in ("left", "center", "right"):
        fail(f"{element['id']}.align: choose left, center, or right")
    if element.get("verticalAlign", "top") not in ("top", "middle", "bottom"):
        fail(f"{element['id']}.verticalAlign: choose top, middle, or bottom")
    return {"font": font, "lines": lines, "metrics": metrics, "leading": leading, "tracking": tracking, "top": top, "width": width, "height": height}


def crop_rect(rect: Any, size: tuple[int, int], name: str) -> tuple[float, float, float, float]:
    if not isinstance(rect, dict):
        fail(f"{name}: fill sourceRectPx with x, y, width, height")
    x = number(rect.get("x"), f"{name}.x", 0)
    y = number(rect.get("y"), f"{name}.y", 0)
    w = number(rect.get("width"), f"{name}.width", 0.000001)
    h = number(rect.get("height"), f"{name}.height", 0.000001)
    if x + w > size[0] + 1e-6 or y + h > size[1] + 1e-6:
        fail(f"{name}: crop exceeds source pixels {size[0]}x{size[1]}")
    return x, y, x + w, y + h


def source_crop(image: Image.Image, extent: tuple[float, float, float, float], size: tuple[int, int]) -> Image.Image:
    """RGBA throughout: alpha is never discarded, inferred, or removed."""
    integer = all(abs(v - round(v)) < 1e-9 for v in extent)
    if integer and size == (round(extent[2] - extent[0]), round(extent[3] - extent[1])):
        return image.crop(tuple(round(v) for v in extent))
    return image.resize(size, Image.Resampling.LANCZOS, box=extent)


def photo_mapping_mode(design: dict) -> str | None:
    mapping = design.get("photoMapping", design.get("product", {}).get("photoMapping"))
    if isinstance(mapping, str):
        return mapping
    return mapping.get("mode") if isinstance(mapping, dict) else None


def validate_label(element: dict, design: dict) -> None:
    role = str(element.get("labelRole", "")).strip().casefold().replace("-", "_")
    text = str(element.get("text", "")).strip().casefold()
    # Full label equality is intentional: normal prose containing "before" or "after" is allowed.
    temporal = role in ("before", "after", "before_label", "after_label") or text in ("before", "after")
    if temporal and photo_mapping_mode(design) != "confirmed_before_after":
        fail(f"{element['id']}: Before/After labels require photoMapping.mode=confirmed_before_after; supplied angles or unconfirmed photos do not establish time states")


class AssetStore:
    def __init__(self, design: dict, root: Path):
        self.root = root
        assets = design.get("assets", [])
        if not isinstance(assets, list):
            fail("assets: expected an array")
        self.assets = {}
        self.images = {}
        self.sources = {}
        for asset in assets:
            aid = asset.get("id")
            if not isinstance(aid, str) or not aid or aid in self.assets:
                fail(f"assets: duplicate or missing id {aid!r}")
            if asset.get("kind") not in ("photo", "logo", "graphic"):
                fail(f"{aid}.kind: choose photo, logo, or graphic")
            local_path(root, asset.get("localPath"), f"{aid}.localPath", relative_only=True)
            if asset.get("preparedCrop") is not None and Path(asset["localPath"]).suffix.lower() != ".png":
                fail(f"{aid}: prepared localPath must name a PNG output")
            self.assets[aid] = asset

    def load(self, aid: str, stack: tuple[str, ...] = ()) -> Image.Image:
        if aid in self.images:
            return self.images[aid]
        if aid not in self.assets:
            fail(f"Unknown assetId {aid!r}")
        if aid in stack:
            fail(f"Prepared crop dependency cycle: {' -> '.join(stack + (aid,))}")
        asset = self.assets[aid]
        prepared = asset.get("preparedCrop")
        if prepared is None:
            path = local_path(self.root, asset["localPath"], f"{aid}.localPath", relative_only=True)
            if not path.is_file():
                fail(f"{aid}: source asset does not exist: {path}")
            try:
                with Image.open(path) as source:
                    image = source.convert("RGBA")
            except (OSError, ValueError) as exc:
                fail(f"{aid}: cannot read source image: {exc}")
            self.sources[aid] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pixelSize": list(image.size)}
        else:
            if not isinstance(prepared, dict):
                fail(f"{aid}.preparedCrop: expected an object")
            sid = prepared.get("sourceAssetId")
            source = self.load(sid, stack + (aid,))
            if asset["kind"] != self.assets[sid]["kind"]:
                fail(f"{aid}: prepared crop must preserve source asset kind")
            width = number(asset.get("width"), f"{aid}.width", 1)
            height = number(asset.get("height"), f"{aid}.height", 1)
            if width != round(width) or height != round(height):
                fail(f"{aid}: prepared asset width and height must be integer pixel sizes")
            extent = crop_rect(prepared.get("sourceRectPx"), source.size, f"{aid}.preparedCrop.sourceRectPx")
            if any(prepared.get(k) for k in ("flippedHorizontally", "flippedVertically", "retouch", "filter", "backgroundRemoved")):
                fail(f"{aid}: prepared assets support crop and scale only; preserve supplied pixels and alpha")
            image = source_crop(source, extent, (round(width), round(height)))
        for key, observed in (("width", image.width), ("height", image.height)):
            expected = asset.get(key)
            if expected is not None and number(expected, f"{aid}.{key}", 1) != observed:
                fail(f"{aid}: recorded {key} {expected} differs from actual pixels {observed}")
        self.images[aid] = image
        return image


def validate_design(design: dict, design_path: Path) -> AssetStore:
    root = design_path.resolve().parent
    canvas = design.get("canvas", {})
    width = number(canvas.get("width"), "canvas.width", 1)
    height = number(canvas.get("height"), "canvas.height", 1)
    if width != round(width) or height != round(height):
        fail("canvas: width and height must be integer pixel sizes")
    if canvas.get("unit", "px") != "px":
        fail("canvas.unit: only px is supported")
    pages = design.get("pages")
    if not isinstance(pages, list) or not pages:
        fail("pages: provide one or more page objects")
    if canvas.get("pages", len(pages)) != len(pages):
        fail("canvas.pages must equal the actual number of page objects")
    page_ids, element_ids = set(), set()
    assets = AssetStore(design, root)
    for aid in assets.assets:
        assets.load(aid)  # In memory only, including derived crops.
    for page in pages:
        pid = page.get("id")
        if not isinstance(pid, str) or not pid or pid in page_ids:
            fail(f"pages: duplicate or missing page id {pid!r}")
        page_ids.add(pid)
        color(page.get("background", "#FFFFFF"))
        filename = page.get("filename", f"{pid}.png")
        if Path(filename).suffix.lower() != ".png":
            fail(f"{pid}.filename: use a PNG filename")
        output_path(Path("/validation-output"), filename, f"{pid}.filename")
        elements = page.get("elements")
        if not isinstance(elements, list):
            fail(f"{pid}.elements: expected an array")
        for element in elements:
            eid = element.get("id")
            if not isinstance(eid, str) or not eid or eid in element_ids:
                fail(f"elements: duplicate or missing id {eid!r}")
            element_ids.add(eid)
            number(element.get("z", 0), f"{eid}.z")
            if number(element.get("rotationDegrees", 0), f"{eid}.rotationDegrees") != 0:
                fail(f"{eid}: nonzero rotation is not supported by this local renderer")
            box = element.get("box", {})
            x = number(box.get("x"), f"{eid}.box.x", 0)
            y = number(box.get("y"), f"{eid}.box.y", 0)
            w = number(box.get("width"), f"{eid}.box.width", 0.000001)
            h = number(box.get("height"), f"{eid}.box.height", 0.000001)
            if x + w > width + 1e-6 or y + h > height + 1e-6:
                fail(f"{eid}: box exceeds the {width}x{height}px canvas")
            opacity = opacity_for(element)
            kind = element.get("type")
            if kind == "text":
                validate_label(element, design)
                color(element.get("color", "#111111"), opacity)
                text_layout(element, root)
            elif kind == "image":
                asset = assets.assets.get(element.get("assetId"))
                if asset is None:
                    fail(f"{eid}: unknown assetId {element.get('assetId')!r}")
                crop = element.get("crop", {})
                if not isinstance(crop, dict):
                    fail(f"{eid}.crop: expected an object")
                if crop.get("flippedHorizontally") or crop.get("flippedVertically"):
                    fail(f"{eid}: image flipping is not supported; photos remain crop/scale only")
                if asset["kind"] == "photo" and opacity != 1:
                    fail(f"{eid}: photo opacity must remain 1; crop and scale only")
                image_for_element(element, assets)
            elif kind in ("rect", "rectangle", "ellipse"):
                color(element.get("fill"), opacity)
            elif kind == "frame":
                color(element.get("stroke"), opacity)
                stroke = number(element.get("strokeWidthPx"), f"{eid}.strokeWidthPx", 0.000001)
                if 2 * stroke > min(w, h):
                    fail(f"{eid}: frame stroke consumes its transparent center")
            else:
                fail(f"{eid}: unsupported type {kind!r}")
    return assets


def image_for_element(element: dict, assets: AssetStore) -> tuple[Image.Image, dict]:
    image = assets.load(element["assetId"])
    crop = element.get("crop", {})
    w, h = max(1, round(element["box"]["width"])), max(1, round(element["box"]["height"]))
    extent = (0.0, 0.0, float(image.width), float(image.height))
    if not crop.get("preparedAssetIsViewport", False) and crop.get("sourceRectPx") is not None:
        extent = crop_rect(crop["sourceRectPx"], image.size, f"{element['id']}.crop.sourceRectPx")
    fit = crop.get("fit", element.get("fit", "cover"))
    if fit == "fill_prepared_viewport":
        fit = "fill"
    if fit not in ("cover", "contain", "fill"):
        fail(f"{element['id']}.crop.fit: choose cover, contain, or fill")
    if fit == "fill" and assets.assets[element["assetId"]]["kind"] == "photo" and not crop.get("preparedAssetIsViewport", False):
        fail(f"{element['id']}: photo fill requires an explicit prepared viewport; otherwise use cover or contain")
    sw, sh = extent[2] - extent[0], extent[3] - extent[1]
    if fit == "cover":
        target_ratio = w / h
        cw, ch = (sh * target_ratio, sh) if sw / sh > target_ratio else (sw, sw / target_ratio)
        focal = crop.get("focalPoint", crop.get("focalPointWithinRegion", {"x": 0.5, "y": 0.5}))
        fx = number(focal.get("x"), f"{element['id']}.crop.focalPoint.x", 0)
        fy = number(focal.get("y"), f"{element['id']}.crop.focalPoint.y", 0)
        if fx > 1 or fy > 1:
            fail(f"{element['id']}: crop focal point must be within 0..1")
        x = extent[0] + max(0, min(sw - cw, fx * sw - cw / 2))
        y = extent[1] + max(0, min(sh - ch, fy * sh - ch / 2))
        extent = (x, y, x + cw, y + ch)
        placed = source_crop(image, extent, (w, h))
    elif fit == "contain":
        scale = min(w / sw, h / sh)
        size = (max(1, round(sw * scale)), max(1, round(sh * scale)))
        fitted = source_crop(image, extent, size)
        placed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        placed.alpha_composite(fitted, ((w - size[0]) // 2, (h - size[1]) // 2))
    else:
        placed = source_crop(image, extent, (w, h))
    opacity = opacity_for(element)
    if opacity != 1:
        placed = placed.copy()
        placed.putalpha(placed.getchannel("A").point(lambda v: round(v * opacity)))
    return placed, {"assetId": element["assetId"], "sourceAssetPixelSize": list(image.size), "usedSourceRectPx": {"x": extent[0], "y": extent[1], "width": extent[2] - extent[0], "height": extent[3] - extent[1]}, "renderedPixelSize": [w, h], "fit": fit, "preparedAssetIsViewport": crop.get("preparedAssetIsViewport", False)}


def draw_text(layer: Image.Image, element: dict, root: Path) -> dict:
    layout = text_layout(element, root)
    box = element["box"]
    offset = 0 if element.get("verticalAlign", "top") == "top" else (box["height"] - layout["height"]) / (2 if element["verticalAlign"] == "middle" else 1)
    baseline = box["y"] + offset - layout["top"]
    draw = ImageDraw.Draw(layer)
    fill = color(element.get("color", "#111111"), opacity_for(element))
    for i, (line, metrics) in enumerate(zip(layout["lines"], layout["metrics"])):
        left, _, right, _ = metrics["box"]
        width = right - left
        alignment = element.get("align", "left")
        x = box["x"] + (0 if alignment == "left" else (box["width"] - width) / 2 if alignment == "center" else box["width"] - width) - left
        y = baseline + i * layout["leading"]
        if metrics["positions"] is None:
            draw.text((x, y), line, font=layout["font"], fill=fill, anchor="ls")
        else:
            for ch, delta in zip(line, metrics["positions"]):
                draw.text((x + delta, y), ch, font=layout["font"], fill=fill, anchor="ls")
    return {"visibleGlyphSizePx": [layout["width"], layout["height"]], "localFontPixelSize": layout["font"].size, "lineHeightPx": layout["leading"], "requestedFamily": element["font"].get("requestedFamily"), "effectiveLocalPath": str(local_path(root, element["font"]["localPath"], "font.localPath")), "nativeFamilyVerified": False, "nativeFontVerification": "not_checked_locally"}


def generated_name(identifier: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]", "_", identifier)[:80] or "element"
    return readable + "-" + hashlib.sha256(identifier.encode()).hexdigest()[:10] + ".png"


def primitive_for_element(element: dict) -> Image.Image:
    box = element["box"]
    size = (max(1, round(box["width"])), max(1, round(box["height"])))
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    bounds = (0, 0, size[0] - 1, size[1] - 1)
    if element["type"] == "frame":
        draw.rectangle(bounds, outline=color(element["stroke"], opacity_for(element)), width=max(1, round(element["strokeWidthPx"])))
    else:
        method = draw.ellipse if element["type"] == "ellipse" else draw.rectangle
        method(bounds, fill=color(element["fill"], opacity_for(element)))
    return image


def render_page(page: dict, design: dict, assets: AssetStore, root: Path) -> tuple[Image.Image, dict]:
    size = (round(design["canvas"]["width"]), round(design["canvas"]["height"]))
    canvas = Image.new("RGBA", size, color(page.get("background", "#FFFFFF")))
    report = {"pageId": page["id"], "pixelSize": list(size), "elements": []}
    for element in sorted(page["elements"], key=lambda e: e.get("z", 0)):
        box = element["box"]
        kind = element["type"]
        info = {"id": element["id"], "type": kind, "box": box, "z": element.get("z", 0)}
        if kind == "image":
            image, placement = image_for_element(element, assets)
            canvas.alpha_composite(image, (round(box["x"]), round(box["y"])))
            info["imagePlacement"] = placement
        elif kind == "text":
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            info["textMetrics"] = draw_text(layer, element, root)
            canvas = Image.alpha_composite(canvas, layer)
        else:
            canvas.alpha_composite(primitive_for_element(element), (round(box["x"]), round(box["y"])))
        report["elements"].append(info)
    return canvas, report


def render_design(design_path: Path, output: Path | None, *, validate_only: bool = False) -> dict:
    design_path = design_path.resolve()
    design = json.loads(design_path.read_text(encoding="utf-8"))
    assets = validate_design(design, design_path)
    if validate_only:
        return {"status": "valid", "pageCount": len(design["pages"]), "writesPerformed": False}
    if output is None:
        fail("--output is required when rendering; source JSON and original assets are never overwritten")
    output = output.resolve()
    # Resolve and protect every output path before creating any directory or writing any file.
    source_paths = {Path(s["path"]).resolve() for s in assets.sources.values()} | {design_path}
    source_paths.update(local_path(design_path.parent, e["font"]["localPath"], "font.localPath") for page in design["pages"] for e in page["elements"] if e["type"] == "text")
    destinations = [output_path(output, page.get("filename", f"{page['id']}.png"), "page.filename") for page in design["pages"]]
    prepared_destinations = {aid: output_path(output, asset["localPath"], f"{aid}.localPath") for aid, asset in assets.assets.items() if asset.get("preparedCrop") is not None}
    runtime_destinations = {"elementImages": {}, "graphics": {}, "pageBackgrounds": {}}
    for page in design["pages"]:
        runtime_destinations["pageBackgrounds"][page["id"]] = output / "runtime-generated/backgrounds" / generated_name(page["id"])
        for element in page["elements"]:
            if element["type"] == "image":
                runtime_destinations["elementImages"][element["id"]] = output / "runtime-generated/images" / generated_name(element["id"])
            elif element["type"] in ("rect", "rectangle", "ellipse", "frame"):
                runtime_destinations["graphics"][element["id"]] = output / "runtime-generated/graphics" / generated_name(element["id"])
    runtime_paths = [path for group in runtime_destinations.values() for path in group.values()]
    all_destinations = destinations + list(prepared_destinations.values()) + runtime_paths + [output / "preview-all.jpg", output / "render-manifest.json"]
    if len(set(all_destinations)) != len(all_destinations):
        fail("Output filenames collide; use unique page and prepared-asset paths")
    collision = source_paths.intersection(all_destinations)
    if collision:
        fail(f"Output would overwrite source files: {', '.join(str(p) for p in collision)}")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schemaVersion": "1.0", "status": "rendered_local_preview", "sourceDesign": str(design_path), "sourceDesignSha256": hashlib.sha256(design_path.read_bytes()).hexdigest(), "sources": assets.sources, "preparedAssets": {}, "elementImages": {}, "graphics": {}, "pageBackgrounds": {}, "pages": [], "nativeCanvaVerified": False}
    for aid, destination in prepared_destinations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        image = assets.load(aid)
        image.save(destination, format="PNG", optimize=True)
        report["preparedAssets"][aid] = {"path": str(destination), "relativeOutputPath": str(destination.relative_to(output)), "pixelSize": list(image.size), "mode": "RGBA", "sourceCrop": assets.assets[aid]["preparedCrop"], "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    for page in design["pages"]:
        background_path = runtime_destinations["pageBackgrounds"][page["id"]]
        background_path.parent.mkdir(parents=True, exist_ok=True)
        background = Image.new("RGBA", (round(design["canvas"]["width"]), round(design["canvas"]["height"])), color(page.get("background", "#FFFFFF")))
        background.save(background_path, format="PNG", optimize=True)
        report["pageBackgrounds"][page["id"]] = {"path": str(background_path), "relativeOutputPath": str(background_path.relative_to(output)), "pixelSize": list(background.size), "fill": page.get("background", "#FFFFFF"), "nativeOpacity": 1}
        for element in page["elements"]:
            kind = element["type"]
            if kind == "text":
                continue
            group = "elementImages" if kind == "image" else "graphics"
            path = runtime_destinations[group][element["id"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == "image":
                image, placement = image_for_element(element, assets)
                metadata = {"assetId": element["assetId"], "placement": placement, "preparedAssetIsViewport": True, "sourceOpacity": element.get("opacity", 1), "nativeOpacity": 1}
            else:
                image = primitive_for_element(element)
                metadata = {"type": kind, "sourceFill": element.get("fill"), "sourceStroke": element.get("stroke"), "sourceOpacity": element.get("opacity", 1), "nativeOpacity": 1}
            image.save(path, format="PNG", optimize=True)
            report[group][element["id"]] = {"path": str(path), "relativeOutputPath": str(path.relative_to(output)), "pixelSize": list(image.size), "mode": "RGBA", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **metadata}
    for page, destination in zip(design["pages"], destinations):
        image, page_report = render_page(page, design, assets, design_path.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=True)
        page_report["path"] = str(destination)
        report["pages"].append(page_report)
    # Dynamic contact sheet: square thumbnails contain non-square pages without cropping.
    thumb, gap, columns = 480, 16, min(2, len(design["pages"]))
    rows = math.ceil(len(design["pages"]) / columns)
    preview = Image.new("RGB", (columns * thumb + (columns + 1) * gap, rows * thumb + (rows + 1) * gap), "#FFFFFF")
    for i, destination in enumerate(destinations):
        with Image.open(destination) as original:
            image = original.convert("RGBA")
            image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
            x = gap + (i % columns) * (thumb + gap) + (thumb - image.width) // 2
            y = gap + (i // columns) * (thumb + gap) + (thumb - image.height) // 2
            preview.paste(image, (x, y), image)
    preview.save(output / "preview-all.jpg", quality=94, optimize=True)
    report["previewPath"] = str(output / "preview-all.jpg")
    (output / "render-manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True, help="Job JSON; all asset localPath values are relative to this file")
    parser.add_argument("--output", type=Path, help="Job output directory; required for rendering")
    parser.add_argument("--validate-only", action="store_true", help="Validate using memory only; do not create files or directories")
    args = parser.parse_args()
    try:
        report = render_design(args.design, args.output, validate_only=args.validate_only)
    except (DesignError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    if args.validate_only:
        print(json.dumps(report))
    else:
        for page in report["pages"]:
            print(page["path"])
        print(report["previewPath"])
        print(str(args.output.resolve() / "render-manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
