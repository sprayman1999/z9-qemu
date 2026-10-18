# SPDX-License-Identifier: GPL-2.0-or-later
"""Versioned source/build provenance for standalone capture experiments."""
import json
import struct
from pathlib import Path
from probe import sha

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent


def full_sensor(path):
    """Validate the full-resolution input used by native still processing."""
    path=Path(path)
    with path.open('rb') as stream:header=stream.read(32)
    fields=struct.unpack('<8s6I',header) if len(header)==32 else None
    if (not fields or fields[0]!=b'NZ9RAW1\0' or
            fields[1:3] not in ((8256,5504),(8280,5520)) or fields[3:]!=(14,0,0,16383)):
        raise ValueError('Full capture requires 8256x5504 or 8280x5520, 14-bit RGGB NZ9RAW1 input')
    if path.stat().st_size!=32+fields[1]*fields[2]*2:
        raise ValueError('Full sensor input is truncated or has trailing bytes')
    return fields[1:3]


def card_photos(card):
    """Read an idle guest's persisted card without constructing camera files."""
    from inspect_virtual_exfat import catalog
    card=Path(card)
    with card.open('rb') as stream:mbr=stream.read(512)
    if len(mbr)!=512 or mbr[510:]!=b'\x55\xaa' or mbr[450]!=7:
        raise ValueError('Expected MBR exFAT card')
    first,sectors=struct.unpack_from('<II',mbr,454)
    offset,length=first*512,sectors*512
    rows=catalog(card,offset=offset,length=length)['files']
    photos={r['path']:r for r in rows if not r['directory'] and r['path'].upper().endswith(('.NEF','.JPG','.JPEG'))}
    return photos,offset,length


def export_new_photos(card, before, output):
    """Export newly closed, initialized camera files after capture recovery."""
    from extract_virtual_exfat import extract
    photos,offset,length=card_photos(card)
    created=[r for name,r in photos.items() if name not in before]
    if not created:raise ValueError('Capture recovered but no new photograph exists on the card')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result=[]
    for row in created:
        receipt=extract(card,row['path'],output/Path(row['path']).name,offset=offset,length=length)
        with Path(receipt['output']).open('rb') as stream:head=stream.read(4)
        if not (head[:2]==b'\xff\xd8' or head in (b'II*\0',b'MM\0*')):
            raise ValueError('Saved photograph has no TIFF/NEF or JPEG signature')
        result.append(dict(name=row['path'],bytes=receipt['bytes'],sha256=receipt['sha256'],
            cache=str(Path(receipt['output']).resolve())))
    return result


def validate(binary=None):
    manifest = json.loads((PUBLIC / '.local/build-manifest.json').read_text())
    if binary is not None and Path(binary).resolve() != Path(manifest['binary']).resolve():
        raise ValueError('Capture requires the binary in this checkout\'s build manifest')
    if sha(Path(manifest['binary'])) != manifest['binary_sha256']:
        raise ValueError('Binary differs from its build receipt; rebuild')
    for name, digest in manifest['sources'].items():
        if sha(PUBLIC / name) != digest:
            raise ValueError('Source changed since build: ' + name)
    return manifest


def archive(g, manifest):
    (g.out / 'public-build-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    compiled = Path(manifest['binary']).parents[1] / 'qemu-10.2.4/hw/arm'
    for name, digest in manifest.get('compiled_sources', {}).items():
        source = compiled / name
        if sha(source) != digest:
            raise ValueError('Compiled source changed since build: ' + name)
        (g.out / name).write_bytes(source.read_bytes())
    g.data['public_build'] = manifest


def output_path(path):
    path = Path(path).resolve()
    if path.is_relative_to(PUBLIC) and not path.is_relative_to(PUBLIC / '.local'):
        raise ValueError('Outputs within the repository must be under ignored .local/')
    if path.exists():
        raise ValueError('Use a fresh output directory; existing evidence is preserved')
    return path
