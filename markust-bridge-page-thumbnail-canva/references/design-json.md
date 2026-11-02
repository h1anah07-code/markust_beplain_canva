# Design JSON and local rendering contract

The JSON records copy, geometry, typography, colors, image crops, and stacking order. The local renderer previews it. The Canva adapter applies it to individually editable native elements using observed native IDs. A local preview is not evidence that Canva accepted the same font or geometry.

`assets/design-template.json` is a historical geometry starter, not production-ready facts/copy. Resolve product, source files/dimensions, crop recipes and fonts from this job. Select/merge `assets/focused-benefit-template.json` only for structure 05 and set canvas.pages to the requested count. Current composition/type rules are in approved-quality.md; copy/information roles are in click-through-copy.md. Keep stable structure IDs independent of output order. Preview inspection is still required even when JSON validates.

## Native wording revision

Read [native-revision.md](native-revision.md) for compact copy-only/copy-add contracts and preservation. Do not use this full reconstruction schema for native wording work.

## Source structure

- `title`: actual Canva file name, `MM.DD` of the Friday in the user request's Monday–Sunday week. Calculate with `scripts/friday_name.py`; keep the full request date, timezone and Friday date separately in runtime/naming.json.
- `canvas`: integer `width`, `height`, `unit: "px"`, and `pages` equal to the actual page-array length. The renderer supports any positive canvas size and page count; the standard thumbnail template is 1600×1600 with four pages.
- `product`: current brand/name, official source URL, verified facts, and appeal. Research and review verify facts; the renderer cannot establish efficacy from photos.
- `photoMapping`: explicit photo-state evidence, described below.
- `assets`: unique stable IDs, relative local file paths, a `kind`, and optional prepared-crop recipes.
- `pages`: unique stable IDs, PNG filenames, background colors, and native-element source objects.

All asset `localPath` values are local paths **relative to the job JSON**. Copy the supplied original assets into the job, preserving their pixels and alpha. No network URLs are loaded by the renderer. A selected font `localPath` may be relative to the job or an explicit installed local font path; copying the font into the job improves portability where permitted.

Every page has `id`, optional `filename` (defaults to `<id>.png`), `background`, and `elements`. Every element has a unique `id`, `type`, `box: {x,y,width,height}`, and `z`. Boxes and z values may be fractional. The renderer sorts ascending z and preserves array order for ties. Local output rounds image positions and raster pixel sizes to the nearest pixel; canonical floating coordinates remain unchanged for Canva. Nonzero element rotation is currently rejected instead of silently ignored.

### Assets and exact crops

`kind` is `photo`, `logo`, or `graphic`. Original assets may record `width` and `height`; when present, these must match actual source pixels. A prepared asset requires integer output pixel dimensions and a recipe:

```json
{
  "id": "portrait-frame",
  "localPath": "assets/portrait-frame.png",
  "kind": "photo",
  "width": 680,
  "height": 650,
  "preparedCrop": {
    "sourceAssetId": "portrait-original",
    "sourceRectPx": {"x": 10, "y": 30, "width": 400, "height": 382.352941}
  }
}
```

`sourceRectPx` uses pixels of the referenced source asset. Fractions are allowed; the rectangle must lie inside its source. Integer crops at their original size preserve pixel values exactly. Other crops use Lanczos scaling. Prepared-crop dependencies may refer to other assets but cannot form cycles or change `kind`. Prepared output paths must be PNG paths inside the chosen output directory.

Only crop and scale are supported. The renderer does not retouch skin, recolor photos/logos, infer transparency, remove backgrounds, flip images, or modify originals. RGBA survives loading, cropping, resizing, export, and composition. Photo-element opacity must remain 1. The starter references the bundled beplain logo at its actual 1920×1080 size and crops only its transparent outer padding; copy that original into the job. If replacing the official asset, recalculate its source dimensions and crop instead of reusing this crop. For beplain, place the latest transparent logo at top-left of every page. Do not add a white logo badge or replace source alpha. Choose a light page/column composition behind the black logo instead.

### Text elements

A text element has `text`, `font`, `color`, optional `align` (`left`, `center`, `right`), and optional `verticalAlign` (`top`, `middle`, `bottom`). Set explicit newlines in `text`. Null/empty copy fails validation.

Font fields:

| Field | Meaning |
|---|---|
| `requestedFamily` | Desired family for native authoring; does not prove availability. |
| `localPath` | Explicit local font file for the preview. There is no built-in font substitution. |
| `localFaceIndex` | Face index for a font collection; defaults to 0. |
| `sizePx` | Chosen source size; Pillow rounds fractional sizes for its local raster. |
| `weight` | Chosen weight metadata. The selected file/face must represent it; the renderer does not guess a face. |
| `lineHeight` | Baseline-spacing ratio multiplied by `sizePx`; defaults to 1.15 locally. |
| `lineHeightPx` | Optional exact local baseline spacing; takes precedence over the ratio. |
| `letterSpacingPx` | Explicit tracking; defaults to 0. |

Native asset/page/element IDs, application history, receipts, observed font families, and native verification evidence belong in separate runtime files, not the canonical intent JSON. Legacy source fields claiming `effectiveFamily` or `canvaVerified` do not establish native evidence and are not trusted by the local renderer. Its manifest always reports native font verification as `not_checked_locally`.

The renderer measures visible glyph bounds, preserving natural baselines. It fails if copy exceeds its box. It never automatically shrinks fonts, wraps text, deletes words, or rewrites marketing copy. Fix text, explicit line breaks, boxes, or font settings in the JSON. Local font metrics and native automatic text height can differ; verify actual Canva boxes after applying.

The native adapter has an explicit `--font-scale` (positive, default 1) for the observed native sizing convention. Do not assume a universal pixel-to-point conversion. `--line-height-unit ratio|omit` defaults to `ratio` and uses `font.lineHeight`; it does not convert a local `lineHeightPx` into an unsupported native unit. When native spacing is omitted or inherited, inspect and verify it. Verification uses the scale recorded in the compiled plan.

### Image elements

An image element references `assetId` and has optional `crop`:

```json
{
  "id": "portrait-main",
  "type": "image",
  "assetId": "portrait-frame",
  "z": 10,
  "box": {"x": 80, "y": 485, "width": 680, "height": 650},
  "crop": {"fit": "fill_prepared_viewport", "preparedAssetIsViewport": true},
  "opacity": 1
}
```

`preparedAssetIsViewport: true` means the assigned asset already represents its complete intended viewport; do not apply a provenance crop again. For an original image or logo, set it to false (or omit it). `crop.sourceRectPx` may select a rectangle within that assigned asset before placement. Choose `fit`:

- `cover`: proportionally fill the box, using `crop.focalPoint: {x,y}` in 0..1 (default center), recording the resulting source rectangle in the render manifest.
- `contain`: proportionally fit the complete selected image inside the box, adding transparent padding. Original logo alpha remains intact.
- `fill` / `fill_prepared_viewport`: use the prepared full viewport. Photo fill requires `preparedAssetIsViewport: true`; avoid distortion by preparing the correct crop first.

The renderer exports an **exact per-element viewport PNG** for every image, including contain padding. The native uploader/adapter uses this image-element ID upload first, so Canva places the same viewport without a second crop. This resolves aspect differences between a supplied logo file and its layout box without altering the original logo geometry.

### Rectangles, ellipses, and frames

`rect` and `rectangle` are aliases with `fill`. `ellipse` has `fill` and a transparent exterior. `frame` has `stroke`, `strokeWidthPx`, and a transparent center. Use `opacity` in 0..1; color values accept `#RRGGBB` or `#RRGGBBAA`. Alpha from both is multiplied.

Each graphic is exported as its own RGBA PNG keyed by element ID. Each page background is exported separately keyed by page ID. Native image-fill workflows use these assets as individually editable fills with **native opacity 1**, because the exported alpha already encodes source opacity. Text remains native text. The complete preview PNG is never the final editable native composition.

### Portrait selection

Every thumbnail portrait must be front-facing to at most 45°, including page 04 main/inset. Use a suitable panel from a supplied sheet; exclude its 90° panel from the Canva composition. Cropping does not change the face's pose. Record selected source panel/crop and observed view in job evidence. Approximate pose is a visual QA item, not something the renderer infers from pixels. Structural/style references do not override this limit.

### Before/After and angle-only photos

The canonical mapping is:

```json
{
  "photoMapping": {
    "mode": "angles",
    "assignments": {
      "portrait-original": "angle_front",
      "portrait-second-original": "angle_other"
    },
    "evidence": "User confirmed these are different angles, with no Before/After distinction."
  }
}
```

Modes are `unconfirmed`, `angles`, or `confirmed_before_after`. Structures 01, 04 and 05 require `confirmed_before_after`: map source assets to `before` and `after`, and record the user's confirmation and provenance. A user-authorized AI concept mapping confirms the intended asset roles, not real product-use evidence; explicitly record that distinction. The `angles` mode is for an explicitly requested angle-only variant, not a fallback that replaces the default Before/After layouts. Top-level `photoMapping` is canonical; legacy `product.photoMapping` and string-mode values are accepted for reading.

Mark temporal photo-caption elements explicitly with `labelRole: "before"` or `"after"` (case-insensitive). They are allowed only in `confirmed_before_after` mode. Exact standalone text labels “Before” and “After” are also checked, so omitting the semantic role cannot bypass the guard. Natural English prose such as “Care after a busy day” is allowed; there is no global word ban. For an explicitly requested angle-only variant, use `labelRole: "view"` and truthful view captions. Structure 01 places Before left/After right; structure 04 places Before in the lower-left inset/After in the large right photo, with both state labels inside their photos at bottom-right. Each selected source pose must independently be front-facing (0°) through at most 45°; matching direction/angle is not required. Do not invent angle degrees.

## Renderer CLI and runtime outputs

Requires Python 3.10+ and Pillow. No installed skill dependency, original job, hardcoded font, Canva account, or external tool ID is needed.

```bash
python scripts/render.py --design /absolute/job/design.json --output /absolute/job/rendered --validate-only
python scripts/render.py --design /absolute/job/design.json --output /absolute/job/rendered
```

`--design` is required. `--output` is required for rendering and may be omitted with `--validate-only`. Validation loads fonts/images and prepared crops in memory; it creates no directories or files. All validation succeeds before rendering starts. Output paths are confined to `--output` and cannot overwrite the source JSON, original images, or selected font files.

Render outputs:

| Output | Role |
|---|---|
| Page PNGs and `preview-all.jpg` | Local QA; contact-sheet size adapts to the page count and preserves non-square pages. |
| Prepared assets at `<output>/<asset.localPath>` | Crop/scale-only assets from the source recipes. |
| `runtime-generated/images/*.png` | Exact RGBA image viewports, including proportional contain padding. |
| `runtime-generated/graphics/*.png` | Separate rect/ellipse/frame fills; alpha already encoded. |
| `runtime-generated/backgrounds/*.png` | Separate solid page backgrounds. |
| `render-manifest.json` | Source hashes, source/output pixel sizes, computed crops, local text metrics, and canonical-ID-to-runtime-path mappings. |

The manifest keys are `preparedAssets[assetId]`, `elementImages[elementId]`, `graphics[elementId]`, and `pageBackgrounds[pageId]`. Each runtime entry contains an absolute `path` and `relativeOutputPath`; use those paths when the output directory differs from the job JSON directory. The source JSON is not silently rewritten to point into the renderer's output directory.

The uploader creates real Canva asset IDs from the runtime paths. Its normalized upload manifest has `assets: {assetOrElementId: realAssetId}` and `pageBackgrounds: {pageId: realAssetId}`. For images, the adapter prefers `assets[elementId]` (prepared exact viewport) over `assets[assetId]`. Graphics use `assets[elementId]`. Explicit per-element viewport uploads are preparation evidence; photo asset-ID fallback still requires source `preparedAssetIsViewport: true`.

Native page/element mappings are separate: `pages: {sourcePageId: nativePageId}`, `elements: {sourceElementId: nativeElementId}`. Revisions may add `originalElementId` to link copied elements; it is not a native ID. Actual IDs must be observed in the target design and validated against its returned page membership. Cached IDs in source fields are not sufficient authorization or evidence.

Use `scripts/canva_adapter.py --help` and the linked [Canva workflow](canva-workflow.md) for compile/verify/summarize operations. Each receipt attempt needs its own expected count, including failed and retry attempts; no count means totals remain unconfirmed. Never equate a local render with verified native application.

## Focused-benefit metadata

For structure 05, keep `focus` on the page with `appealId`, `region`, `beforeAssetId`, `afterAssetId`, `visualizable`, and `provenance`. Resolve placeholders from the actual job. Record matching pose/region/light/scale QA in evidence.json; the renderer cannot establish that an image demonstrates a benefit. A concept asset requires a readable neutral illustrative-comparison caption in the composition, without AI-related artwork wording. Metadata is not a substitute for visual inspection.
