"""Author CL-52 fixtures once; tests consume only the committed bytes.

Requires matplotlib, Pillow, Chromium and libjpeg's cjpeg (authoring tools,
not runtime/test dependencies). Supply the downloaded fence preview using
--fence-source; its URL, licence and SHA-256 are in tests/data/real/README.md.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image, ImageDraw, ImageFont

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fence-source", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    dest = root / "tests/data/real"

    # A plot-only export: no axes/labels to mistake for repeated bars.
    fig = plt.figure(figsize=(6.4, 2.4), dpi=100, facecolor="#f5f7fa")
    ax = fig.add_axes((0, 0, 1, 1), facecolor="#f5f7fa")
    ax.bar(range(8), [36, 73, 48, 92, 64, 110, 83, 52], width=0.55, color="#427dad")
    ax.set(xlim=(-1, 8), ylim=(-12, 128))
    ax.set_axis_off()
    fig.savefig(dest / "matplotlib-bars.png", dpi=100)
    plt.close(fig)

    # Retain native pixels; omit the common base which joins the buildings.
    source = Image.open(dest / "sources/skyline.png")
    source.crop((250, 820, 1700, 1240)).save(dest / "diffusion-skyline.png")

    # A real photograph, cropped above the connecting rail to isolate tips.
    fence = Image.open(args.fence_source).convert("RGB")
    fence.crop((380, 270, 960, 350)).save(
        dest / "fence-tips.jpg", quality=95, subsampling=2
    )

    with tempfile.TemporaryDirectory(prefix="cl52-fixtures-") as tmp:
        tmpdir = Path(tmp)
        shot = tmpdir / "screenshot.png"
        subprocess.run(
            [
                "chromium",
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--window-size=640,240",
                f"--screenshot={shot}",
                (dest / "screenshot.html").as_uri(),
            ],
            check=True,
            capture_output=True,
        )

        # Independent libjpeg outputs at odd dimensions catch MCU padding,
        # chroma coordinates, restarts, RGB and optimized-table handling.
        jpeg_dest = root / "tests/data/jpeg"
        jpeg_dest.mkdir(exist_ok=True)
        gradient = Image.new("RGB", (97, 65))
        gradient.putdata(
            [
                (x * 255 // 96, y * 255 // 64, (x + y) * 255 // 160)
                for y in range(65)
                for x in range(97)
            ]
        )
        gradient_path = tmpdir / "gradient.ppm"
        gradient.save(gradient_path)
        cases = {
            "444": ["-sample", "1x1"],
            "422": ["-sample", "2x1"],
            "420": ["-sample", "2x2"],
            "restart": ["-sample", "2x2", "-restart", "4B"],
            "optimized": ["-sample", "2x2", "-optimize"],
            "grayscale": ["-grayscale"],
            "rgb": ["-rgb"],
            "progressive": ["-progressive"],
        }
        for name, options in cases.items():
            jpg = jpeg_dest / f"{name}.jpg"
            subprocess.run(
                [
                    "cjpeg",
                    "-quality",
                    "90",
                    *options,
                    "-outfile",
                    str(jpg),
                    str(gradient_path),
                ],
                check=True,
                capture_output=True,
            )
            if name != "progressive":
                reference = tmpdir / "reference.ppm"
                subprocess.run(
                    [
                        "djpeg",
                        "-rgb",
                        "-nosmooth",
                        "-dct",
                        "float",
                        "-outfile",
                        str(reference),
                        str(jpg),
                    ],
                    check=True,
                    capture_output=True,
                )
                Image.open(reference).save(jpeg_dest / f"{name}.png")
        # Chromium may capture an opaque PNG or RGBA depending on version.
        Image.open(shot).save(dest / "browser-screenshot.png")

        # Font-rendered em dashes with antialiasing and a lossy encoder.
        image = Image.new("RGB", (641 * 4, 97 * 4), "#eeeeea")
        draw = ImageDraw.Draw(image)
        font_path = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
        font = ImageFont.truetype(str(font_path), 52 * 4)
        for x in range(24, 600, 72):
            draw.text((x * 4, 4 * 4), "—", font=font, fill="#343a40")
        image = image.resize((641, 97), Image.Resampling.LANCZOS)
        ppm = tmpdir / "morse.ppm"
        image.save(ppm)
        subprocess.run(
            [
                "cjpeg",
                "-quality",
                "92",
                "-sample",
                "2x1",
                "-restart",
                "4B",
                "-outfile",
                str(dest / "morse-dashes.jpg"),
                str(ppm),
            ],
            check=True,
            capture_output=True,
        )


if __name__ == "__main__":
    main()
