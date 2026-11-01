# Independent JPEG decoder references (CL-52)

Self-authored 97×65 RGB gradient, encoded once using libjpeg-turbo `cjpeg` at
quality 90. All assets in this directory are distributed under MIT. Authoring
code is in `scripts/build_real_image_fixtures.py`; tests need no external codec.

- `444`, `422`, `420`: sampling factors 1×1, 2×1, 2×2 respectively.
- `restart`: 4:2:0 with a restart marker every four MCUs.
- `optimized`: 4:2:0 with optimized Huffman tables.
- `grayscale`: one component.
- `rgb`: Adobe-marked RGB, no YCbCr conversion.
- `progressive`: deliberately outside the supported pixel decoder subset.

Each supported JPEG has an independently decoded PNG reference from
`djpeg -rgb -nosmooth -dct float`. Nearest-neighbour upsampling matches the
declared decoder method; tests allow up to three sample levels of IDCT/colour
rounding difference and require mean absolute error below 0.5. Odd dimensions
exercise chroma coordinates at partially padded MCU edges.
