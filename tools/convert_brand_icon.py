"""Deterministic PNG-to-ICO conversion; Pillow is a build-time tool only.

No redraw, recoloring, cropping or replacement of the supplied artwork.
Each frame is downsampled directly from the source, never from another frame.
"""
from io import BytesIO
from pathlib import Path
import struct

SIZES = (16, 24, 32, 48, 64, 128, 256)
ROOT = Path(__file__).resolve().parents[1]


def convert():
    from PIL import Image
    folder = ROOT / 'assets/branding'
    source = folder / 'source/logomouse.png'
    target = folder / 'r6-rebuild.ico'
    preview = folder / 'preview.png'
    if target.exists() or preview.exists():
        raise FileExistsError('Refusing to overwrite existing branding outputs')
    with Image.open(source) as original:
        if original.width != original.height:
            raise ValueError('Source artwork must be square; do not distort it')
        master = original.convert('RGBA')
    images = [master.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    frames = []
    for image in images:
        stream = BytesIO()
        image.save(stream, format='PNG', optimize=True)
        frames.append(stream.getvalue())
    offset = 6 + 16 * len(frames)
    entries = []
    for size, frame in zip(SIZES, frames):
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    with target.open('xb') as stream:
        stream.write(struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries) + b''.join(frames))
    # Review sheet at native pixel sizes; not shipped to end users.
    sheet = Image.new('RGB', (680, 280), '#303030')
    x = 12
    for image in images:
        sheet.paste(image, (x, 12), image)
        x += image.width + 16
    with preview.open('xb') as stream:
        sheet.save(stream, format='PNG')
    print(f'{target}: {SIZES}, 32-bit RGBA, PNG-compressed frames')


if __name__ == '__main__':
    convert()
