"""Exactly three explicit, immutable PNG reference snapshots per selection."""
import base64
import hashlib
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent
DEFAULTS = ROOT / 'default_references'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def default_slots():
    return [{'default': i} for i in (1, 2, 3)]


def decode(slots):
    if not isinstance(slots, list) or len(slots) != 3:
        raise ValueError('请确认恰好三张参考图。')
    decoded = []
    for i, slot in enumerate(slots, 1):
        if not isinstance(slot, dict):
            raise ValueError('参考图槽位格式无效。')
        if 'default' in slot:
            n = slot['default']
            if type(n) is not int or n not in (1, 2, 3):
                raise ValueError('默认参考图编号必须为 1–3。')
            data = (DEFAULTS / f'style-reference-{n:02d}.png').read_bytes()
            origin = {'kind': 'default', 'default': n, 'name': f'默认参考图 {n}',
                      'source': 'FigureCrafter v2.5.1 explicitly bundled reference PNG; image only'}
        else:
            raw = slot.get('content_base64', '')
            if not isinstance(raw, str) or len(raw) > 9 * 1024 * 1024:
                raise ValueError('参考图超过 6 MB。')
            try:
                data = base64.b64decode(raw, validate=True)
            except Exception:
                raise ValueError('参考图编码无效。') from None
            origin = {'kind': 'upload', 'name': Path(str(slot.get('name', f'reference-{i}'))).name[:150]}
        if not data or len(data) > 6 * 1024 * 1024:
            raise ValueError('参考图为空或超过 6 MB。')
        if not data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')):
            raise ValueError('参考图仅接受 PNG 或 JPEG 图片。')
        try:
            image = fitz.Pixmap(data)
            if image.width * image.height > 30_000_000 or min(image.width, image.height) < 16:
                raise ValueError('参考图尺寸必须至少 16 像素且不超过 3000 万像素。')
            if image.colorspace and image.colorspace.n != 3:
                image = fitz.Pixmap(fitz.csRGB, image)
            png = image.tobytes('png')
        except Exception as e:
            raise ValueError('无法读取参考图：' + str(e)) from None
        decoded.append((png, {**origin, 'original_sha256': digest(data), 'sha256': digest(png)}))
    return decoded


def snapshot(directory, slots, revision):
    decoded = decode(slots)
    folder = directory / 'input/references' / f'selection-{revision}'
    folder.mkdir(parents=True, exist_ok=False)
    result = []
    for i, (data, metadata) in enumerate(decoded, 1):
        path = folder / f'style-reference-{i:02d}.png'
        path.write_bytes(data)
        result.append({**metadata, 'slot': i, 'path': str(path.relative_to(directory))})
    return result
