import json
import os
import posixpath
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TITLE = 'MOBI6 & Images'
AUTHOR = 'Regression Author'
SOURCE_COMMAND = (
    'import sys; sys.path.insert(0, sys.argv.pop(1)); '
    'import azw2zip; sys.exit(azw2zip.main(sys.argv[1:]))'
)
NS = {
    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
}


def png(color):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(color) * 2) * 2))
        + chunk(b'IEND', b'')
    )


def encrypt_pc1(key, data):
    command = (
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'from alfcrypto import Pukall_Cipher; '
        'sys.stdout.buffer.write(Pukall_Cipher().PC1(bytes.fromhex(sys.argv[2]), sys.stdin.buffer.read(), False))'
    )
    return subprocess.run(
        [sys.executable, '-c', command, str(ROOT / 'DeDRM_Plugin'), key.hex()],
        input=data, capture_output=True, check=True, timeout=30,
    ).stdout


def make_mobi(encrypted=False):
    images = [png((255, 0, 0)), png((0, 255, 0)), png((0, 0, 255))]
    html = b'<html><head><title>MOBI6</title></head><body><p>Original story text.</p><img recindex="00001"/><img recindex="00002"/><img recindex="00003"/></body></html>'
    title = TITLE.encode('utf-8')
    entries = [
        (100, AUTHOR.encode('utf-8')), (101, b'Test Publisher'),
        (503, title), (106, b'2026-01-01'), (201, struct.pack('>I', 1)),
    ]
    exth_data = b''.join(struct.pack('>II', kind, len(value) + 8) + value for kind, value in entries)
    exth = b'EXTH' + struct.pack('>II', len(exth_data) + 12, len(entries)) + exth_data
    exth += b'\0' * (-len(exth) % 4)
    header = bytearray(16 + 0xe8)
    struct.pack_into('>HHIHHHH', header, 0, 1, 0, len(html), 1, 4096, 2 if encrypted else 0, 0)
    header[0x10:0x14] = b'MOBI'
    fields = {
        0x14: 0xe8, 0x18: 2, 0x1c: 65001, 0x20: 12345, 0x24: 6,
        0x28: 0xffffffff, 0x2c: 0xffffffff, 0x30: 0xffffffff, 0x34: 0xffffffff,
        0x50: 2, 0x54: len(header) + len(exth), 0x58: len(title), 0x5c: 1033,
        0x68: 6, 0x6c: 2, 0x70: 0xffffffff, 0x80: 0x40,
        0xa8: 0xffffffff, 0xc8: 0xffffffff, 0xd0: 0xffffffff,
        0xe0: 0xffffffff, 0xf4: 0xffffffff,
    }
    for offset, value in fields.items():
        struct.pack_into('>I', header, offset, value)
    header += exth + title
    if encrypted:
        book_key = bytes(range(16))
        default_key = bytes.fromhex('723833b0b4f2e3cadf0901d6e2e03f96')
        verification = 0x12345678
        cookie = encrypt_pc1(default_key, struct.pack('>LL16sLL', verification, 1, book_key, 0, 0))
        drm = struct.pack('>LLLBxxx32s', verification, 48, 1, sum(default_key) & 255, cookie)
        struct.pack_into('>LLLL', header, 0xa8, len(header), 1, len(drm), 0)
        header += drm
        html = encrypt_pc1(book_key, html)
    records = [bytes(header), html] + images
    book = bytearray(78)
    book[:5] = b'MOBI6'
    book[60:68] = b'BOOKMOBI'
    struct.pack_into('>I', book, 68, len(records) + 1)
    struct.pack_into('>H', book, 76, len(records))
    offset = 78 + len(records) * 8 + 2
    for index, record in enumerate(records):
        book += struct.pack('>II', offset, index * 2)
        offset += len(record)
    book += b'\0\0' + b''.join(records)
    return bytes(book), [images[1], images[0], images[2]]


def prepare_case(directory, encrypted=False, extension='.azw'):
    directory = Path(directory)
    inputs = directory / 'input'
    inputs.mkdir()
    book, images = make_mobi(encrypted)
    (inputs / ('B000000001_EBOK' + extension)).write_bytes(book)
    keys = directory / 'keys'
    keys.mkdir()
    (keys / 'fixture.k4i').write_text('{}', encoding='utf-8')
    config = {
        'default': [{'k4i_dir': str(keys)}],
        'rename': [{'authors': '.+', 'title': '.+', 'directory': '', 'template': '[{authors}] {title}'}],
    }
    (directory / 'azw2zip.json').write_text(json.dumps(config), encoding='utf-8')
    return images


class MobiConversionTests(unittest.TestCase):
    def assert_artifacts(self, directory, options, images):
        outputs = Path(directory) / 'output'
        extensions = {'.zip' for option in options if option == '-z'} | {'.epub' for option in options if option == '-e'}
        self.assertEqual({path.suffix for path in outputs.iterdir()}, extensions)
        for extension in extensions:
            path = outputs / ('[' + AUTHOR + '] ' + TITLE + extension)
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                if extension == '.zip':
                    self.assertEqual({archive.read(name) for name in archive.namelist()}, set(images))
                    self.assertTrue(all(name.endswith('.png') for name in archive.namelist()))
                    continue
                self.assertEqual(archive.infolist()[0].filename, 'mimetype')
                self.assertEqual(archive.getinfo('mimetype').compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
                container = ET.fromstring(archive.read('META-INF/container.xml'))
                opf_path = container.find('.//container:rootfile', NS).get('full-path')
                package = ET.fromstring(archive.read(opf_path))
                self.assertEqual(package.findtext('opf:metadata/dc:title', namespaces=NS), TITLE)
                self.assertEqual(package.findtext('opf:metadata/dc:creator', namespaces=NS), AUTHOR)
                manifest = {item.get('id'): item for item in package.findall('opf:manifest/opf:item', NS)}
                for item in manifest.values():
                    self.assertIn(posixpath.join(posixpath.dirname(opf_path), item.get('href')), archive.namelist())
                spine_hrefs = []
                actual_images = []
                for itemref in package.findall('opf:spine/opf:itemref', NS):
                    item = manifest[itemref.get('idref')]
                    self.assertEqual(item.get('media-type'), 'application/xhtml+xml')
                    spine_hrefs.append(item.get('href'))
                    page_path = posixpath.join(posixpath.dirname(opf_path), item.get('href'))
                    page = ET.fromstring(archive.read(page_path))
                    image_elements = page.findall('.//xhtml:img', NS)
                    self.assertEqual(len(image_elements), 1)
                    image_path = posixpath.normpath(posixpath.join(posixpath.dirname(page_path), image_elements[0].get('src')))
                    actual_images.append(archive.read(image_path))
                    self.assertNotIn(b'Original story text.', archive.read(page_path))
                self.assertEqual(actual_images, images)
                ncx_item = manifest[package.find('opf:spine', NS).get('toc')]
                ncx_path = posixpath.join(posixpath.dirname(opf_path), ncx_item.get('href'))
                ncx = ET.fromstring(archive.read(ncx_path))
                self.assertEqual([node.get('src') for node in ncx.findall('.//ncx:content', NS)], spine_hrefs)
        rows = [json.loads(line) for line in (Path(directory) / 'result.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'success')
        self.assertIsNone(rows[0]['error'])
        self.assertEqual(rows[0]['title'], TITLE)
        self.assertEqual(rows[0]['authors'], [AUTHOR])

    def run_case(self, encrypted, options, extension='.azw'):
        with tempfile.TemporaryDirectory(prefix='azw2zip-mobi-') as directory:
            directory = Path(directory)
            images = prepare_case(directory, encrypted, extension)
            result = subprocess.run(
                [sys.executable, '-c', SOURCE_COMMAND, str(ROOT), str(directory / 'azw2zip.py')]
                + list(options) + ['-j', str(directory / 'result.jsonl'), str(directory / 'input'), str(directory / 'output')],
                cwd=directory, env=dict(
                    os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='0',
                    PYTHONCOERCECLOCALE='0', LC_ALL='C',
                ),
                capture_output=True, text=True, encoding='utf-8', timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_artifacts(directory, options, images)

    def test_mobi6_output_formats_with_and_without_drm(self):
        for encrypted in (False, True):
            for options in (('-z',), ('-e',), ('-z', '-e')):
                with self.subTest(encrypted=encrypted, options=options):
                    self.run_case(encrypted, options)

    def test_unencrypted_azw3_keeps_metadata_after_opf_generation(self):
        self.run_case(False, ('-z', '-e'), '.azw3')


if __name__ == '__main__':
    unittest.main()
