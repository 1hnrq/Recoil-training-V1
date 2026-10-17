"""Verify all ICO frames and the exact corresponding Windows PE resources."""
from pathlib import Path
import struct

SIZES = (16, 24, 32, 48, 64, 128, 256)


def ico_frames(path):
    data = Path(path).read_bytes()
    if struct.unpack_from('<HHH', data) != (0, 1, 7):
        raise ValueError('Expected seven ICO images')
    frames = {}
    for i in range(7):
        w, h, colors, reserved, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16*i)
        w, h = w or 256, h or 256
        frame = data[offset:offset+length]
        if w != h or planes != 1 or bits != 32 or len(frame) != length:
            raise ValueError('Invalid ICO entry')
        if frame[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack_from('>II', frame, 16) != (w, h):
            raise ValueError('Invalid PNG dimensions')
        frames[w] = frame
    if tuple(sorted(frames)) != SIZES:
        raise ValueError('Missing ICO resolution')
    return frames


def verify_pe(exe, icon):
    import pefile
    expected = ico_frames(icon)
    with pefile.PE(str(exe)) as pe:
        resources = {}
        for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if kind.id not in (3, 14):
                continue
            resources[kind.id] = {}
            for name in kind.directory.entries:
                entry = name.directory.entries[0].data.struct
                resources[kind.id][name.id] = pe.get_data(entry.OffsetToData, entry.Size)
        if len(resources.get(14, {})) != 1:
            raise ValueError('Expected one official icon group')
        group = next(iter(resources[14].values()))
        if struct.unpack_from('<HHH', group) != (0, 1, 7):
            raise ValueError('Incorrect embedded group')
        found = []
        for i in range(7):
            w, h, _, _, planes, bits, length, resource_id = struct.unpack_from('<BBBBHHIH', group, 6+14*i)
            size = w or 256
            image = resources[3][resource_id]
            if (h or 256) != size or image != expected[size] or len(image) != length:
                raise ValueError('Embedded icon differs from approved ICO')
            found.append(size)
        if sorted(found) != list(SIZES):
            raise ValueError('Missing embedded size')
    return {'sizes': sorted(found), 'frames_match_source_ico': True, 'bits': 32}
