#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ion.py: Decrypt Kindle KFX files.

Revision history:
  Pascal implementation by lulzkabulz.
  BinaryIon.pas + DrmIon.pas + IonSymbols.pas
  1.0   - Python translation by apprenticenaomi.
  1.1   - DeDRM integration by anon.
  1.2   - Added pylzma import fallback
  1.3   - Fixed lzma support for calibre 4.6+
  2.0   - VoucherEnvelope v2/v3 support by apprenticesakuya.
  3.0   - Added Python 3 compatibility for calibre 5.0

Copyright © 2013-2020 Apprentice Harper et al.
"""

import collections
import hashlib
import hmac
import os
import os.path
import struct

from io import BytesIO

__license__ = 'GPL v3'
__version__ = '3.0'

#@@CALIBRE_COMPAT_CODE@@


try:
    from Cryptodome.Cipher import AES
    from Cryptodome.Util.py3compat import bchr
except ImportError:
    from Crypto.Cipher import AES
    from Crypto.Util.py3compat import bchr

try:
    # lzma library from calibre 4.6.0 or later
    import calibre_lzma.lzma1 as calibre_lzma
except ImportError:
    calibre_lzma = None
    # lzma library from calibre 2.35.0 or later
    try:
        import lzma.lzma1 as calibre_lzma
    except ImportError:
        calibre_lzma = None
        try:
            import lzma
        except ImportError:
            # Need pip backports.lzma on Python <3.3
            try:
                from backports import lzma
            except ImportError:
                # Windows-friendly choice: pylzma wheels
                import pylzma as lzma
try:
 from kfxtables import *
except:
 from kfxtables import *

TID_NULL = 0
TID_BOOLEAN = 1
TID_POSINT = 2
TID_NEGINT = 3
TID_FLOAT = 4
TID_DECIMAL = 5
TID_TIMESTAMP = 6
TID_SYMBOL = 7
TID_STRING = 8
TID_CLOB = 9
TID_BLOB = 0xA
TID_LIST = 0xB
TID_SEXP = 0xC
TID_STRUCT = 0xD
TID_TYPEDECL = 0xE
TID_UNUSED = 0xF


SID_UNKNOWN = -1
SID_ION = 1
SID_ION_1_0 = 2
SID_ION_SYMBOL_TABLE = 3
SID_NAME = 4
SID_VERSION = 5
SID_IMPORTS = 6
SID_SYMBOLS = 7
SID_MAX_ID = 8
SID_ION_SHARED_SYMBOL_TABLE = 9
SID_ION_1_0_MAX = 10


LEN_IS_VAR_LEN = 0xE
LEN_IS_NULL = 0xF


VERSION_MARKER = [b"\x01", b"\x00", b"\xEA"]


# asserts must always raise exceptions for proper functioning
def _assert(test, msg="Exception"):
    if not test:
        raise Exception(msg)


class SystemSymbols(object):
    ION = '$ion'
    ION_1_0 = '$ion_1_0'
    ION_SYMBOL_TABLE = '$ion_symbol_table'
    NAME = 'name'
    VERSION = 'version'
    IMPORTS = 'imports'
    SYMBOLS = 'symbols'
    MAX_ID = 'max_id'
    ION_SHARED_SYMBOL_TABLE = '$ion_shared_symbol_table'


class IonCatalogItem(object):
    name = ""
    version = 0
    symnames = []

    def __init__(self, name, version, symnames):
        self.name = name
        self.version = version
        self.symnames = symnames


class SymbolToken(object):
    text = ""
    sid = 0

    def __init__(self, text, sid):
        if text == "" and sid == 0:
            raise ValueError("Symbol token must have Text or SID")

        self.text = text
        self.sid = sid


class SymbolTable(object):
    table = None

    def __init__(self):
        self.table = [None] * SID_ION_1_0_MAX
        self.table[SID_ION] = SystemSymbols.ION
        self.table[SID_ION_1_0] = SystemSymbols.ION_1_0
        self.table[SID_ION_SYMBOL_TABLE] = SystemSymbols.ION_SYMBOL_TABLE
        self.table[SID_NAME] = SystemSymbols.NAME
        self.table[SID_VERSION] = SystemSymbols.VERSION
        self.table[SID_IMPORTS] = SystemSymbols.IMPORTS
        self.table[SID_SYMBOLS] = SystemSymbols.SYMBOLS
        self.table[SID_MAX_ID] = SystemSymbols.MAX_ID
        self.table[SID_ION_SHARED_SYMBOL_TABLE] = SystemSymbols.ION_SHARED_SYMBOL_TABLE

    def findbyid(self, sid):
        if sid < 1:
            raise ValueError("Invalid symbol id")

        if sid < len(self.table):
            return self.table[sid]
        else:
            return ""

    def import_(self, table, maxid):
        for i in range(maxid):
            self.table.append(table.symnames[i])

    def importunknown(self, name, maxid):
        for i in range(maxid):
            self.table.append("%s#%d" % (name, i + 1))


class ParserState:
    Invalid,BeforeField,BeforeTID,BeforeValue,AfterValue,EOF = 1,2,3,4,5,6

ContainerRec = collections.namedtuple("ContainerRec", "nextpos, tid, remaining")


class BinaryIonParser(object):
    eof = False
    state = None
    localremaining = 0
    needhasnext = False
    isinstruct = False
    valuetid = 0
    valuefieldid = 0
    parenttid = 0
    valuelen = 0
    valueisnull = False
    valueistrue = False
    value = None
    didimports = False

    def __init__(self, stream):
        self.annotations = []
        self.catalog = []

        self.stream = stream
        self.initpos = stream.tell()
        self.reset()
        self.symbols = SymbolTable()

    def reset(self):
        self.state = ParserState.BeforeTID
        self.needhasnext = True
        self.localremaining = -1
        self.eof = False
        self.isinstruct = False
        self.containerstack = []
        self.stream.seek(self.initpos)

    def addtocatalog(self, name, version, symbols):
        self.catalog.append(IonCatalogItem(name, version, symbols))

    def hasnext(self):
        while self.needhasnext and not self.eof:
            self.hasnextraw()
            if len(self.containerstack) == 0 and not self.valueisnull:
                if self.valuetid == TID_SYMBOL:
                    if self.value == SID_ION_1_0:
                        self.needhasnext = True
                elif self.valuetid == TID_STRUCT:
                    for a in self.annotations:
                        if a == SID_ION_SYMBOL_TABLE:
                            self.parsesymboltable()
                            self.needhasnext = True
                            break
        return not self.eof

    def hasnextraw(self):
        self.clearvalue()
        while self.valuetid == -1 and not self.eof:
            self.needhasnext = False
            if self.state == ParserState.BeforeField:
                _assert(self.valuefieldid == SID_UNKNOWN)

                self.valuefieldid = self.readfieldid()
                if self.valuefieldid != SID_UNKNOWN:
                    self.state = ParserState.BeforeTID
                else:
                    self.eof = True

            elif self.state == ParserState.BeforeTID:
                self.state = ParserState.BeforeValue
                self.valuetid = self.readtypeid()
                if self.valuetid == -1:
                    self.state = ParserState.EOF
                    self.eof = True
                    break

                if self.valuetid == TID_TYPEDECL:
                    if self.valuelen == 0:
                        self.checkversionmarker()
                    else:
                        self.loadannotations()

            elif self.state == ParserState.BeforeValue:
                self.skip(self.valuelen)
                self.state = ParserState.AfterValue

            elif self.state == ParserState.AfterValue:
                if self.isinstruct:
                    self.state = ParserState.BeforeField
                else:
                    self.state = ParserState.BeforeTID

            else:
                _assert(self.state == ParserState.EOF)

    def next(self):
        if self.hasnext():
            self.needhasnext = True
            return self.valuetid
        else:
            return -1

    def push(self, typeid, nextposition, nextremaining):
        self.containerstack.append(ContainerRec(nextpos=nextposition, tid=typeid, remaining=nextremaining))

    def stepin(self):
        _assert(self.valuetid in [TID_STRUCT, TID_LIST, TID_SEXP] and not self.eof,
                "valuetid=%s eof=%s" % (self.valuetid, self.eof))
        _assert((not self.valueisnull or self.state == ParserState.AfterValue) and
               (self.valueisnull or self.state == ParserState.BeforeValue))

        nextrem = self.localremaining
        if nextrem != -1:
            nextrem -= self.valuelen
            if nextrem < 0:
                nextrem = 0
        self.push(self.parenttid, self.stream.tell() + self.valuelen, nextrem)

        self.isinstruct = (self.valuetid == TID_STRUCT)
        if self.isinstruct:
            self.state = ParserState.BeforeField
        else:
            self.state = ParserState.BeforeTID

        self.localremaining = self.valuelen
        self.parenttid = self.valuetid
        self.clearvalue()
        self.needhasnext = True

    def stepout(self):
        rec = self.containerstack.pop()

        self.eof = False
        self.parenttid = rec.tid
        if self.parenttid == TID_STRUCT:
            self.isinstruct = True
            self.state = ParserState.BeforeField
        else:
            self.isinstruct = False
            self.state = ParserState.BeforeTID
        self.needhasnext = True

        self.clearvalue()
        curpos = self.stream.tell()
        if rec.nextpos > curpos:
            self.skip(rec.nextpos - curpos)
        else:
            _assert(rec.nextpos == curpos)

        self.localremaining = rec.remaining

    def read(self, count=1):
        if self.localremaining != -1:
            self.localremaining -= count
            _assert(self.localremaining >= 0)

        result = self.stream.read(count)
        if len(result) == 0:
            raise EOFError()
        return result

    def readfieldid(self):
        if self.localremaining != -1 and self.localremaining < 1:
            return -1

        try:
            return self.readvaruint()
        except EOFError:
            return -1

    def readtypeid(self):
        if self.localremaining != -1:
            if self.localremaining < 1:
                return -1
            self.localremaining -= 1

        b = self.stream.read(1)
        if len(b) < 1:
            return -1
        b = ord(b)
        result = b >> 4
        ln = b & 0xF

        if ln == LEN_IS_VAR_LEN:
            ln = self.readvaruint()
        elif ln == LEN_IS_NULL:
            ln = 0
            self.state = ParserState.AfterValue
        elif result == TID_NULL:
            # Must have LEN_IS_NULL
            _assert(False)
        elif result == TID_BOOLEAN:
            _assert(ln <= 1)
            self.valueistrue = (ln == 1)
            ln = 0
            self.state = ParserState.AfterValue
        elif result == TID_STRUCT:
            if ln == 1:
                ln = self.readvaruint()

        self.valuelen = ln
        return result

    def readvarint(self):
        b = ord(self.read())
        negative = ((b & 0x40) != 0)
        result = (b & 0x3F)

        i = 0
        while (b & 0x80) == 0 and i < 4:
            b = ord(self.read())
            result = (result << 7) | (b & 0x7F)
            i += 1

        _assert(i < 4 or (b & 0x80) != 0, "int overflow")

        if negative:
            return -result
        return result

    def readvaruint(self):
        b = ord(self.read())
        result = (b & 0x7F)

        i = 0
        while (b & 0x80) == 0 and i < 4:
            b = ord(self.read())
            result = (result << 7) | (b & 0x7F)
            i += 1

        _assert(i < 4 or (b & 0x80) != 0, "int overflow")

        return result

    def readdecimal(self):
        if self.valuelen == 0:
            return 0.

        rem = self.localremaining - self.valuelen
        self.localremaining = self.valuelen
        exponent = self.readvarint()

        _assert(self.localremaining > 0, "Only exponent in ReadDecimal")
        _assert(self.localremaining <= 8, "Decimal overflow")

        signed = False
        b = [ord(x) for x in self.read(self.localremaining)]
        if (b[0] & 0x80) != 0:
            b[0] = b[0] & 0x7F
            signed = True

        # Convert variably sized network order integer into 64-bit little endian
        j = 0
        vb = [0] * 8
        for i in range(len(b), -1, -1):
            vb[i] = b[j]
            j += 1

        v = struct.unpack("<Q", b"".join(bchr(x) for x in vb))[0]

        result = v * (10 ** exponent)
        if signed:
            result = -result

        self.localremaining = rem
        return result

    def skip(self, count):
        if self.localremaining != -1:
            self.localremaining -= count
            if self.localremaining < 0:
                raise EOFError()

        self.stream.seek(count, os.SEEK_CUR)

    def parsesymboltable(self):
        self.next() # shouldn't do anything?

        _assert(self.valuetid == TID_STRUCT)

        if self.didimports:
            return

        self.stepin()

        fieldtype = self.next()
        while fieldtype != -1:
            if not self.valueisnull:
                _assert(self.valuefieldid == SID_IMPORTS, "Unsupported symbol table field id")

                if fieldtype == TID_LIST:
                    self.gatherimports()

            fieldtype = self.next()

        self.stepout()
        self.didimports = True

    def gatherimports(self):
        self.stepin()

        t = self.next()
        while t != -1:
            if not self.valueisnull and t == TID_STRUCT:
                self.readimport()

            t = self.next()

        self.stepout()

    def readimport(self):
        version = -1
        maxid = -1
        name = ""

        self.stepin()

        t = self.next()
        while t != -1:
            if not self.valueisnull and self.valuefieldid != SID_UNKNOWN:
                if self.valuefieldid == SID_NAME:
                    name = self.stringvalue()
                elif self.valuefieldid == SID_VERSION:
                    version = self.intvalue()
                elif self.valuefieldid == SID_MAX_ID:
                    maxid = self.intvalue()

            t = self.next()

        self.stepout()

        if name == "" or name == SystemSymbols.ION:
            return

        if version < 1:
            version = 1

        table = self.findcatalogitem(name)
        if maxid < 0:
            _assert(table is not None and version == table.version, "Import %s lacks maxid" % name)
            maxid = len(table.symnames)

        if table is not None:
            self.symbols.import_(table, min(maxid, len(table.symnames)))
            if len(table.symnames) < maxid:
                self.symbols.importunknown(name + "-unknown", maxid - len(table.symnames))
        else:
            self.symbols.importunknown(name, maxid)

    def intvalue(self):
        _assert(self.valuetid in [TID_POSINT, TID_NEGINT], "Not an int")

        self.preparevalue()
        return self.value

    def stringvalue(self):
        _assert(self.valuetid == TID_STRING, "Not a string")

        if self.valueisnull:
            return ""

        self.preparevalue()
        return self.value

    def symbolvalue(self):
        _assert(self.valuetid == TID_SYMBOL, "Not a symbol")

        self.preparevalue()
        result = self.symbols.findbyid(self.value)
        if result == "":
            result = "SYMBOL#%d" % self.value
        return result

    def lobvalue(self):
        _assert(self.valuetid in [TID_CLOB, TID_BLOB], "Not a LOB type: %s" % self.getfieldname())

        if self.valueisnull:
            return None

        result = self.read(self.valuelen)
        self.state = ParserState.AfterValue
        return result

    def decimalvalue(self):
        _assert(self.valuetid == TID_DECIMAL, "Not a decimal")

        self.preparevalue()
        return self.value

    def preparevalue(self):
        if self.value is None:
            self.loadscalarvalue()

    def loadscalarvalue(self):
        if self.valuetid not in [TID_NULL, TID_BOOLEAN, TID_POSINT, TID_NEGINT,
                                 TID_FLOAT, TID_DECIMAL, TID_TIMESTAMP,
                                 TID_SYMBOL, TID_STRING]:
            return

        if self.valueisnull:
            self.value = None
            return

        if self.valuetid == TID_STRING:
            self.value = self.read(self.valuelen).decode("UTF-8")

        elif self.valuetid in (TID_POSINT, TID_NEGINT, TID_SYMBOL):
            if self.valuelen == 0:
                self.value = 0
            else:
                _assert(self.valuelen <= 4, "int too long: %d" % self.valuelen)
                v = 0
                for i in range(self.valuelen - 1, -1, -1):
                    v = (v | (ord(self.read()) << (i * 8)))

                if self.valuetid == TID_NEGINT:
                    self.value = -v
                else:
                    self.value = v

        elif self.valuetid == TID_DECIMAL:
            self.value = self.readdecimal()

        #else:
        #    _assert(False, "Unhandled scalar type %d" % self.valuetid)

        self.state = ParserState.AfterValue

    def clearvalue(self):
        self.valuetid = -1
        self.value = None
        self.valueisnull = False
        self.valuefieldid = SID_UNKNOWN
        self.annotations = []

    def loadannotations(self):
        ln = self.readvaruint()
        maxpos = self.stream.tell() + ln
        while self.stream.tell() < maxpos:
            self.annotations.append(self.readvaruint())
        self.valuetid = self.readtypeid()

    def checkversionmarker(self):
        for i in VERSION_MARKER:
            _assert(self.read() == i, "Unknown version marker")

        self.valuelen = 0
        self.valuetid = TID_SYMBOL
        self.value = SID_ION_1_0
        self.valueisnull = False
        self.valuefieldid = SID_UNKNOWN
        self.state = ParserState.AfterValue

    def findcatalogitem(self, name):
        for result in self.catalog:
            if result.name == name:
                return result

    def forceimport(self, symbols):
        item = IonCatalogItem("Forced", 1, symbols)
        self.symbols.import_(item, len(symbols))

    def getfieldname(self):
        if self.valuefieldid == SID_UNKNOWN:
            return ""
        return self.symbols.findbyid(self.valuefieldid)

    def getfieldnamesymbol(self):
        return SymbolToken(self.getfieldname(), self.valuefieldid)

    def gettypename(self):
        if len(self.annotations) == 0:
            return ""

        return self.symbols.findbyid(self.annotations[0])

    @staticmethod
    def printlob(b):
        if b is None:
            return "null"

        result = ""
        for i in b:
            result += ("%02x " % ord(i))

        if len(result) > 0:
            result = result[:-1]
        return result

    def ionwalk(self, supert, indent, lst):
        while self.hasnext():
            if supert == TID_STRUCT:
                L = self.getfieldname() + ":"
            else:
                L = ""

            t = self.next()
            if t in [TID_STRUCT, TID_LIST]:
                if L != "":
                    lst.append(indent + L)
                L = self.gettypename()
                if L != "":
                    lst.append(indent + L + "::")
                if t == TID_STRUCT:
                    lst.append(indent + "{")
                else:
                    lst.append(indent + "[")

                self.stepin()
                self.ionwalk(t, indent + "  ", lst)
                self.stepout()

                if t == TID_STRUCT:
                    lst.append(indent + "}")
                else:
                    lst.append(indent + "]")

            else:
                if t == TID_STRING:
                    L += ('"%s"' % self.stringvalue())
                elif t in [TID_CLOB, TID_BLOB]:
                    L += ("{%s}" % self.printlob(self.lobvalue()))
                elif t == TID_POSINT:
                    L += str(self.intvalue())
                elif t == TID_SYMBOL:
                    tn = self.gettypename()
                    if tn != "":
                        tn += "::"
                    L += tn + self.symbolvalue()
                elif t == TID_DECIMAL:
                    L += str(self.decimalvalue())
                else:
                    L += ("TID %d" % t)
                lst.append(indent + L)

    def print_(self, lst):
        self.reset()
        self.ionwalk(-1, "", lst)


SYM_NAMES = [ 'com.amazon.drm.Envelope@1.0',
              'com.amazon.drm.EnvelopeMetadata@1.0', 'size', 'page_size',
              'encryption_key', 'encryption_transformation',
              'encryption_voucher', 'signing_key', 'signing_algorithm',
              'signing_voucher', 'com.amazon.drm.EncryptedPage@1.0',
              'cipher_text', 'cipher_iv', 'com.amazon.drm.Signature@1.0',
              'data', 'com.amazon.drm.EnvelopeIndexTable@1.0', 'length',
              'offset', 'algorithm', 'encoded', 'encryption_algorithm',
              'hashing_algorithm', 'expires', 'format', 'id',
              'lock_parameters', 'strategy', 'com.amazon.drm.Key@1.0',
              'com.amazon.drm.KeySet@1.0', 'com.amazon.drm.PIDv3@1.0',
              'com.amazon.drm.PlainTextPage@1.0',
              'com.amazon.drm.PlainText@1.0', 'com.amazon.drm.PrivateKey@1.0',
              'com.amazon.drm.PublicKey@1.0', 'com.amazon.drm.SecretKey@1.0',
              'com.amazon.drm.Voucher@1.0', 'public_key', 'private_key',
              'com.amazon.drm.KeyPair@1.0', 'com.amazon.drm.ProtectedData@1.0',
              'doctype', 'com.amazon.drm.EnvelopeIndexTableOffset@1.0',
              'enddoc', 'license_type', 'license', 'watermark', 'key', 'value',
              'com.amazon.drm.License@1.0', 'category', 'metadata',
              'categorized_metadata', 'com.amazon.drm.CategorizedMetadata@1.0',
              'com.amazon.drm.VoucherEnvelope@1.0', 'mac', 'voucher',
              'com.amazon.drm.ProtectedData@2.0',
              'com.amazon.drm.Envelope@2.0',
              'com.amazon.drm.EnvelopeMetadata@2.0',
              'com.amazon.drm.EncryptedPage@2.0',
              'com.amazon.drm.PlainText@2.0', 'compression_algorithm',
              'com.amazon.drm.Compressed@1.0', 'page_index_table',
              ] + ['com.amazon.drm.VoucherEnvelope@%d.0' % n
                   for n in list(range(2, 29)) + [
                                   9708, 1031, 2069, 9041, 3646,
                                   6052, 9479, 9888, 4648, 5683,7384,2746,3332]+list(range(10001,11111))] #this assumes there are no new types added aside from voucher envelopes. So far it was largely correct
                                   


def addprottable(ion):
    ion.addtocatalog("ProtectedData", 1, SYM_NAMES)


def pkcs7pad(msg, blocklen):
    paddinglen = blocklen - len(msg) % blocklen
    padding = bchr(paddinglen) * paddinglen
    return msg + padding


def pkcs7unpad(msg, blocklen):
    _assert(len(msg) % blocklen == 0)

    paddinglen = msg[-1]

    _assert(paddinglen > 0 and paddinglen <= blocklen, "Incorrect padding - Wrong key")
    _assert(msg[-paddinglen:] == bchr(paddinglen) * paddinglen, "Incorrect padding - Wrong key")

    return msg[:-paddinglen]





# every VoucherEnvelope version has a corresponding "word" and magic number, used in obfuscating the shared secret
# 4-digit versions use their own obfuscation/scramble. It does not seem to depend on the "word" and number
OBFUSCATION_TABLE = {
    "V1":    (0x00, None),
    "V2":    (0x05, b'Antidisestablishmentarianism'),
    "V3":    (0x08, b'Floccinaucinihilipilification'),
    "V4":    (0x07, b'>\x14\x0c\x12\x10-\x13&\x18U\x1d\x05Rlt\x03!\x19\x1b\x13\x04]Y\x19,\t\x1b'),
    "V5":    (0x06, b'~\x18~\x16J\\\x18\x10\x05\x0b\x07\t\x0cZ\r|\x1c\x15\x1d\x11>,\x1b\x0e\x03"4\x1b\x01'),
    "V6":    (0x09, b'3h\x055\x03[^>\x19\x1c\x08\x1b\rtm4\x02Rp\x0c\x16B\n'),
    "V7":    (0x05, b'\x10\x1bJ\x18\nh!\x10"\x03>Z\'\r\x01]W\x06\x1c\x1e?\x0f\x13'),
    "V8":    (0x09, b"K\x0c6\x1d\x1a\x17pO}Rk\x1d'w1^\x1f$\x1c{C\x02Q\x06\x1d`"),
    "V9":    (0x05, b'X.\x0eW\x1c*K\x12\x12\t\n\n\x17Wx\x01\x02Yf\x0f\x18\x1bVXPi\x01'),
    "V10":   (0x07, b'z3\n\x039\x12\x13`\x06=v;\x02MTK\x1e%}L\x1c\x1f\x15\x0c\x11\x02\x0c\n8\x17p'),
    "V11":   (0x05, b'L=\nhVm\x07go\n6\x14\x06\x16L\r\x02\x0b\x0c\x1b\x04#p\t'),
    "V12":   (0x06, b';n\x1d\rl\x13\x1c\x13\x16p\x14\x07U\x0c\x1f\x19w\x16\x16\x1d5T'),
    "V13":   (0x07, b'I\x05\t\x08\x03r)\x01$N\x0fr3n\x0b062D\x0f\x13'),
    "V14":   (0x05, b"\x03\x02\x1c9\x19\x15\x15q\x1057\x08\x16\x0cF\x1b.Fw\x01\x12\x03\x13\x02\x17S'hk6"),
    "V15":   (0x0A, b'&,4B\x1dcI\x0bU\x03I\x07\x04\x1c\t\x05c\x07%ws\x0cj\t\x1a\x08\x0f'),
    "V16":   (0x0A, b'\x06\x18`h;b><\x06PqR\x02Zc\x034\n\x16\x1e\x18\x06#e'),
    "V17":   (0x07, b'y\r\x12\x08fw.[\x02\t\n\x13\x11\x0c\x11b\x1e8L\x10(\x13<Jx6c\x0f'),
    "V18":   (0x07, b'I\x0b\x0e;\x19\x1aIa\x10s\x19g\\\x1b\x11!\x18yf\x0f\t\x1d7[bSp\x03'),
    "V19":   (0x05, b'\n6>)N\x02\x188\x016s\x13\x14\x1b\x16jeN\n\x146\x04\x18\x1c\x0c\x19\x1f,\x02]'),
    "V20":   (0x08, b'_\r\x01\x12]\\\x14*\x17i\x14\r\t!\x1e;~hZ\x12jK\x17\x1e*1'),
    "V21":   (0x07, b'e\x1d\x19|\ty\x1di|N\x13\x0e\x04\x1bj<h\x13\x15k\x12\x08=\x1f\x16~\x13l'),
    "V22":   (0x08, b'?\x17yi$k7Pc\tEo\x0c\x07\x07\t\x1f,*i\x12\x0cI0\x10I\x1a?2\x04'),
    "V23":   (0x08, b'\x16+db\x13\x04\x18\rc%\x14\x17\x0f\x13F\x0c[\t9\x1ay\x01\x1eH'),
    "V24":   (0x06, b'|6\\\x1a\r\x10\nP\x07\x0fu\x1f\t;\rr`uv\\~55\x11]N'),
    "V25":   (0x09, b'\x07\x14w\x1e;^y\x01:\x08\x07\x1fr\tU#j\x16\x12\x1eB\x04\x16=\x06fZ\x07\x02\x06'),
    "V26":   (0x06, b'\x03IL\x1e"K\x1f\x0f\x1fp0\x01`X\x02z0`\x03\x0eN\x07'),
    "V27":   (0x07, b'Xk\x10y\x02\x18\x10\x17\x1d,\x0e\x05e\x10\x15"e\x0fh(\x06s\x1c\x08I\x0c\x1b\x0e'),
    "V28":   (0x0A, b'6P\x1bs\x0f\x06V.\x1cM\x14\x02\n\x1b\x07{P0:\x18zaU\x05'),
    "V9708": (0x05, b'\x1diIm\x08a\x17\x1e!am\x1d\x1aQ.\x16!\x06*\x04\x11\t\x06\x04?'),
    "V1031": (0x08, b'Antidisestablishmentarianism'),
    "V2069": (0x07, b'Floccinaucinihilipilification'),
    "V9041": (0x06, b'>\x14\x0c\x12\x10-\x13&\x18U\x1d\x05Rlt\x03!\x19\x1b\x13\x04]Y\x19,\t\x1b'),
    "V3646": (0x09, b'~\x18~\x16J\\\x18\x10\x05\x0b\x07\t\x0cZ\r|\x1c\x15\x1d\x11>,\x1b\x0e\x03"4\x1b\x01'),
    "V6052": (0x05, b'3h\x055\x03[^>\x19\x1c\x08\x1b\rtm4\x02Rp\x0c\x16B\n'),
    "V9479": (0x09, b'\x10\x1bJ\x18\nh!\x10"\x03>Z\'\r\x01]W\x06\x1c\x1e?\x0f\x13'),
    "V9888": (0x05, b"K\x0c6\x1d\x1a\x17pO}Rk\x1d'w1^\x1f$\x1c{C\x02Q\x06\x1d`"),
    "V4648": (0x07, b'X.\x0eW\x1c*K\x12\x12\t\n\n\x17Wx\x01\x02Yf\x0f\x18\x1bVXPi\x01'),
    "V5683": (0x05, b'z3\n\x039\x12\x13`\x06=v;\x02MTK\x1e%}L\x1c\x1f\x15\x0c\x11\x02\x0c\n8\x17p'),
}


#common str:  "PIDv3AESAES/CBC/PKCS5PaddingHmacSHA256"
class workspace(object):
  def __init__(self,initial_list):
    self.work=initial_list
  def shuffle(self,shuflist):
    ll=len(shuflist)
    rt=[]
    for i in range(ll):
      rt.append(self.work[shuflist[i]])
    self.work=rt
  def sbox(self,table,matrix,skplist=[]): #table is list of 4-byte integers
    offset=0
    nwork=list(self.work)
    wo=0
    toff=0
    while offset<0x6000:
      uv5=table[toff+nwork[wo+0]]
      uv1=table[toff+nwork[wo+1]+0x100]
      uv2=table[toff+nwork[wo+2]+0x200]
      uv3=table[toff+nwork[wo+3]+0x300]
      moff=0
      if 0 in skplist:
        moff+=0x400
      else:
        nib1=matrix[moff+offset+(uv1>>0x1c)|( (uv5>>0x18)&0xf0)]
        moff+=0x100
        nib2=matrix[moff+offset+(uv3>>0x1c)|( (uv2>>0x18)&0xf0)]
        moff+=0x100
        nib3=matrix[moff+offset+((uv1>>0x18)&0xf) |( (uv5>>0x14)&0xf0)]
        moff+=0x100
        nib4=matrix[moff+offset+((uv3>>0x18)&0xf) |( (uv2>>0x14)&0xf0)]
        moff+=0x100
      rnib1=matrix[moff+offset+nib1*0x10+nib2]
      moff+=0x100
      rnib2=matrix[moff+offset+nib3*0x10+nib4]
      moff+=0x100
      nwork[wo+0]=rnib1*0x10+rnib2
      if 1 in skplist:
        moff+=0x400
      else:
        nib1=matrix[moff+offset+((uv1>>0x14)&0xf)|( (uv5>>0x10)&0xf0)]
        moff+=0x100
        nib2=matrix[moff+offset+((uv3>>0x14)&0xf)|( (uv2>>0x10)&0xf0)]
        moff+=0x100
        nib3=matrix[moff+offset+((uv1>>0x10)&0xf) |( (uv5>>0xc)&0xf0)]
        moff+=0x100
        nib4=matrix[moff+offset+((uv3>>0x10)&0xf) |( (uv2>>0xc)&0xf0)]
        moff+=0x100

      rnib1=matrix[moff+offset+nib1*0x10+nib2]
      moff+=0x100
      rnib2=matrix[moff+offset+nib3*0x10+nib4]
      moff+=0x100
      nwork[wo+1]=rnib1*0x10+rnib2
      if 2 in skplist:
        moff+=0x400
      else:
        nib1=matrix[moff+offset+((uv1>>0xc)&0xf)|( (uv5>>0x8)&0xf0)]
        moff+=0x100
        nib2=matrix[moff+offset+((uv3>>0xc)&0xf)|( (uv2>>0x8)&0xf0)]
        moff+=0x100
        nib3=matrix[moff+offset+((uv1>>0x8)&0xf) |( (uv5>>0x4)&0xf0)]
        moff+=0x100
        nib4=matrix[moff+offset+((uv3>>0x8)&0xf) |( (uv2>>0x4)&0xf0)]
        moff+=0x100
      rnib1=matrix[moff+offset+nib1*0x10+nib2]
      moff+=0x100
      rnib2=matrix[moff+offset+nib3*0x10+nib4]
      moff+=0x100
      nwork[wo+2]=rnib1*0x10+rnib2
      if 3 in skplist:
        moff+=0x400
      else:
        nib1=matrix[moff+offset+((uv1>>0x4)&0xf)|( (uv5)&0xf0)]
        moff+=0x100
        nib2=matrix[moff+offset+((uv3>>0x4)&0xf)|( (uv2)&0xf0)]
        moff+=0x100
        nib3=matrix[moff+offset+((uv1)&0xf)|( (uv5<<4)&0xf0) ]
        moff+=0x100
        nib4=matrix[moff+offset+((uv3)&0xf)|( (uv2<<4)&0xf0) ]
        moff+=0x100
      ##############
      rnib1=matrix[moff+offset+nib1*0x10+nib2]
      moff+=0x100
      rnib2=matrix[moff+offset+nib3*0x10+nib4]
      moff+=0x100
      nwork[wo+3]=rnib1*0x10+rnib2
      offset = offset + 0x1800
      wo+=4
      toff+=0x400
    self.work=nwork
  def lookup(self,ltable):
    for a in range(len(self.work)):
      self.work[a]=ltable[a]
  def exlookup(self,ltable):
    lookoffs=0
    for a in range(len(self.work)):
      self.work[a]=ltable[self.work[a]+lookoffs]
      lookoffs+=0x100
  def mask(self, chunk):
    out=[]
    for a in range(len(chunk)):
      self.work[a]=self.work[a]^chunk[a]
      out.append(self.work[a])
    return out

def process_V9708(st):
  #e9c457a7dae6aa24365e7ef219b934b17ed58ee7d5329343fc3aea7860ed51f9a73de14351c9
  ws=workspace([0x11]*16)
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.shuffle(repl)
    ws.sbox(d0x6a06ea70,d0x6a0dab50)
    ws.sbox(d0x6a073a70,d0x6a0dab50)
    ws.shuffle(repl)
    ws.exlookup(d0x6a072a70)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16;
  return bytes(out)

def process_V1031(st):
  #d53efea7fdd0fda3e1e0ebbae87cad0e8f5ef413c471c3ae81f39222a9ec8b8ed582e045918c
  ws=workspace([0x06,0x18,0x60,0x68,0x3b,0x62,0x3e,0x3c,0x06,0x50,0x71,0x52,0x02,0x5a,0x63,0x03])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.shuffle(repl)
    ws.sbox(d0x6a0797c0,d0x6a0dab50,[3])
    ws.sbox(d0x6a07e7c0,d0x6a0dab50,[3])
    ws.shuffle(repl)
    ws.sbox(d0x6a0797c0,d0x6a0dab50,[3])
    ws.sbox(d0x6a07e7c0,d0x6a0dab50,[3])
    ws.exlookup(d0x6a07d7c0)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
    #break
  return bytes(out)

def process_V2069(st):
  #8e6196d754a304c9354e91b5d79f07b048026d31c7373a8691e513f2c802c706742731caa858
  ws=workspace([0x79,0x0d,0x12,0x08,0x66,0x77,0x2e,0x5b,0x02,0x09,0x0a,0x13,0x11,0x0c,0x11,0x62])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a084498,d0x6a0dab50,[2])
    ws.shuffle(repl)
    ws.sbox(d0x6a089498,d0x6a0dab50,[2])
    ws.sbox(d0x6a089498,d0x6a0dab50,[2])
    ws.sbox(d0x6a084498,d0x6a0dab50,[2])
    ws.shuffle(repl)
    ws.exlookup(d0x6a088498)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)


def process_V9041(st):
  #11f7db074b24e560dfa6fae3252b383c3b936e51f6ded570dc936cb1da9f4fc4a97ec686e7d8
  ws=workspace([0x49,0x0b,0x0e,0x3b,0x19,0x1a,0x49,0x61,0x10,0x73,0x19,0x67,0x5c,0x1b,0x11,0x21])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a094170,d0x6a0dab50,[1])
    ws.shuffle(repl)
    ws.shuffle(repl)
    ws.sbox(d0x6a08f170,d0x6a0dab50,[1])
    ws.sbox(d0x6a08f170,d0x6a0dab50,[1])
    ws.sbox(d0x6a094170,d0x6a0dab50,[1])

    ws.exlookup(d0x6a093170)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
    #break
  return bytes(out)

def process_V3646(st):
  #d468aa362b44479282291983243b38197c4b4aa24c2c58e62c76ec4b81e08556ca0c54301664
  ws=workspace([0x0a,0x36,0x3e,0x29,0x4e,0x02,0x18,0x38,0x01,0x36,0x73,0x13,0x14,0x1b,0x16,0x6a])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.shuffle(repl)
    ws.sbox(d0x6a099e48,d0x6a0dab50,[2,3])
    ws.sbox(d0x6a09ee48,d0x6a0dab50,[2,3])
    ws.sbox(d0x6a09ee48,d0x6a0dab50,[2,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a099e48,d0x6a0dab50,[2,3])
    ws.sbox(d0x6a099e48,d0x6a0dab50,[2,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a09ee48,d0x6a0dab50,[2,3])
    ws.exlookup(d0x6a09de48)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)


def process_V6052(st):
  #d683c8c4e4f46ae45812196f37e218eabce0fae08994f25fabb01d3e569b8bf3866b99d36f57
  ws=workspace([0x5f,0x0d,0x01,0x12,0x5d,0x5c,0x14,0x2a,0x17,0x69,0x14,0x0d,0x09,0x21,0x1e,0x3b])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.shuffle(repl)
    ws.sbox(d0x6a0a4b20,d0x6a0dab50,[1,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a0a4b20,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0a9b20,d0x6a0dab50,[1,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a0a9b20,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0a9b20,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0a4b20,d0x6a0dab50,[1,3])

    ws.exlookup(d0x6a0a8b20)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)

def process_V9479(st):
  #925635db434bccd3f4791eb87b89d2dfc7c93be06e794744eb9de58e6d721e696980680ab551
  ws=workspace([0x65,0x1d,0x19,0x7c,0x09,0x79,0x1d,0x69,0x7c,0x4e,0x13,0x0e,0x04,0x1b,0x6a,0x3c ])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a0af7f8,d0x6a0dab50,[1,2,3])
    ws.sbox(d0x6a0af7f8,d0x6a0dab50,[1,2,3])
    ws.sbox(d0x6a0b47f8,d0x6a0dab50,[1,2,3])
    ws.sbox(d0x6a0af7f8,d0x6a0dab50,[1,2,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a0b47f8,d0x6a0dab50,[1,2,3])
    ws.shuffle(repl)
    ws.shuffle(repl)
    ws.sbox(d0x6a0b47f8,d0x6a0dab50,[1,2,3])
    ws.exlookup(d0x6a0b37f8)

    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)

def process_V9888(st):
  #54c470723f8c105ba0186b6319050869de673ce31a5ec15d4439921d4cd05c5e860cb2a41fea
  ws=workspace([0x3f,0x17,0x79,0x69,0x24,0x6b,0x37,0x50,0x63,0x09,0x45,0x6f,0x0c,0x07,0x07,0x09])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a0ba4d0,d0x6a0dab50,[1,2])
    ws.sbox(d0x6a0bf4d0,d0x6a0dab50,[1,2])
    ws.sbox(d0x6a0bf4d0,d0x6a0dab50,[1,2])
    ws.sbox(d0x6a0ba4d0,d0x6a0dab50,[1,2])
    ws.shuffle(repl)
    ws.shuffle(repl)
    ws.shuffle(repl)
    ws.sbox(d0x6a0bf4d0,d0x6a0dab50,[1,2])
    ws.sbox(d0x6a0ba4d0,d0x6a0dab50,[1,2])
    ws.exlookup(d0x6a0be4d0)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)

def process_V4648(st):
  #705bd4cd8b61d4596ef4ca40774d68e71f1f846c6e94bd23fd26e5c127e0beaa650a50171f1b
  ws=workspace([0x16,0x2b,0x64,0x62,0x13,0x04,0x18,0x0d,0x63,0x25,0x14,0x17,0x0f,0x13,0x46,0x0c])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a0ca1a8,d0x6a0dab50,[1,3])
    ws.shuffle(repl)
    ws.sbox(d0x6a0ca1a8,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0c51a8,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0ca1a8,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0c51a8,d0x6a0dab50,[1,3])
    ws.sbox(d0x6a0c51a8,d0x6a0dab50,[1,3])
    ws.shuffle(repl)
    ws.shuffle(repl)
    ws.exlookup(d0x6a0c91a8)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)

def process_V5683(st):
  #1f5af733423e5104afb9d5594e682ecf839a776257f33747c9beee671c57ab3f84943f69d8fd
  ws=workspace([0x7c,0x36,0x5c,0x1a,0x0d,0x10,0x0a,0x50,0x07,0x0f,0x75,0x1f,0x09,0x3b,0x0d,0x72])
  repl=[0,5,10,15,4,9,14,3,8,13,2,7,12,1,6,11]
  remln=len(st)
  sto=0
  out=[]
  while(remln>0):
    ws.sbox(d0x6a0d4e80,d0x6a0dab50,[])
    ws.shuffle(repl)
    ws.sbox(d0x6a0cfe80,d0x6a0dab50,[])
    ws.sbox(d0x6a0d4e80,d0x6a0dab50,[])
    ws.sbox(d0x6a0cfe80,d0x6a0dab50,[])
    ws.sbox(d0x6a0d4e80,d0x6a0dab50,[])
    ws.shuffle(repl)
    ws.sbox(d0x6a0cfe80,d0x6a0dab50,[])
    ws.shuffle(repl)
    ws.exlookup(d0x6a0d3e80)
    dat=ws.mask(st[sto:sto+16])
    out+=dat
    sto+=16
    remln-=16
  return bytes(out)


# def a2hex(arr):
#   ax=[]
#   ha="0123456789abcdef"
#   for a in arr:
#     if a<0: a=256+a
#     ax.append(ha[(a>>4)]+ha[a%16])
#   return "".join(ax)
#
# def memhex(adr,sz):
#   emu=EmulatorHelper(currentProgram)
#   arr=emu.readMemory(getAddress(adr),sz)
#   return a2hex(arr)
#




# obfuscate shared secret according to the VoucherEnvelope version
def obfuscate(secret, version):
    if version == 1:  # v1 does not use obfuscation
        return secret

    magic, word = OBFUSCATION_TABLE.get("V%d" % version,(1,b"unknown"))

    # extend secret so that its length is divisible by the magic number
    if len(secret) % magic != 0:
        secret = secret + b'\x00' * (magic - len(secret) % magic)

    secret = bytearray(secret)

    obfuscated = bytearray(len(secret))
    wordhash = bytearray(hashlib.sha256(word).digest())

    # shuffle secret and xor it with the first half of the word hash
    for i in range(0, len(secret)):
        index = i // (len(secret) // magic) + magic * (i % (len(secret) // magic))
        obfuscated[index] = secret[i] ^ wordhash[index % 16]

    return obfuscated



# scramble() and obfuscate2() from https://github.com/andrewc12/DeDRM_tools/commit/d9233d61f00d4484235863969919059f4d0b2057

def scramble(st,magic):
    ret=bytearray(len(st))
    padlen=len(st)
    for counter in range(len(st)):
        ivar2=(padlen//2)-2*(counter%magic)+magic+counter-1
        ret[ivar2%padlen]=st[counter]
    return ret


def obfuscate2(secret, version):
    if version == 1:  # v1 does not use obfuscation
        return secret
    magic, word = OBFUSCATION_TABLE.get("V%d" % version,(1,b"unknown"))
    # extend secret so that its length is divisible by the magic number
    if len(secret) % magic != 0:
        secret = secret + b'\x00' * (magic - len(secret) % magic)
    obfuscated = bytearray(len(secret))
    wordhash = bytearray(hashlib.sha256(word).digest()[16:])
    #print(wordhash.hex())
    shuffled = bytearray(scramble(secret,magic))
    for i in range(0, len(secret)):
        obfuscated[i] = shuffled[i] ^ wordhash[i % 16]
    return obfuscated

# scramble3() and obfuscate3() from https://github.com/Satsuoni/DeDRM_tools/commit/da6b6a0c911b6d45fe1b13042b690daebc1cc22f

def scramble3(st,magic):
  ret=bytearray(len(st))
  padlen=len(st)
  divs = padlen // magic
  cntr = 0
  iVar6 = 0
  offset = 0
  if (0 < ((magic - 1) + divs)):
    while True:
      if (offset & 1) == 0 :
        uVar4 = divs - 1
        if offset < divs:
          iVar3 = 0
          uVar4 = offset
        else:
          iVar3 = (offset - divs) + 1
        if uVar4>=0:
          iVar5 = uVar4 * magic
          index =  ((padlen - 1) - cntr)
          while True:
            if (magic <= iVar3): break
            ret[index] = st[iVar3 + iVar5]
            iVar3 = iVar3 + 1
            cntr = cntr + 1
            uVar4 = uVar4 - 1
            iVar5 = iVar5 - magic
            index -= 1
            if uVar4<=-1: break
      else:
        if (offset < magic):
          iVar3 = 0
        else :
          iVar3 = (offset - magic) + 1
        if (iVar3 < divs):
          uVar4 = offset
          if (magic <= offset):
            uVar4 = magic - 1

          index = ((padlen - 1) - cntr)
          iVar5 = iVar3 * magic
          while True:
            if (uVar4 < 0) : break
            iVar3 += 1
            ret[index] = st[uVar4 + iVar5]
            uVar4 -= 1
            index=index-1
            iVar5 = iVar5 + magic;
            cntr += 1;
            if iVar3>=divs: break
      offset = offset + 1
      if offset >= ((magic - 1) + divs) :break
  return ret

#not sure if the third variant is used anywhere, but it is in Kindle, so I tried to add it
def obfuscate3(secret, version):
    if version == 1:  # v1 does not use obfuscation
        return secret
    magic, word = OBFUSCATION_TABLE.get("V%d" % version,(1,b"unknown"))
    # extend secret so that its length is divisible by the magic number
    if len(secret) % magic != 0:
        secret = secret + b'\x00' * (magic - len(secret) % magic)
    #secret = bytearray(secret)
    obfuscated = bytearray(len(secret))
    wordhash = bytearray(hashlib.sha256(word).digest())
    #print(wordhash.hex())
    shuffled=bytearray(scramble3(secret,magic))
    #print(shuffled)
    # shuffle secret and xor it with the first half of the word hash
    for i in range(0, len(secret)):
        obfuscated[i] = shuffled[i] ^ wordhash[i % 16]
    return obfuscated

class SKeyList(object):
    def __init__(self, skeyfile):
      self.keycandidates={}
      self.secretkeys={} #let us hope there is one key per voucher...
      if skeyfile is None: return
      if os.path.isfile(skeyfile):
          with open(skeyfile,"r",encoding="utf8") as fl:
              for line in fl:
                  sline=line.strip()
                  if len(sline)<32: continue 
                  lst=sline.split("$")
                  if len(lst)<2: continue 
                  voucherid=lst[0]
                  for key in lst[1:]:
                      skey=key.split(":")
                      if skey[0]=="secret_key":
                          self.secretkeys[voucherid]=bytes.fromhex(skey[1])
                      elif skey[0]=="shared_key":
                          curlist=self.keycandidates.get(voucherid,[])
                          curlist.append(bytes.fromhex(skey[1]))
                          self.keycandidates[voucherid]=curlist
                          
class DrmIonVoucher(object):
    envelope = None
    version = None
    voucher = None
    drmkey = None
    license_type = "Unknown"

    encalgorithm = ""
    enctransformation = ""
    hashalgorithm = ""

    lockparams = None

    ciphertext = b""
    cipheriv = b""
    secretkey = b""

    def __init__(self, voucherenv, dsn, secret,skeylist=None):
        self.dsn, self.secret = dsn, secret

        if isinstance(dsn, str):
            self.dsn = dsn.encode('ASCII')

        if isinstance(secret, str):
            self.secret = secret.encode('ASCII')

        self.lockparams = []
        self.keycandidates=[]
        self.secretkeycandidate=None
        self.skeylist=skeylist
        self.voucher_id=""
        self.envelope = BinaryIonParser(voucherenv)
        addprottable(self.envelope)

    def decryptvoucher(self):
        shared = ("PIDv3" + self.encalgorithm + self.enctransformation + self.hashalgorithm).encode('ASCII')

        self.lockparams.sort()
        for param in self.lockparams:
            if param == "ACCOUNT_SECRET":
                shared += param.encode('ASCII') + self.secret
            elif param == "CLIENT_ID":
                shared += param.encode('ASCII') + self.dsn
            else:
                _assert(False, "Unknown lock parameter: %s" % param)


        # i know that version maps to scramble pretty much 1 to 1, but there was precendent where they changed it, so...
        sharedsecrets = [obfuscate(shared, self.version),obfuscate2(shared, self.version),obfuscate3(shared, self.version),
                         process_V9708(shared), process_V1031(shared), process_V2069(shared), process_V9041(shared),
                         process_V3646(shared), process_V6052(shared), process_V9479(shared), process_V9888(shared),
                         process_V4648(shared), process_V5683(shared)]

        decrypted=False
        lastexception = None # type: Exception | None
        keycandidates=self.keycandidates+[hmac.new(sharedsecret, b"PIDv3", digestmod=hashlib.sha256).digest() for sharedsecret in sharedsecrets]
        for key in keycandidates:
            print(f"{key.hex()} {self.cipheriv[:16].hex()}")
            aes = AES.new(key[:32], AES.MODE_CBC, self.cipheriv[:16])
            try:
                b = aes.decrypt(self.ciphertext)
                b = pkcs7unpad(b, 16)
                self.drmkey = BinaryIonParser(BytesIO(b))
                addprottable(self.drmkey)

                _assert(self.drmkey.hasnext() and self.drmkey.next() == TID_LIST and self.drmkey.gettypename() == "com.amazon.drm.KeySet@1.0",
                    "Expected KeySet, got %s" % self.drmkey.gettypename())
                decrypted=True

                print("Decryption succeeded")
                break
            except Exception as ex:
                lastexception = ex
                print("Decryption failed, trying next fallback ")
        if not decrypted:
            if self.secretkeycandidate is None:
              print("Failed all decryption attempts and no key candidate available")
              raise lastexception
            else:
                print("Failed all decryption attempts but we have a key candidate")
                self.secretkey =self.secretkeycandidate
                self.drmkey=None
                return
                 

        self.drmkey.stepin()
        while self.drmkey.hasnext():
            self.drmkey.next()
            if self.drmkey.gettypename() != "com.amazon.drm.SecretKey@1.0":
                continue

            self.drmkey.stepin()
            while self.drmkey.hasnext():
                self.drmkey.next()
                if self.drmkey.getfieldname() == "algorithm":
                    _assert(self.drmkey.stringvalue() == "AES", "Unknown cipher algorithm: %s" % self.drmkey.stringvalue())
                elif self.drmkey.getfieldname() == "format":
                    _assert(self.drmkey.stringvalue() == "RAW", "Unknown key format: %s" % self.drmkey.stringvalue())
                elif self.drmkey.getfieldname() == "encoded":
                    self.secretkey = self.drmkey.lobvalue()

            self.drmkey.stepout()
            break

        self.drmkey.stepout()

    def parse(self):
        self.envelope.reset()
        _assert(self.envelope.hasnext(), "Envelope is empty")
        tn=self.envelope.gettypename()
        _assert(self.envelope.next() == TID_STRUCT and str.startswith(tn, "com.amazon.drm.VoucherEnvelope@"),
                "Unknown type encountered in envelope, expected VoucherEnvelope")
        print(f"Envelope version {tn}")
        self.version = int(self.envelope.gettypename().split('@')[1][:-2])

        self.envelope.stepin()
        while self.envelope.hasnext():
            self.envelope.next()
            field = self.envelope.getfieldname()
            if field == "voucher":
                self.voucher = BinaryIonParser(BytesIO(self.envelope.lobvalue()))
                addprottable(self.voucher)
                continue
            elif field != "strategy":
                continue

            _assert(self.envelope.gettypename() == "com.amazon.drm.PIDv3@1.0", "Unknown strategy: %s" % self.envelope.gettypename())

            self.envelope.stepin()
            while self.envelope.hasnext():
                self.envelope.next()
                field = self.envelope.getfieldname()
                if field == "encryption_algorithm":
                    self.encalgorithm = self.envelope.stringvalue()
                elif field == "encryption_transformation":
                    self.enctransformation = self.envelope.stringvalue()
                elif field == "hashing_algorithm":
                    self.hashalgorithm = self.envelope.stringvalue()
                elif field == "lock_parameters":
                    self.envelope.stepin()
                    while self.envelope.hasnext():
                        _assert(self.envelope.next() == TID_STRING, "Expected string list for lock_parameters")
                        self.lockparams.append(self.envelope.stringvalue())
                    self.envelope.stepout()

            self.envelope.stepout()

        self.parsevoucher()
        if self.skeylist is not None:
            self.keycandidates=self.skeylist.keycandidates.get(self.voucher_id,[])
            print(f"Got {len(self.keycandidates)} shared key candidates {self.skeylist.keycandidates} {self.voucher_id}")
            self.secretkeycandidate=self.skeylist.secretkeys.get(self.voucher_id,None)
            if self.secretkeycandidate is not None:
                print(f"Got secret key candidate from file: {self.secretkeycandidate.hex()}")
           
    def parsevoucher(self):
        _assert(self.voucher.hasnext(), "Voucher is empty")
        _assert(self.voucher.next() == TID_STRUCT and self.voucher.gettypename() == "com.amazon.drm.Voucher@1.0",
                "Unknown type, expected Voucher")

        self.voucher.stepin()
        while self.voucher.hasnext():
            self.voucher.next()

            if self.voucher.getfieldname() == "cipher_iv":
                self.cipheriv = self.voucher.lobvalue()
            elif self.voucher.getfieldname() == "cipher_text":
                self.ciphertext = self.voucher.lobvalue()
            elif self.voucher.getfieldname() == "id":
                self.voucher_id = self.voucher.stringvalue()
            elif self.voucher.getfieldname() == "license":
                _assert(self.voucher.gettypename() == "com.amazon.drm.License@1.0",
                        "Unknown license: %s" % self.voucher.gettypename())
                self.voucher.stepin()
                while self.voucher.hasnext():
                    self.voucher.next()
                    if self.voucher.getfieldname() == "license_type":
                        self.license_type = self.voucher.stringvalue()
                self.voucher.stepout()

    def printenvelope(self, lst):
        self.envelope.print_(lst)

    def printkey(self, lst):
        if self.voucher is None:
            self.parse()
        if self.drmkey is None:
            self.decryptvoucher()

        self.drmkey.print_(lst)

    def printvoucher(self, lst):
        if self.voucher is None:
            self.parse()

        self.voucher.print_(lst)

    def getlicensetype(self):
        return self.license_type


class DrmIon(object):
    ion = None
    voucher = None
    vouchername = ""
    key = b""
    onvoucherrequired = None

    def __init__(self, ionstream, onvoucherrequired,skeylist=None):
        self.ion = BinaryIonParser(ionstream)
        addprottable(self.ion)
        self.onvoucherrequired = onvoucherrequired
        self.skeylist = skeylist
    def parse(self, outpages):
        self.ion.reset()

        _assert(self.ion.hasnext(), "DRMION envelope is empty")
        _assert(self.ion.next() == TID_SYMBOL and self.ion.gettypename() == "doctype", "Expected doctype symbol")
        _assert(self.ion.next() == TID_LIST and self.ion.gettypename() in ["com.amazon.drm.Envelope@1.0", "com.amazon.drm.Envelope@2.0"],
                "Unknown type encountered in DRMION envelope, expected Envelope, got %s" % self.ion.gettypename())

        while True:
            if self.ion.gettypename() == "enddoc":
                break

            self.ion.stepin()
            while self.ion.hasnext():
                self.ion.next()

                if self.ion.gettypename() in ["com.amazon.drm.EnvelopeMetadata@1.0", "com.amazon.drm.EnvelopeMetadata@2.0"]:
                    self.ion.stepin()
                    while self.ion.hasnext():
                        self.ion.next()
                        fname=self.ion.getfieldname()
                        if self.key is None or len(self.key)==0:
                            if fname=="encryption_key":
                                keyname=self.ion.stringvalue()
                                if self.skeylist is not None:
                                    self.key=self.skeylist.secretkeys.get(keyname,self.key) # i know they are supposed to be voucher ids, but it is easier to dump them all into one file, their UIDs are distinct anyway
                                    if self.key is not None and len(self.key)>10:
                                        print("Obtained secret key from list: {}".format(self.key.hex()))
                        if  fname != "encryption_voucher":
                            continue

                        if self.vouchername == "":
                            self.vouchername = self.ion.stringvalue()
                            self.voucher = self.onvoucherrequired(self.vouchername)
                            if self.voucher is not None and self.voucher.secretkey is not None and len(self.voucher.secretkey)>0:
                                self.key = self.voucher.secretkey
                                _assert(self.key is not None, "Unable to obtain secret key from voucher")
                                
                        else:
                            _assert(self.vouchername == self.ion.stringvalue(),
                                    "Unexpected: Different vouchers required for same file?")

                    self.ion.stepout()

                elif self.ion.gettypename() in ["com.amazon.drm.EncryptedPage@1.0", "com.amazon.drm.EncryptedPage@2.0"]:
                    decompress = False
                    decrypt = True
                    ct = None
                    civ = None
                    self.ion.stepin()
                    while self.ion.hasnext():
                        self.ion.next()
                        if self.ion.gettypename() == "com.amazon.drm.Compressed@1.0":
                            decompress = True
                        if self.ion.getfieldname() == "cipher_text":
                            ct = self.ion.lobvalue()
                        elif self.ion.getfieldname() == "cipher_iv":
                            civ = self.ion.lobvalue()
                    _assert(self.key is not None, "Unable to obtain secret key from voucher or keylist")
                    if ct is not None and civ is not None:
                        self.processpage(ct, civ, outpages, decompress, decrypt)
                    self.ion.stepout()

                elif self.ion.gettypename() in ["com.amazon.drm.PlainText@1.0", "com.amazon.drm.PlainText@2.0"]:
                    decompress = False
                    decrypt = False
                    plaintext = None
                    self.ion.stepin()
                    while self.ion.hasnext():
                        self.ion.next()
                        if self.ion.gettypename() == "com.amazon.drm.Compressed@1.0":
                            decompress = True
                        if self.ion.getfieldname() == "data":
                            plaintext = self.ion.lobvalue()

                    if plaintext is not None:
                        self.processpage(plaintext, None, outpages, decompress, decrypt)
                    self.ion.stepout()

            self.ion.stepout()
            if not self.ion.hasnext():
                break
            self.ion.next()

    def print_(self, lst):
        self.ion.print_(lst)

    def processpage(self, ct, civ, outpages, decompress, decrypt):
        if decrypt:
            aes = AES.new(self.key[:16], AES.MODE_CBC, civ[:16])
            msg = pkcs7unpad(aes.decrypt(ct), 16)
        else:
            msg = ct

        if not decompress:
            outpages.write(msg)
            return

        _assert(msg[0] == 0, "LZMA UseFilter not supported")

        if calibre_lzma is not None:
            with calibre_lzma.decompress(msg[1:], bufsize=0x1000000) as f:
                f.seek(0)
                outpages.write(f.read())
            return

        decomp = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        while not decomp.eof:
            segment = decomp.decompress(msg[1:])
            msg = b"" # Contents were internally buffered after the first call
            outpages.write(segment)
