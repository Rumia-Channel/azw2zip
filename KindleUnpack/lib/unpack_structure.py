#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab

from __future__ import unicode_literals, division, absolute_import, print_function

from compatibility_utils import text_type

import unipath
from unipath import pathof

DUMP = False
""" Set to True to dump all possible information. """

import os
import shutil

import re
# note: re requites the pattern to be the exact same type as the data to be searched in python3
# but u"" is not allowed for the pattern itself only b""

import zipfile
import binascii
import mimetypes
import uuid
import xml.etree.ElementTree as ET
from mobi_utils import mangle_fonts

class unpackException(Exception):
    pass

class ZipInfo(zipfile.ZipInfo):

    def __init__(self, *args, **kwargs):
        if 'compress_type' in kwargs:
            compress_type = kwargs.pop('compress_type')
        super(ZipInfo, self).__init__(*args, **kwargs)
        self.compress_type = compress_type

class fileNames:

    def __init__(self, infile, outdir):
        self.infile = infile
        self.outdir = outdir
        if not unipath.exists(self.outdir):
            unipath.mkdir(self.outdir)
        self.mobi7dir = os.path.join(self.outdir,'mobi7')
        if not unipath.exists(self.mobi7dir):
            unipath.mkdir(self.mobi7dir)
        self.imgdir = os.path.join(self.mobi7dir, 'Images')
        if not unipath.exists(self.imgdir):
            unipath.mkdir(self.imgdir)
        self.hdimgdir = os.path.join(self.outdir,'HDImages')
        if not unipath.exists(self.hdimgdir):
            unipath.mkdir(self.hdimgdir)
        # azw2zip用のHDimages
        self.HDimages = os.path.join(self.outdir,'azw6_images')
        self.outbase = os.path.join(self.outdir, os.path.splitext(os.path.split(infile)[1])[0])

    def getInputFileBasename(self):
        return os.path.splitext(os.path.basename(self.infile))[0]

    def makeK8Struct(self):
        self.k8dir = os.path.join(self.outdir,'mobi8')
        if not unipath.exists(self.k8dir):
            unipath.mkdir(self.k8dir)
        self.k8metainf = os.path.join(self.k8dir,'META-INF')
        if not unipath.exists(self.k8metainf):
            unipath.mkdir(self.k8metainf)
        self.k8oebps = os.path.join(self.k8dir,'OEBPS')
        if not unipath.exists(self.k8oebps):
            unipath.mkdir(self.k8oebps)
        self.k8images = os.path.join(self.k8oebps,'Images')
        if not unipath.exists(self.k8images):
            unipath.mkdir(self.k8images)
        self.k8fonts = os.path.join(self.k8oebps,'Fonts')
        if not unipath.exists(self.k8fonts):
            unipath.mkdir(self.k8fonts)
        self.k8styles = os.path.join(self.k8oebps,'Styles')
        if not unipath.exists(self.k8styles):
            unipath.mkdir(self.k8styles)
        self.k8text = os.path.join(self.k8oebps,'Text')
        if not unipath.exists(self.k8text):
            unipath.mkdir(self.k8text)
        # azw2zip用のHDimages
        self.HDimages = os.path.join(self.outdir,'azw6_images')

    # recursive zip creation support routine
    def zipUpDir(self, myzip, tdir, localname, compress_type=zipfile.ZIP_DEFLATED):
        currentdir = tdir
        if localname != "":
            currentdir = os.path.join(currentdir,localname)
        list = unipath.listdir(currentdir)
        for file in list:
            afilename = file
            localfilePath = os.path.join(localname, afilename)
            realfilePath = os.path.join(currentdir,file)
            if unipath.isfile(realfilePath):
                myzip.write(pathof(realfilePath), pathof(localfilePath), compress_type)
            elif unipath.isdir(realfilePath):
                self.zipUpDir(myzip, tdir, localfilePath, compress_type)

    def makeEPUB(self, usedmap, obfuscate_data, uid):
        bname = os.path.join(self.k8dir, self.getInputFileBasename() + '.epub')
        # Create an encryption key for Adobe font obfuscation
        # based on the epub's uid
        if isinstance(uid,text_type):
            uid = uid.encode('ascii')
        if obfuscate_data:
            key = re.sub(br'[^a-fA-F0-9]', b'', uid)
            key = binascii.unhexlify((key + key)[:32])

        # copy over all images and fonts that are actually used in the ebook
        # and remove all font files from mobi7 since not supported
        imgnames = unipath.listdir(self.imgdir)
        for name in imgnames:
            if usedmap.get(name,'not used') == 'used':
                filein = os.path.join(self.imgdir,name)
                if name.endswith(".ttf"):
                    fileout = os.path.join(self.k8fonts,name)
                elif name.endswith(".otf"):
                    fileout = os.path.join(self.k8fonts,name)
                elif name.endswith(".failed"):
                    fileout = os.path.join(self.k8fonts,name)
                else:
                    fileout = os.path.join(self.k8images,name)
                data = b''
                with open(pathof(filein),'rb') as f:
                    data = f.read()
                if obfuscate_data:
                    if name in obfuscate_data:
                        data = mangle_fonts(key, data)
                open(pathof(fileout),'wb').write(data)
                if name.endswith(".ttf") or name.endswith(".otf"):
                    os.remove(pathof(filein))

        # opf file name hard coded to "content.opf"
        container = '<?xml version="1.0" encoding="UTF-8"?>\n'
        container += '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        container += '    <rootfiles>\n'
        container += '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        container += '    </rootfiles>\n</container>\n'
        fileout = os.path.join(self.k8metainf,'container.xml')
        with open(pathof(fileout),'wb') as f:
            f.write(container.encode('utf-8'))

        if obfuscate_data:
            encryption = '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" \
xmlns:enc="http://www.w3.org/2001/04/xmlenc#" xmlns:deenc="http://ns.adobe.com/digitaleditions/enc">\n'
            for font in obfuscate_data:
                encryption += '  <enc:EncryptedData>\n'
                encryption += '    <enc:EncryptionMethod Algorithm="http://ns.adobe.com/pdf/enc#RC"/>\n'
                encryption += '    <enc:CipherData>\n'
                encryption += '      <enc:CipherReference URI="OEBPS/Fonts/' + font + '"/>\n'
                encryption += '    </enc:CipherData>\n'
                encryption += '  </enc:EncryptedData>\n'
            encryption += '</encryption>\n'
            fileout = os.path.join(self.k8metainf,'encryption.xml')
            with open(pathof(fileout),'wb') as f:
                f.write(encryption.encode('utf-8'))

        # ready to build epub
        self.outzip = zipfile.ZipFile(pathof(bname), 'w')

        # add the mimetype file uncompressed
        mimetype = b'application/epub+zip'
        fileout = os.path.join(self.k8dir,'mimetype')
        with open(pathof(fileout),'wb') as f:
            f.write(mimetype)
        nzinfo = ZipInfo('mimetype', compress_type=zipfile.ZIP_STORED)
        nzinfo.external_attr = 0o600 << 16 # make this a normal file
        self.outzip.writestr(nzinfo, mimetype)
        # HD画像取り込み（azw2zip用）
        if hasattr(self, 'HDimages'):
            replaceHDimages(self.HDimages, self.k8images, None)
        
        self.zipUpDir(self.outzip,self.k8dir,'META-INF')
        self.zipUpDir(self.outzip,self.k8dir,'OEBPS')
        self.outzip.close()

    def makeMobi7EPUB(self, metadata, rscnames):
        cover_offset = int(metadata.get('CoverOffset', ['-1'])[0])
        cover_name = rscnames[cover_offset] if 0 <= cover_offset < len(rscnames) else None
        images = []
        for name in rscnames:
            if name is None:
                continue
            media = mimetypes.guess_type(name)[0]
            if media and media.startswith('image/'):
                image = (name, media)
                if name == cover_name:
                    images.insert(0, image)
                else:
                    images.append(image)
        if not images:
            raise unpackException('No images available for MOBI EPUB output')
        self.makeK8Struct()
        uid = 'urn:uuid:' + str(uuid.uuid4())
        title = metadata['Title'][0]
        language = metadata['Language'][0]

        package = ET.Element('package', {
            'xmlns': 'http://www.idpf.org/2007/opf', 'version': '2.0', 'unique-identifier': 'uid',
        })
        meta = ET.SubElement(package, 'metadata', {'xmlns:dc': 'http://purl.org/dc/elements/1.1/'})
        ET.SubElement(meta, 'dc:identifier', {'id': 'uid'}).text = uid
        ET.SubElement(meta, 'dc:title').text = title
        ET.SubElement(meta, 'dc:language').text = language
        for key, tag in [('Creator', 'creator'), ('Publisher', 'publisher'), ('Published', 'date')]:
            for value in metadata.get(key, []):
                ET.SubElement(meta, 'dc:' + tag).text = value
        manifest = ET.SubElement(package, 'manifest')
        ET.SubElement(manifest, 'item', {
            'id': 'ncx', 'href': 'toc.ncx', 'media-type': 'application/x-dtbncx+xml',
        })
        spine = ET.SubElement(package, 'spine', {'toc': 'ncx'})

        ncx = ET.Element('ncx', {'xmlns': 'http://www.daisy.org/z3986/2005/ncx/', 'version': '2005-1'})
        head = ET.SubElement(ncx, 'head')
        for name, content in [('dtb:uid', uid), ('dtb:depth', '1'), ('dtb:totalPageCount', '0'), ('dtb:maxPageNumber', '0')]:
            ET.SubElement(head, 'meta', {'name': name, 'content': content})
        ET.SubElement(ET.SubElement(ncx, 'docTitle'), 'text').text = title
        nav_map = ET.SubElement(ncx, 'navMap')
        usedmap = {}
        for number, (name, media) in enumerate(images, 1):
            page_id = 'page%05d' % number
            image_id = 'image%05d' % number
            page_href = 'Text/' + page_id + '.xhtml'
            ET.SubElement(manifest, 'item', {
                'id': image_id, 'href': 'Images/' + name, 'media-type': media,
            })
            ET.SubElement(manifest, 'item', {
                'id': page_id, 'href': page_href, 'media-type': 'application/xhtml+xml',
            })
            ET.SubElement(spine, 'itemref', {'idref': page_id})
            if name == cover_name:
                ET.SubElement(meta, 'meta', {'name': 'cover', 'content': image_id})
            point = ET.SubElement(nav_map, 'navPoint', {'id': page_id, 'playOrder': str(number)})
            ET.SubElement(ET.SubElement(point, 'navLabel'), 'text').text = str(number)
            ET.SubElement(point, 'content', {'src': page_href})

            page = ET.Element('html', {'xmlns': 'http://www.w3.org/1999/xhtml', 'xml:lang': language})
            page_head = ET.SubElement(page, 'head')
            ET.SubElement(page_head, 'title').text = title
            ET.SubElement(page_head, 'style', {'type': 'text/css'}).text = 'body { margin: 0; } img { max-width: 100%; height: auto; }'
            ET.SubElement(ET.SubElement(page, 'body'), 'img', {'src': '../Images/' + name, 'alt': str(number)})
            ET.ElementTree(page).write(pathof(os.path.join(self.k8text, page_id + '.xhtml')), encoding='utf-8', xml_declaration=True)
            usedmap[name] = 'used'

        ET.ElementTree(package).write(pathof(os.path.join(self.k8oebps, 'content.opf')), encoding='utf-8', xml_declaration=True)
        ET.ElementTree(ncx).write(pathof(os.path.join(self.k8oebps, 'toc.ncx')), encoding='utf-8', xml_declaration=True)
        self.makeEPUB(usedmap, {}, uid)

    def makeZipStruct(self):
        self.k8dir = os.path.join(self.outdir,'mobi8')
        self.k8oebps = os.path.join(self.k8dir,'OEBPS')
        self.k8images = os.path.join(self.k8oebps,'Images')
        self.HDimages = os.path.join(self.outdir,'azw6_images')
        self.zipdir = os.path.join(self.outdir,'zip')
        if not unipath.exists(self.zipdir):
            unipath.mkdir(self.zipdir)

    def makeZip(self, fname, cover_offset, zip_compress = False):
        bname = os.path.normpath(os.path.join(self.outdir, '..', fname + '.zip'))
        if not unipath.exists(os.path.dirname(bname)):
            unipath.makedirs(os.path.dirname(bname))

        # ready to build zip
        self.outzip = zipfile.ZipFile(pathof(bname), 'w')

        if unipath.exists(self.k8images):
            shutil.copytree(self.k8images, self.zipdir, dirs_exist_ok=True)
        else:
            shutil.copytree(self.imgdir, self.zipdir, dirs_exist_ok=True)

        # HDイメージ差し替え
        replaceHDimages(self.hdimgdir, self.zipdir, cover_offset)
        
        # zip作成
        if zip_compress:
            self.zipUpDir(self.outzip, self.zipdir, '')
        else:
            self.zipUpDir(self.outzip, self.zipdir, '', zipfile.ZIP_STORED)
        self.outzip.close()

    def makeImages(self, fname, cover_offset):
        bname = os.path.normpath(os.path.join(self.outdir, '..', fname))

        if not unipath.exists(bname):
            unipath.makedirs(bname)

        # ready to build images
        if unipath.exists(self.k8images):
            shutil.copytree(self.k8images, bname, dirs_exist_ok=True)
        else:
            shutil.copytree(self.imgdir, bname, dirs_exist_ok=True)

        # HDイメージ差し替え
        replaceHDimages(self.hdimgdir, bname, cover_offset)


def replaceHDimages(src_dir, dest_dir, cover_offset):
    # HDイメージ差し替え
    if unipath.exists(src_dir):
        shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)

        # HDカバー画像をリネーム
        if cover_offset is not None:
            imgtype = 'jpg'
            imgname = "image%05d.%s" % (cover_offset+1, imgtype)
            imgpath = os.path.join(dest_dir, imgname)
            cvrname = "cover%05d.%s" % (cover_offset+1, imgtype)
            cvrpath = os.path.join(dest_dir, cvrname)
            if unipath.exists(imgpath):
                if unipath.exists(cvrpath):
                    os.remove(cvrpath)
                os.rename(imgpath, cvrpath)
