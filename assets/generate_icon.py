"""Generate a crisp multi-resolution application icon at `assets/app.ico`."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def generate_icon(output_path: Path) -> None:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded crimson badge
    draw.rounded_rectangle((16, 16, 240, 240), radius=46, fill=(209, 36, 47, 255))

    # White document sheet
    draw.rounded_rectangle((52, 40, 196, 216), radius=18, fill=(255, 255, 255, 255))

    # Stylized document lines
    draw.rounded_rectangle((74, 72, 168, 86), radius=6, fill=(209, 36, 47, 255))
    draw.rounded_rectangle((74, 102, 150, 114), radius=5, fill=(148, 163, 184, 255))
    # Blackout redaction bar motif
    draw.rounded_rectangle((74, 130, 168, 146), radius=4, fill=(17, 24, 39, 255))
    draw.rounded_rectangle((74, 162, 138, 174), radius=5, fill=(148, 163, 184, 255))

    # Subtle edit pencil accent on bottom-right
    draw.ellipse((150, 150, 224, 224), fill=(31, 41, 55, 255))
    draw.polygon([(172, 200), (198, 174), (208, 184), (182, 210)], fill=(255, 255, 255, 255))
    draw.polygon([(168, 204), (172, 200), (182, 210), (166, 212)], fill=(251, 191, 36, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        output_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "app.ico"
    generate_icon(target)
    print(f"Icon generated: {target}")
