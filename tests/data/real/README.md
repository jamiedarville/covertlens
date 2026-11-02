# CL-52 real-image segmentation fixtures

These five committed inputs test segmentation, not hidden-message detection.
`manifest.json` records independently counted visible elements, approximate
horizontal centre annotations, native fixture dimensions and SHA-256 hashes.
Tests read these bytes offline with the default `SegmenterConfig`; they do not
download, regenerate, resize or recompress inputs. Counts must be within ±1;
location checks also reject merged objects plus unrelated noise.

| File | Expected elements | Provenance and licence |
| --- | ---: | --- |
| `matplotlib-bars.png` | 8 bars | Self-authored matplotlib Agg plot-only export; MIT. RGBA PNG with normal encoder row filters, no axes or tick labels. |
| `diffusion-skyline.png` | 17 buildings, including the two clipped edge buildings | Crop of the AI-generated skyline already supplied in the CL-52 branch as `generated_images/call_01a19912c046718686bd3aee7576d552.png`. The unaltered source is preserved at `sources/skyline.png`, including its trained-algorithmic-media XMP provenance. Generated for this project; distributed with the repository under MIT to the extent copyright applies. The precise generator/model, prompt and seed were not recorded; the category filename does not establish a specific model. |
| `browser-screenshot.png` | 6 signal bars | Actual headless Chromium screenshot of the self-authored `screenshot.html`; MIT. Rounded corners, gradients and shadows exercise ordinary browser rasterization. |
| `fence-tips.jpg` | 12 visible fence tips, including the clipped left tip | Photograph by **Joshep Coronel**, [PxHere photo 1598366](https://pxhere.com/en/photo/1598366), published 2019-10-23. The source page identifies it as [CC0](https://creativecommons.org/publicdomain/zero/1.0/). Cropped and re-encoded as quality-95 4:2:0 JPEG. |
| `morse-dashes.jpg` | 8 em dashes | Self-authored DejaVu Sans text rendering, antialiased at 4× then reduced once during fixture authoring; MIT. Encoded with libjpeg at quality 92, 4:2:2 with restart markers, odd dimensions 641×97. This is a Morse-like dash row, not a claim to decode a message. |

The skyline uses native source crop `(250, 820, 1700, 1240)`, retaining the
gradient sky and soft building edges while excluding the continuous common base.
The fence uses crop `(380, 270, 960, 350)` of the 1200×794 published preview,
above the connecting rail. These are deliberately isolated-object crops; they
do not demonstrate separation of touching buildings, connected fence rails,
busy scenes, arbitrary photographs or SAM-like semantic segmentation.

Fence preview downloaded on 2026-11-01:

- URL: <https://c.pxhere.com/images/35/ee/c5b6ef95ed3629f6c299f5c662dd-1598366.jpg!d>
- SHA-256: `7642d14403792645d1b61d38833db4248c4207a16b9be1ee69667c021629e4ed`
- The source page labels the author Joshep Coronel and states: “The image is
  released free of copyrights under Creative Commons CC0.”

Authoring is optional and separate from tests:

```bash
python scripts/build_real_image_fixtures.py --fence-source /path/to/fence-preview.jpg
```

Tools used: matplotlib 3.11.2, Pillow 13.0.0, Chromium and libjpeg-turbo `cjpeg` /
`djpeg`. Those tools are not library or CI test dependencies. Encoder/browser
updates can change bytes; review the images and annotations before updating the
manifest hashes. The source skyline bytes are committed because the initial
generation cannot be repeated exactly.
