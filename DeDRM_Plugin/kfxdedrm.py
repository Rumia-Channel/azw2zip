#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Engine to remove drm from Kindle KFX ebooks

#  2.0   - Python 3 for calibre 5.0
#  2.1   - Some fixes for debugging
#  2.1.1 - Whitespace!


import os, sys
import shutil
import traceback
import zipfile

from io import BytesIO


#@@CALIBRE_COMPAT_CODE@@


from ion import DrmIon, DrmIonVoucher, SKeyList

try:
    from kbdr import DR
    KBDR_AVAILABLE = True
except ImportError:
    KBDR_AVAILABLE = False

__license__ = 'GPL v3'
__version__ = '2.1'


class KFXZipBook:
    def __init__(self, infile,skeyfile=None):
        self.infile = infile
        if skeyfile is not None:
          self.skeylist=SKeyList(skeyfile)
        else:
          self.skeylist=None
        self.voucher = None
        self.decrypted = {}
        self.is_new_format = False

    def getPIDMetaInfo(self):
        return (None, None)
    
    def check_new_format(self):
        """Check if this is a new-format KFX-ZIP (KBDR style)"""
        try:
            with zipfile.ZipFile(self.infile, 'r') as zf:
                # New format has metadata.json with contentKeys
                if 'metadata.json' in zf.namelist():
                    import json
                    metadata = json.loads(zf.read('metadata.json'))
                    if 'contentKeys' in metadata:
                        return True
        except:
            pass
        return False

    def processBook(self, totalpids):
        # Check if this is new format first
        if KBDR_AVAILABLE and self.check_new_format():
            self.is_new_format = True
            return self.processNewFormat(totalpids)
        
        # Original DRMION format processing
        with zipfile.ZipFile(self.infile, 'r') as zf:
            for filename in zf.namelist():
                with zf.open(filename) as fh:
                    data = fh.read(8)
                    if data != b'\xeaDRMION\xee':
                        continue
                    data += fh.read()
                    if self.voucher is None:
                        self.decrypt_voucher(totalpids)
                    print("Decrypting KFX DRMION: {0}".format(filename))
                    outfile = BytesIO()
                    DrmIon(BytesIO(data[8:-8]), lambda name: self.voucher,self.skeylist).parse(outfile)
                    self.decrypted[filename] = outfile.getvalue()

        if not self.decrypted:
            print("The .kfx-zip archive does not contain an encrypted DRMION file")
    
    def processNewFormat(self, totalpids):
        """Process new-format KFX-ZIP using KBDR"""
        import json
        import base64
        print("Detected new-format KFX-ZIP with contentKeys")
        
        with zipfile.ZipFile(self.infile, 'r') as zf:
            if 'metadata.json' not in zf.namelist():
                raise Exception("New-format KFX-ZIP missing metadata.json")
            
            metadata = json.loads(zf.read('metadata.json'))
            content_keys = metadata.get('contentKeys', {})
            
            if not content_keys:
                print("Warning: No contentKeys found in metadata.json")
                return
            
            print(f"Found {len(content_keys)} content keys in metadata")
            
            # Extract deviceId and userId/secret from PIDs
            # PIDs can be:
            # 1. Traditional: deviceId (16/32/40) + userId (0/40)
            # 2. New format: deviceId (hex) + secret (base64)
            success = False
            for pid in totalpids:
                if isinstance(pid, bytes):
                    pid = pid.decode('utf-8')
                
                # Try as new format first (deviceId + base64 secret)
                # Secret from KFXKeyExtractor is base64 encoded
                if '+' in pid or '/' in pid or '=' in pid:
                    # Likely contains base64, split at typical deviceId lengths
                    for dsn_len in [16, 32, 40]:
                        if len(pid) > dsn_len:
                            device_id = pid[:dsn_len]
                            secret_b64 = pid[dsn_len:]
                            
                            try:
                                # Use the base64 secret as userId
                                print(f"Trying KBDR with deviceId={device_id[:8]}... and base64 secret")
                                dr = DR(device_id, secret_b64)
                                
                                # Create temporary output file
                                import tempfile
                                temp_fd, temp_path = tempfile.mkstemp(suffix='.kfx-zip')
                                os.close(temp_fd)
                                
                                try:
                                    if dr.RemoveDrm(self.infile, temp_path, content_keys):
                                        print(f"Successfully decrypted with KBDR (new format)")
                                        # Read decrypted file
                                        with zipfile.ZipFile(temp_path, 'r') as decrypted_zf:
                                            for filename in decrypted_zf.namelist():
                                                self.decrypted[filename] = decrypted_zf.read(filename)
                                        success = True
                                        os.unlink(temp_path)
                                        return
                                finally:
                                    if os.path.exists(temp_path):
                                        os.unlink(temp_path)
                            except Exception as e:
                                print(f"KBDR new format attempt failed: {e}")
                                continue
                
                # Try traditional format (deviceId + userId)
                for dsn_len in [16, 32, 40]:
                    for secret_len in [0, 40]:
                        if len(pid) == dsn_len + secret_len:
                            device_id = pid[:dsn_len]
                            user_id = pid[dsn_len:] if secret_len > 0 else ''
                            
                            try:
                                print(f"Trying KBDR with deviceId length {dsn_len}, userId length {secret_len}")
                                dr = DR(device_id, user_id)
                                
                                # Create temporary output file
                                import tempfile
                                temp_fd, temp_path = tempfile.mkstemp(suffix='.kfx-zip')
                                os.close(temp_fd)
                                
                                try:
                                    if dr.RemoveDrm(self.infile, temp_path, content_keys):
                                        print(f"Successfully decrypted with KBDR (traditional format)")
                                        # Read decrypted file
                                        with zipfile.ZipFile(temp_path, 'r') as decrypted_zf:
                                            for filename in decrypted_zf.namelist():
                                                self.decrypted[filename] = decrypted_zf.read(filename)
                                        success = True
                                        os.unlink(temp_path)
                                        return
                                finally:
                                    if os.path.exists(temp_path):
                                        os.unlink(temp_path)
                            except Exception as e:
                                print(f"KBDR traditional attempt failed: {e}")
                                continue
            
            if not success:
                raise Exception("Failed to decrypt new-format KFX-ZIP with any available keys")

    def decrypt_voucher(self, totalpids):
        with zipfile.ZipFile(self.infile, 'r') as zf:
            for info in zf.infolist():
                with zf.open(info.filename) as fh:
                    data = fh.read(4)
                    if data != b'\xe0\x01\x00\xea':
                        continue

                    data += fh.read()
                    if b'ProtectedData' in data:
                        break   # found DRM voucher
            else:
                #raise Exception("The .kfx-zip archive contains an encrypted DRMION file without a DRM voucher")
                print("The .kfx-zip archive contains an encrypted DRMION file without a DRM voucher. Just in case it is a rare decrypted KFX, we continue")
                self.voucher = None
                return
        print("Decrypting KFX DRM voucher: {0}".format(info.filename))

        import binascii
        for pid in [''] + totalpids:
            # Belt and braces. PIDs should be unicode strings, but just in case...
            if isinstance(pid, bytes):
                pid = pid.decode('utf-8')
            
            # Try standard PID length combinations first
            for dsn_len,secret_len in [(0,0), (16,0), (16,40), (16,128), (32,0), (32,40), (32,128), (40,0), (40,40), (40,128)]:
                if len(pid) == dsn_len + secret_len:
                    dsn = pid[:dsn_len]
                    secret = pid[dsn_len:]
                    break
            else:
                # Non-standard length, try to intelligently split
                if len(pid) >= 72:
                    # Likely 32-char DSN + longer secret
                    dsn = pid[:32]
                    secret = pid[32:]
                elif len(pid) >= 40:
                    # Try 16 or 32 char DSN
                    if len(pid) == 16 + 128:
                        dsn = pid[:16]
                        secret = pid[16:]
                    else:
                        dsn = pid[:32] if len(pid) >= 32 else pid[:16]
                        secret = pid[len(dsn):]
                else:
                    dsn = pid
                    secret = ''
            
            # DrmIonVoucher expects secret as bytes
            # If secret is hex-encoded (even length, only hex chars), try decoding
            secret_bytes = secret
            if secret and len(secret) % 2 == 0:
                try:
                    # Try to decode as hex
                    secret_bytes = binascii.unhexlify(secret)
                except:
                    # Not hex, use as-is
                    secret_bytes = secret

            try:
                voucher = DrmIonVoucher(BytesIO(data), dsn, secret_bytes, self.skeylist)
                voucher.parse()
                voucher.decryptvoucher()
                print(f"Successfully decrypted voucher with DSN length={len(dsn)}, SECRET length={len(secret)}")
                break
            except:
                # Only print traceback for first PID attempt
                if pid == (totalpids[0] if totalpids else ''):
                    traceback.print_exc()
                pass
        else:
            print("Failed to decrypt KFX DRM voucher with any key... Hoping that keylist has a book key. ")
            self.voucher = voucher
            return

        print("KFX DRM voucher successfully decrypted")

        license_type = voucher.getlicensetype()
        if license_type != "Purchase":
            #raise Exception(("This book is licensed as {0}. "
            #        'These tools are intended for use on purchased books.').format(license_type))
            print("Warning: This book is licensed as {0}. "
                    "These tools are intended for use on purchased books. Continuing ...".format(license_type))

        self.voucher = voucher

    def getBookTitle(self):
        return os.path.splitext(os.path.split(self.infile)[1])[0]

    def getBookExtension(self):
        return '.kfx-zip'

    def getBookType(self):
        return 'KFX-ZIP'

    def cleanup(self):
        pass

    def getFile(self, outpath):
        if not self.decrypted:
            shutil.copyfile(self.infile, outpath)
        else:
            if self.is_new_format:
                # For new format, write all decrypted files directly
                with zipfile.ZipFile(outpath, 'w', zipfile.ZIP_DEFLATED) as zof:
                    for filename, content in self.decrypted.items():
                        zof.writestr(filename, content)
            else:
                # Original format: merge with original zip
                with zipfile.ZipFile(self.infile, 'r') as zif:
                    with zipfile.ZipFile(outpath, 'w') as zof:
                        for info in zif.infolist():
                            zof.writestr(info, self.decrypted.get(info.filename, zif.read(info.filename)))


class KFXStandaloneBook:
    def __init__(self, infile, voucherfile, skeyfile=None):
        self.infile = infile
        self.voucherfile = voucherfile
        if skeyfile is not None:
            self.skeylist = SKeyList(skeyfile)
        else:
            self.skeylist = None
        self.voucher = None
        self.decrypted = {}

    def getPIDMetaInfo(self):
        return (None, None)

    def processBook(self, totalpids):
        # Read DRMION file
        with open(self.infile, 'rb') as fh:
            data = fh.read(8)
            if data != b'\xeaDRMION\xee':
                print("Warning: File does not start with DRMION magic bytes")
            data += fh.read()
        
        # Decrypt voucher first
        if self.voucher is None:
            self.decrypt_voucher(totalpids)
        
        print("Decrypting standalone KFX DRMION: {0}".format(os.path.basename(self.infile)))
        outfile = BytesIO()
        DrmIon(BytesIO(data[8:-8]), lambda name: self.voucher, self.skeylist).parse(outfile)
        self.decrypted[os.path.basename(self.infile)] = outfile.getvalue()

    def decrypt_voucher(self, totalpids):
        # Read voucher file
        with open(self.voucherfile, 'rb') as fh:
            data = fh.read(4)
            if data != b'\xe0\x01\x00\xea':
                print("Warning: Voucher file does not start with expected magic bytes")
            data += fh.read()
        
        if b'ProtectedData' not in data:
            print("Warning: Voucher file does not contain ProtectedData")
            self.voucher = None
            return
        
        print("Decrypting KFX DRM voucher: {0}".format(os.path.basename(self.voucherfile)))
        
        import binascii
        for pid in [''] + totalpids:
            if isinstance(pid, bytes):
                pid = pid.decode('utf-8')
            
            # KFXの場合、PIDの構造は:
            # - DSN (16, 32, or 40 chars)
            # - ACCOUNT_SECRET (0, 40, or 128 chars hex-encoded)
            # 可能な組み合わせを試す
            for dsn_len, secret_len in [(0,0), (16,0), (16,40), (16,128), (32,0), (32,40), (32,128), (40,0), (40,40), (40,128)]:
                if len(pid) == dsn_len + secret_len:
                    dsn = pid[:dsn_len]
                    secret = pid[dsn_len:]
                    break
            else:
                # 標準的な組み合わせに一致しない場合、PID全体をテスト
                # 特に80文字以上のPIDの場合
                if len(pid) >= 72:
                    # 最初の32文字をDSN、残りをSECRETとして試す
                    dsn = pid[:32]
                    secret = pid[32:]
                elif len(pid) >= 40:
                    # 最初の部分をDSN、残りをSECRETとして試す
                    if len(pid) >= 144:  # 16 + 128
                        dsn = pid[:16]
                        secret = pid[16:]
                    else:
                        dsn = pid[:32] if len(pid) >= 32 else pid
                        secret = pid[32:] if len(pid) > 32 else ''
                else:
                    dsn = pid
                    secret = ''
            
            # DrmIonVoucher expects secret as bytes
            # If secret is hex-encoded (even length, only hex chars), try decoding
            secret_bytes = secret
            if secret and len(secret) % 2 == 0:
                try:
                    # Try to decode as hex
                    secret_bytes = binascii.unhexlify(secret)
                except:
                    # Not hex, use as-is
                    secret_bytes = secret
            
            try:
                voucher = DrmIonVoucher(BytesIO(data), dsn, secret_bytes, self.skeylist)
                voucher.parse()
                voucher.decryptvoucher()
                print("Successfully decrypted voucher with DSN length={}, SECRET length={}".format(len(dsn), len(secret)))
                break
            except Exception as e:
                # 詳細なエラー情報は最初の試行のみ表示
                if pid == totalpids[0] if totalpids else '':
                    import traceback
                    traceback.print_exc()
                pass
        else:
            print("Failed to decrypt KFX DRM voucher with any key")
            raise Exception("Failed to decrypt voucher")
        
        print("KFX DRM voucher successfully decrypted")
        
        license_type = voucher.getlicensetype()
        if license_type != "Purchase":
            print("Warning: This book is licensed as {0}. These tools are intended for use on purchased books. Continuing ...".format(license_type))
        
        self.voucher = voucher

    def getBookTitle(self):
        return os.path.splitext(os.path.split(self.infile)[1])[0]

    def getBookExtension(self):
        return '.azw'

    def getBookType(self):
        return 'KFX'

    def cleanup(self):
        pass

    def getFile(self, outpath):
        if not self.decrypted:
            shutil.copyfile(self.infile, outpath)
        else:
            # Write decrypted DRMION file
            drmion_data = self.decrypted.get(os.path.basename(self.infile), b'')
            with open(outpath, 'wb') as f:
                f.write(b'\xeaDRMION\xee')
                f.write(drmion_data)
                f.write(b'\xe0\x01\x00\xea')
