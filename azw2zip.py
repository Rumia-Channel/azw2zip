#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os, os.path, getopt
import sys, os
import codecs
import contextlib
import glob
import shutil
import random
import string

__license__ = 'GPL v3'
__version__ = u"0.3"

sys.path.append(os.path.join(sys.path[0], "DeDRM_Plugin"))
sys.path.append(os.path.join(sys.path[0], 'KindleUnpack', 'lib'))

@contextlib.contextmanager
def redirect_stdout(target):
    original = sys.stdout
    sys.stdout = target
    yield
    sys.stdout = original

from compatibility_utils import add_cp65001_codec, unicode_argv
add_cp65001_codec()

#import DumpAZW6_v01
import DumpAZW6_py3
import kindleunpack
import unipath

from azw2zip_config import azw2zipConfig
from azw2zip_nodedrm import azw2zip
from azw2zip_nodedrm import azw2zipException
from kfx_key_extractor import KFXKeyExtractor, KFXKeyExtractorError

# KFX image extraction
try:
    from kfxlib.yj_book import YJ_Book
    from kfxlib.yj_to_image_book import KFX_IMAGE_BOOK
    KFX_AVAILABLE = True
except ImportError as e:
    print(u"警告: kfxlibが利用できません。KFX画像抽出は無効です。")
    print(u"  エラー: {}".format(str(e)))
    KFX_AVAILABLE = False

with redirect_stdout(open(os.devnull, 'w')):
    # AlfCrypto読み込み時の標準出力抑制
    import kindlekey
    from scriptinterface import decryptepub, decryptpdb, decryptpdf, decryptk4mobi

def usage(progname):
    print(u"Description:")
    print(u"  azw to zip or EPUB file.")
    print(u"  ")
    print(u"Usage:")
    print(u"  {} [-zefptscodK] <azw_indir> [outdir]".format(progname))
    print(u"  ")
    print(u"Options:")
    print(u"  -z        zipを出力(出力形式省略時のデフォルト)")
    print(u"  -e        epubを出力")
    print(u"  -f        画像ファイルをディレクトリに出力")
    print(u"  -p        pdfを出力(PrintReplica書籍の場合のみ)")
    print(u"  -t        ファイル名の作品名にUpdated_Titleを使用する(Kindleと同じ作品名)")
    print(u"  -s        作者名を昇順でソートする")
    print(u"  -c        zipでの出力時に圧縮をする")
    print(u"  -o        出力時に上書きをする(デフォルトは上書きしない)")
    print(u"  -d        デバッグモード(各ツールの標準出力表示＆作業ディレクトリ消さない)")
    print(u"  -K        k4i/kfx_keysを再生成する(書籍が増減した場合に使用)")
    print(u"  azw_indir 変換する書籍のディレクトリ(再帰的に読み込みます)")
    print(u"            対応形式: .azw, .azw3, .kfx, .azw8, .azw9, .ion, .kfx-zip")
    print(u"  outdir    出力先ディレクトリ(省略時は{}と同じディレクトリ)".format(progname))

def find_all_files(directory):
    for root, dirs, files in os.walk(directory):
        # yield root
        for file in files:
            yield os.path.join(root, file)

def process_kfx_to_images(kfx_path, output_dir, base_filename, output_zip, output_epub, compress_zip, debug_mode):
    """
    KFXファイル/ディレクトリから画像を抽出してZIP/EPUBを作成
    
    Args:
        kfx_path: KFXファイル/ディレクトリのパス
        output_dir: 出力ディレクトリ
        base_filename: 出力ファイル名のベース（拡張子なし）。Noneの場合は元のファイル名を使用
        output_zip: ZIP出力フラグ
        output_epub: EPUB出力フラグ
        compress_zip: ZIP圧縮フラグ
        debug_mode: デバッグモードフラグ
    """
    if not KFX_AVAILABLE:
        print(u"  KFX処理: kfxlibが利用できません")
        return None
    
    try:
        print(u"  KFX画像抽出: 開始: {}".format(kfx_path))
        
        # ディレクトリまたはファイルを判定
        if os.path.isdir(kfx_path):
            # ディレクトリの場合、KFX-ZIPを作成
            print(u"  KFX処理: ディレクトリをKFX-ZIPに変換します: {}".format(kfx_path))
            
            # 一時KFX-ZIPファイルを作成
            import zipfile
            temp_kfx_zip = os.path.join(output_dir, os.path.basename(kfx_path) + '.kfx-zip')
            if base_filename is None:
                base_name = os.path.basename(kfx_path)
            else:
                base_name = base_filename
            
            with zipfile.ZipFile(temp_kfx_zip, 'w', zipfile.ZIP_STORED) as zf:
                # まず一時ディレクトリ内のファイルを処理
                for filename in os.listdir(kfx_path):
                    if filename.endswith(('.azw', '.azw8', '.kfx', '.md', '.res')):
                        file_path = os.path.join(kfx_path, filename)
                        
                        # _nodrmファイルの場合、DRMIONヘッダーを削除して元のファイル名で格納
                        if '_nodrm' in filename:
                            # 元のファイル名を復元（_nodrm部分を削除）
                            original_filename = filename.replace('_nodrm', '')
                            
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                                # DRMIONヘッダーをチェック
                                if file_data[:8] == b'\xeaDRMION\xee':
                                    # DRMIONヘッダー（8バイト）後のCONTコンテナを取得
                                    file_data = file_data[8:]
                                    if debug_mode:
                                        print(u"    DRMIONヘッダー削除: {} -> {}".format(filename, original_filename))
                                # 元のファイル名でZIPに書き込み
                                zf.writestr(original_filename, file_data)
                        else:
                            # 通常のファイルはそのまま追加
                            zf.write(file_path, filename)
                        
                        if debug_mode:
                            stored_name = filename.replace('_nodrm', '') if '_nodrm' in filename else filename
                            print(u"    追加: {}".format(stored_name))
            
            process_target = temp_kfx_zip
            print(u"  KFX処理: KFX-ZIP作成完了: {}".format(temp_kfx_zip))
            
        elif os.path.isfile(kfx_path):
            # ファイルの場合
            parent_dir = os.path.dirname(kfx_path)
            # 親ディレクトリに他のKFXファイルがあるかチェック
            kfx_files = [f for f in os.listdir(parent_dir) if f.endswith(('.kfx', '.azw', '.azw8', '.ion', '.md', '.res'))]
            if len(kfx_files) > 1:
                # 複数のファイルがある場合、KFX-ZIPを作成
                print(u"  KFX処理: ディレクトリ内の複数ファイルをKFX-ZIPに変換します")
                import zipfile
                temp_kfx_zip = os.path.join(output_dir, os.path.basename(parent_dir) + '.kfx-zip')
                if base_filename is None:
                    base_name = os.path.basename(parent_dir)
                else:
                    base_name = base_filename
                
                with zipfile.ZipFile(temp_kfx_zip, 'w', zipfile.ZIP_STORED) as zf:
                    for filename in kfx_files:
                        file_path = os.path.join(parent_dir, filename)
                        
                        # _nodrmファイルの場合、DRMIONヘッダーを削除して元のファイル名で格納
                        if '_nodrm' in filename:
                            # 元のファイル名を復元（_nodrm部分を削除）
                            original_filename = filename.replace('_nodrm', '')
                            
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                                # DRMIONヘッダーをチェック
                                if file_data[:8] == b'\xeaDRMION\xee':
                                    # DRMIONヘッダー（8バイト）後のCONTコンテナを取得
                                    file_data = file_data[8:]
                                    if debug_mode:
                                        print(u"    DRMIONヘッダー削除: {} -> {}".format(filename, original_filename))
                                # 元のファイル名でZIPに書き込み
                                zf.writestr(original_filename, file_data)
                        else:
                            # 通常のファイルはそのまま追加
                            zf.write(file_path, filename)
                        
                        if debug_mode:
                            stored_name = filename.replace('_nodrm', '') if '_nodrm' in filename else filename
                            print(u"    追加: {}".format(stored_name))
                
                process_target = temp_kfx_zip
                print(u"  KFX処理: KFX-ZIP作成完了: {}".format(temp_kfx_zip))
            else:
                # 単独ファイルの場合、.kfx拡張子にコピー
                temp_kfx_file = kfx_path + '.kfx'
                shutil.copy2(kfx_path, temp_kfx_file)
                process_target = temp_kfx_file
                if base_filename is None:
                    base_name = os.path.splitext(os.path.basename(kfx_path))[0]
                    if base_name.endswith('_nodrm'):
                        base_name = base_name[:-7]
                else:
                    base_name = base_filename
        else:
            print(u"  KFX処理: パスが見つかりません: {}".format(kfx_path))
            return None
        
        try:
            # YJ_BookでKFX-ZIPを読み込み（DRM解除済みなので credentials=[]）
            book = YJ_Book(process_target, credentials=[])
            
            output_files = []
            
            # 本をデコード
            try:
                book.decode_book()
            except KeyError as e:
                error_msg = str(e)
                if "$260" in error_msg:
                    print(u"  KFX画像抽出: テキストフラグメントなし（画像のみの本）")
                    # $260エラーは無視して続行（画像のみの本）
                else:
                    print(u"  KFX画像抽出: デコード失敗: {}".format(error_msg))
                    if debug_mode:
                        import traceback
                        traceback.print_exc()
                    return None
            except Exception as e:
                error_msg = str(e)
                # DRMエラーの場合は警告のみで続行を試みる
                if "has DRM and cannot be converted" in error_msg:
                    print(u"  KFX警告: 一部のリソースファイルにDRMが残っていますが処理を継続します")
                    if debug_mode:
                        print(u"    詳細: {}".format(error_msg))
                    # DRMエラーでも処理を続行（メインファイルが解除されていれば変換可能）
                else:
                    print(u"  KFX画像抽出: デコード失敗: {}".format(error_msg))
                    if debug_mode:
                        import traceback
                        traceback.print_exc()
                    return None
            
            # base_filenameが指定されていない場合、メタデータから生成
            if base_filename is None:
                try:
                    from safefilename import safefilename
                    
                    # メタデータ取得を試みる
                    title = None
                    authors = None
                    
                    # get_metadataメソッドを使用
                    if hasattr(book, 'get_metadata'):
                        metadata = book.get_metadata()
                        if debug_mode:
                            print(u"  デバッグ: metadata取得成功")
                            if isinstance(metadata, dict):
                                print(u"  デバッグ: metadataキー: {}".format(list(metadata.keys())))
                        
                        if isinstance(metadata, dict):
                            # 一般的なメタデータキーを試す
                            for title_key in ['title', 'Title', 'book_title', 'cde_content_type']:
                                if title_key in metadata and metadata[title_key]:
                                    title = metadata[title_key]
                                    break
                            
                            for author_key in ['author', 'Author', 'authors', 'Authors', 'creator', 'Creator']:
                                if author_key in metadata and metadata[author_key]:
                                    author_val = metadata[author_key]
                                    if isinstance(author_val, list):
                                        authors = author_val
                                    else:
                                        authors = [author_val]
                                    break
                            
                            if debug_mode:
                                print(u"  デバッグ: メタデータから取得: title={}, authors={}".format(title, authors))
                    
                    # get_metadata_valueを試す
                    if not title and hasattr(book, 'get_metadata_value'):
                        try:
                            title = book.get_metadata_value('title') or book.get_metadata_value('Title')
                        except:
                            pass
                    
                    if not authors and hasattr(book, 'get_metadata_value'):
                        try:
                            author_val = book.get_metadata_value('author') or book.get_metadata_value('Author')
                            if author_val:
                                if isinstance(author_val, list):
                                    authors = author_val
                                else:
                                    authors = [author_val]
                        except:
                            pass
                    
                    if debug_mode:
                        print(u"  デバッグ: 最終KFXメタデータ: title={}, authors={}".format(title, authors))
                    
                    if title:
                        if authors and len(authors) > 0:
                            # authorsがリストの場合、各要素を文字列に変換
                            author_strs = [str(a) for a in authors]
                            author_str = ' & '.join(author_strs)
                            base_name = safefilename(u"{} - {}".format(title, author_str))
                        else:
                            base_name = safefilename(title)
                        if debug_mode:
                            print(u"  デバッグ: KFXメタデータからファイル名生成: {}".format(base_name))
                    # タイトルが取得できない場合は元の base_name を使用（既に設定済み）
                except Exception as e:
                    if debug_mode:
                        print(u"  デバッグ: メタデータからのファイル名生成失敗: {}".format(str(e)))
                        import traceback
                        traceback.print_exc()
                    # base_name は既に設定されているのでそのまま使用
            else:
                base_name = base_filename
            
            # 固定レイアウトかチェック
            is_fixed_layout = False
            if hasattr(book, 'page_order_images') and book.page_order_images:
                is_fixed_layout = True
            # $260フラグメントがない場合も固定レイアウト（画像のみ）
            elif hasattr(book, 'fragments'):
                count_260 = sum(1 for f in book.fragments if f.ftype == "$260")
                if count_260 == 0:
                    is_fixed_layout = True
                    print(u"  KFX処理: テキストコンテンツなし、画像ベースとして処理します")
            
            # 固定レイアウトの場合、CBZを試みる
            if output_zip and is_fixed_layout:
                try:
                    cbz_data = book.convert_to_cbz(
                        split_landscape_comic_images=False,
                        progress_fn=None
                    )
                    
                    cbz_path = os.path.join(output_dir, base_name + '.cbz')
                    with open(cbz_path, 'wb') as f:
                        f.write(cbz_data)
                    
                    output_files.append(cbz_path)
                    print(u"  KFX画像抽出: CBZ作成完了: {}".format(cbz_path))
                except KeyError as e:
                    error_msg = str(e)
                    if "$260" in error_msg:
                        print(u"  KFX画像抽出: CBZ作成スキップ（$260フラグメントエラー）")
                    else:
                        print(u"  KFX画像抽出: CBZ作成失敗: {}".format(error_msg))
                        if debug_mode:
                            import traceback
                            traceback.print_exc()
                except Exception as e:
                    print(u"  KFX画像抽出: CBZ作成失敗: {}".format(str(e)))
                    if debug_mode:
                        import traceback
                        traceback.print_exc()
            
            # リフロー型または固定レイアウトでない場合、EPUBを生成
            if output_epub or (not is_fixed_layout and (output_zip or output_epub)):
                try:
                    print(u"  KFX変換: EPUB変換を開始します")
                    epub_data = book.convert_to_epub(
                        epub2_desired=False,
                        force_cover=False,
                        progress_fn=None
                    )
                    
                    epub_path = os.path.join(output_dir, base_name + '.epub')
                    with open(epub_path, 'wb') as f:
                        f.write(epub_data)
                    
                    output_files.append(epub_path)
                    print(u"  KFX変換: EPUB作成完了: {}".format(epub_path))
                except Exception as e:
                    print(u"  KFX変換: EPUB作成失敗: {}".format(str(e)))
                    if debug_mode:
                        import traceback
                        traceback.print_exc()
            
            return output_files if output_files else None
        finally:
            # 一時ファイルを削除
            if 'temp_kfx_file' in locals() and temp_kfx_file and os.path.exists(temp_kfx_file):
                os.remove(temp_kfx_file)
            if 'temp_kfx_zip' in locals() and temp_kfx_zip and os.path.exists(temp_kfx_zip):
                os.remove(temp_kfx_zip)
        
    except Exception as e:
        print(u"  KFX画像抽出: エラー: {}".format(str(e)))
        if debug_mode:
            import traceback
            traceback.print_exc()
        return None

def main(argv=unicode_argv()):
    progname = os.path.splitext(os.path.basename(argv[0]))[0]
    azw2zip_dir = os.path.dirname(os.path.abspath(argv[0]))

    print(u"{0:} v.{1:s}\nCopyright (C) 2020 junk2ool".format(progname, __version__))
    print(u"")

    try:
        opts, args = getopt.getopt(argv[1:], "zefptscomdK")
    except getopt.GetoptError as err:
        print(str(err))
        usage(progname)
        sys.exit(2)

    if len(args) < 1:
        usage(progname)
        sys.exit(2)

    cfg = azw2zipConfig()
    cfg.load(os.path.join(azw2zip_dir, 'azw2zip.json'))

    updated_title = cfg.isUpdatedTitle()
    authors_sort = cfg.isAuthorsSort()
    compress_zip = cfg.isCompressZip()
    over_write = cfg.isOverWrite()
    output_thumb = cfg.isOutputThumb()
    output_zip = cfg.isOutputZip()
    output_epub = cfg.isOutputEpub()
    output_images = cfg.isOutputImages()
    output_pdf = cfg.isOutputPdf()
    debug_mode = cfg.isDebugMode()
    regenerate_keys = False  # 鍵の再生成フラグ

    # オプション解析
    for o, a in opts:
        if o == "-t":
            updated_title = True
        if o == "-s":
            authors_sort = True
        if o == "-c":
            compress_zip = True
        if o == "-o":
            over_write = True
        if o == "-m":
            output_thumb = True
        if o == "-z":
            output_zip = True
        if o == "-e":
            output_epub = True
        if o == "-f":
            output_images = True
        if o == "-p":
            output_pdf = True
        if o == "-d":
            debug_mode = True
        if o == "-K":
            regenerate_keys = True
    if not output_zip and not output_epub and not output_images and not output_pdf:
        output_zip = True
    cfg.setOptions(updated_title, authors_sort, compress_zip, over_write, output_thumb, debug_mode)
    cfg.setOutputFormats(output_zip, output_epub, output_images, output_pdf)

    # 変換ディレクトリを先に取得
    in_dir = args[0]
    if not os.path.isabs(in_dir):
        in_dir = os.path.abspath(in_dir)
    if not in_dir:
        in_dir = os.getcwd()
    in_dir = os.path.realpath(os.path.normpath(in_dir))
    if (os.path.isfile(in_dir)):
        in_dir = os.path.dirname(in_dir)
    print(u"変換ディレクトリ: {}".format(in_dir))

    # k4i ディレクトリはスクリプトのディレクトリ
    k4i_dir = cfg.getk4iDirectory()
    if not k4i_dir:
        k4i_dir = azw2zip_dir
    print(u"k4iディレクトリ: {}".format(k4i_dir))
    cfg.setk4iDirectory(k4i_dir)
    k4i_files = glob.glob(os.path.join(k4i_dir, '*.k4i'))
    
    # -K オプションが指定された場合、既存のk4iファイルを削除
    if regenerate_keys and len(k4i_files) > 0:
        print(u"k4i再生成: 既存のk4iファイルを削除します")
        for k4i_file in k4i_files:
            os.remove(k4i_file)
            print(u"  削除: {}".format(k4i_file))
        k4i_files = []
        # kfx_keys.txtも削除
        kfx_keys_file = os.path.join(k4i_dir, 'kfx_keys.txt')
        if os.path.exists(kfx_keys_file):
            os.remove(kfx_keys_file)
            print(u"  削除: {}".format(kfx_keys_file))
    
    if not len(k4i_files):
        # k4iがなければ作成
        if not sys.platform.startswith('win') and not sys.platform.startswith('darwin'):
            # k4iはWindowsかMacでしか作成できない
            print(u"エラー : k4iファイルが見つかりません: {}".format(k4i_dir))
            sys.exit(1)
        
        print(u"k4i作成: 開始: {}".format(k4i_dir))
        
        # Try KFXKeyExtractor first for newer Kindle versions
        kfx_success = False
        if sys.platform.startswith('win'):
            try:
                print(u"KFXKeyExtractor28.exeを使用してKindleキー抽出を試行中...")
                extractor = KFXKeyExtractor()
                
                # Use input directory as Kindle content directory
                kindle_docs = in_dir
                if not os.path.exists(kindle_docs):
                    # Fallback to default locations
                    kindle_docs = os.path.join(os.path.expandvars('%LOCALAPPDATA%'), 'Amazon', 'Kindle', 'My Kindle Content')
                    if not os.path.exists(kindle_docs):
                        kindle_docs = os.path.join(os.path.expanduser('~'), 'Documents', 'My Kindle Content')
                        if not os.path.exists(kindle_docs):
                            raise KFXKeyExtractorError(u"Kindle Contentディレクトリが見つかりません")
                
                print(u"  Kindle Content: {}".format(kindle_docs))
                
                # Extract to k4i_dir
                kfx_keys_file = os.path.join(k4i_dir, 'kfx_keys.txt')
                k4i_file = os.path.join(k4i_dir, 'device.k4i')
                
                result = extractor.extract_keys(kindle_docs, kfx_keys_file, k4i_file)
                print(u"KFXキー抽出成功")
                print(u"  KFXキー: {}".format(result['output_file']))
                print(u"  k4i: {}".format(result['k4i_file']))
                kfx_success = True
            except KFXKeyExtractorError as e:
                print(u"KFXKeyExtractor使用失敗: {}".format(str(e)))
                if "failed with code 3221225477" in str(e) or "failed with code -1073741819" in str(e):
                    print(u"  注意: KFXKeyExtractor28.exeはKindle 2.8.0(70980)専用です")
                    print(u"  現在インストールされているKindleのバージョンが異なる可能性があります")
                print(u"従来の方法(kindlekey)にフォールバック...")
            except Exception as e:
                print(u"KFXKeyExtractor実行エラー: {}".format(str(e)))
                print(u"従来の方法(kindlekey)にフォールバック...")
        
        # Fallback to old method if KFXKeyExtractor failed or not Windows
        if not kfx_success:
            try:
                print(u"Kindleキー抽出を試行中(kindlekey)...")
                kindlekey.getkey(k4i_dir)
            except Exception as e:
                print(u"エラー: k4iファイルの作成中にエラーが発生しました: {}".format(str(e)))
                print(u"詳細エラー情報:")
                import traceback
                traceback.print_exc()
        
        # Check if k4i was created
        k4i_files = glob.glob(os.path.join(k4i_dir, '*.k4i'))
        if len(k4i_files) > 0:
            print(u"k4i作成: 完了: {}".format(k4i_files[0]))
        else:
            print(u"エラー: k4iファイルの作成に失敗しました")
            print(u"注意: k4iファイルの作成には以下が必要です:")
            print(u"  - Kindle for PC/Macがインストールされていること")
            print(u"  - Kindleアプリでアカウントにログインしていること")
            print(u"  - Kindleアプリで書籍をダウンロードしたことがあること")
            print(u"  - 新しいKindle(1.26以降)の場合はKFXKeyExtractor28.exeが必要です")
            print(u"")
            print(u"既存のk4iファイルがある場合は、{}ディレクトリに配置してください".format(k4i_dir))
            sys.exit(1)
    else:
        for k4i_fpath in k4i_files:
            print(u"k4i: {}".format(k4i_fpath))

    # 出力ディレクトリ作成
    out_dir = cfg.getOutputDirectory()
    if len(args) > 1:
        out_dir = args[1]
        if not os.path.isabs(out_dir):
           out_dir = os.path.abspath(out_dir)
    if not out_dir:
        out_dir = azw2zip_dir #os.getcwd()
    out_dir = os.path.realpath(os.path.normpath(out_dir))
    cfg.setOutputDirectory(out_dir)

    print(u"出力ディレクトリ: {}".format(out_dir))
    if not unipath.exists(out_dir):
        unipath.mkdir(out_dir)
        print(u"出力ディレクトリ: 作成: {}".format(out_dir))

    output_zip_org = output_zip
    output_epub_org = output_epub
    output_images_org = output_images
    output_pdf_org = output_pdf

    # 処理ディレクトリのファイルを再帰走査
    for azw_fpath in find_all_files(in_dir):
        # ファイルでなければスキップ
        if not os.path.isfile(azw_fpath):
            continue
        # Kindleファイルでなければスキップ
        fname = os.path.basename(azw_fpath)
        fext = os.path.splitext(azw_fpath)[1].upper()
        # KFX関連: .kfx, .azw8, .azw9, .ion, .kfx-zip
        # Kindle Format 8: .azw, .azw3
        if fext not in ['.AZW', '.AZW3', '.KFX', '.AZW8', '.AZW9', '.ION'] and not fname.upper().endswith('.KFX-ZIP'):
            continue

        output_zip = output_zip_org
        output_epub = output_epub_org
        output_images = output_images_org
        output_pdf = output_pdf_org
        
        output_format = [
            [output_zip, u"zip", u".zip"],
            [output_epub, u"epub", u".epub"],
            [output_images, u"Images", u""],
            [output_pdf, u"pdf", u".*.pdf"],
        ]

        print("")
        azw_dir = os.path.dirname(azw_fpath)
        print(u"変換開始: {}".format(azw_dir))

        # 上書きチェック
        a2z = azw2zip()
        over_write_flag = over_write
        try:
            if a2z.load(azw_fpath, '', debug_mode) != 0:
                over_write_flag = True
        except azw2zipException as e:
            print(str(e))
            over_write_flag = True

        cfg.setPrintReplica(a2z.is_print_replica())

        if not over_write_flag:
            fname_txt = cfg.makeOutputFileName(a2z.get_meta_data())
            for format in output_format:
                if format[0]:
                    output_fpath = os.path.join(out_dir, fname_txt + format[2])
                    output_files = glob.glob(output_fpath.replace('[', '[[]'))
                    if (len(output_files)):
                        format[0] = False
                        try:
                            print(u" {}変換: パス: {}".format(format[1], output_files[0]))
                        except UnicodeEncodeError:
                            print(u" {}変換: パス: {}".format(format[1], output_files[0].encode('cp932', 'replace').decode('cp932')))
                    else:
                        over_write_flag = True

        if not over_write_flag:
            # すべてパス
            print(u"変換完了: {}".format(azw_dir))
            continue

        cfg.setOutputFormats(output_zip, output_epub, output_images, output_pdf)

        # 作業ディレクトリ作成
        book_fname = os.path.basename(os.path.dirname(azw_fpath))
        temp_dir = os.path.join(out_dir, book_fname)
        print(u" 作業ディレクトリ: 作成: {}".format(temp_dir))
        if not unipath.exists(temp_dir):
            unipath.mkdir(temp_dir)

        cfg.setTempDirectory(temp_dir)

        # HD画像(resファイル)があれば展開
        res_files = glob.glob(os.path.join(os.path.dirname(azw_fpath), '*.res'))
        for res_fpath in res_files:
            print(u"  HD画像展開: 開始: {}".format(res_fpath))

            if debug_mode:
                DumpAZW6_py3.DumpAZW6(res_fpath, temp_dir)
            else:
                with redirect_stdout(open(os.devnull, 'w')):
                    DumpAZW6_py3.DumpAZW6(res_fpath, temp_dir)

            print(u"  HD画像展開: 完了: {}".format(os.path.join(temp_dir, 'azw6_images')))

        # Kindleファイル全般のDRM解除
        DeDRM_path = ""
        if fext in ['.AZW', '.KFX', '.AZW8', '.AZW9', '.ION'] or fname.upper().endswith('.KFX-ZIP'):
            print(u"  DRM解除: 開始: {}".format(azw_fpath))
            
            # Check for existing KFX keys file
            kfx_keys_file = os.path.join(k4i_dir, 'kfx_keys.txt')
            skeyfile = kfx_keys_file if os.path.exists(kfx_keys_file) else None

            # KFXファイルの場合、ディレクトリ内の関連ファイルもDRM解除
            files_to_decrypt = [azw_fpath]
            additional_files_to_copy = []
            
            # KFXフォーマットかチェック（拡張子ではなくmagicバイトで判定）
            is_kfx_format = False
            try:
                with open(azw_fpath, 'rb') as f:
                    magic = f.read(8)
                    if magic == b'\xeaDRMION\xee' or magic[:4] == b'CONT':
                        is_kfx_format = True
            except Exception:
                pass
            
            if is_kfx_format or fext in ['.KFX', '.AZW8', '.AZW9', '.ION'] or fname.upper().endswith('.KFX-ZIP'):
                # .mdと.resファイルも処理（通常DRMなし、コピーのみ）
                for ext in ['.md', '.res']:
                    additional_files_to_copy.extend(glob.glob(os.path.join(azw_dir, '*' + ext)))
            
            for file_to_decrypt in files_to_decrypt:
                try:
                    if debug_mode:
                        decryptk4mobi(file_to_decrypt, temp_dir, k4i_dir, skeyfile)
                    else:
                        # エラー出力も抑制
                        old_stderr = sys.stderr
                        sys.stderr = open(os.devnull, 'w')
                        try:
                            with redirect_stdout(open(os.devnull, 'w')):
                                decryptk4mobi(file_to_decrypt, temp_dir, k4i_dir, skeyfile)
                        finally:
                            sys.stderr.close()
                            sys.stderr = old_stderr
                except Exception as e:
                    # DRM解除失敗は後で再試行するため、ここでは無視
                    if debug_mode:
                        print(u"  DRM解除エラー（再試行します）: {}".format(str(e)))
            
            # 追加ファイルの処理（.mdと.resファイル）
            for additional_file in additional_files_to_copy:
                basename = os.path.basename(additional_file)
                dst_file = os.path.join(temp_dir, basename)
                
                # .resファイルの場合、DRM解除を試みる
                if basename.endswith('.res'):
                    decrypted_file = os.path.join(temp_dir, basename.replace('.res', '_nodrm.res'))
                    try:
                        if debug_mode:
                            decryptk4mobi(additional_file, temp_dir, k4i_dir, skeyfile)
                        else:
                            old_stderr = sys.stderr
                            sys.stderr = open(os.devnull, 'w')
                            try:
                                with redirect_stdout(open(os.devnull, 'w')):
                                    decryptk4mobi(additional_file, temp_dir, k4i_dir, skeyfile)
                            finally:
                                sys.stderr.close()
                                sys.stderr = old_stderr
                        
                        # DRM解除が成功したかファイルの存在で確認
                        if os.path.exists(decrypted_file):
                            if debug_mode:
                                print(u"  KFX補助ファイルDRM解除成功: {}".format(basename))
                        else:
                            raise Exception("Decrypted file not created")
                    except Exception:
                        # DRM解除失敗時は元ファイルをコピー
                        if not os.path.exists(dst_file):
                            shutil.copy2(additional_file, dst_file)
                        if debug_mode:
                            print(u"  KFX補助ファイルコピー(DRM解除失敗): {}".format(basename))
                else:
                    # .mdファイルは直接コピー
                    if not os.path.exists(dst_file):
                        shutil.copy2(additional_file, dst_file)
                        if debug_mode:
                            print(u"  KFX補助ファイルコピー: {}".format(basename))

            DeDRM_files = glob.glob(os.path.join(temp_dir, book_fname + '*.azw?'))
            if not DeDRM_files:
                # KFX関連ファイルの場合は様々なパターンを探す
                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.kfx-zip'))
                if not DeDRM_files:
                    DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.kfx'))
                if not DeDRM_files:
                    DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw'))
                if not DeDRM_files:
                    DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw8'))
                if not DeDRM_files:
                    DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw9'))
            
            if len(DeDRM_files) > 0:
                DeDRM_path = DeDRM_files[0]
                print(u"  DRM解除: 完了: {}".format(DeDRM_path))
            else:
                print(u"  DRM解除: 失敗:")
                # KFX形式の場合、KFXKeyExtractorで再試行
                if is_kfx_format or fext in ['.KFX', '.AZW8', '.AZW9', '.ION'] or fname.upper().endswith('.KFX-ZIP'):
                    print(u"  KFXKeyExtractor: キー抽出を試行中...")
                    try:
                        kfx_extractor = KFXKeyExtractor()
                        # Kindleドキュメントパスを検出
                        # ユーザーのDocumentsフォルダもチェック
                        kindle_docs_paths = []
                        local_appdata = os.environ.get('LOCALAPPDATA', '')
                        if local_appdata:
                            kindle_docs_paths.append(os.path.join(local_appdata, 'Amazon', 'Kindle', 'My Kindle Content'))
                        
                        # Documentsフォルダもチェック
                        documents = os.path.join(os.path.expanduser('~'), 'Documents', 'My Kindle Content')
                        if os.path.exists(documents):
                            kindle_docs_paths.append(documents)
                        
                        kindle_docs = None
                        for path in kindle_docs_paths:
                            if os.path.exists(path):
                                kindle_docs = path
                                break
                        
                        if kindle_docs:
                            # 新しいk4iファイルを作成
                            new_k4i_path = os.path.join(k4i_dir, 'kfx_extracted.k4i')
                            result = kfx_extractor.extract_keys(kindle_docs, k4i_file=new_k4i_path)
                            print(u"  KFXKeyExtractor: キー抽出完了: {}".format(result['k4i_file']))
                            
                            # 抽出されたk4iファイルをskeyfileとして使用
                            kfx_skey_file = result['k4i_file']
                            
                            # 新しいk4iで再度DRM解除を試行
                            print(u"  DRM解除: 再試行: {}".format(azw_fpath))
                            if debug_mode:
                                decryptk4mobi(azw_fpath, temp_dir, k4i_dir, kfx_skey_file)
                            else:
                                with redirect_stdout(open(os.devnull, 'w')):
                                    decryptk4mobi(azw_fpath, temp_dir, k4i_dir, kfx_skey_file)
                            
                            # 再度DRMフリーファイルを検索
                            DeDRM_files = glob.glob(os.path.join(temp_dir, book_fname + '*.azw?'))
                            if not DeDRM_files:
                                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.kfx-zip'))
                            if not DeDRM_files:
                                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.kfx'))
                            if not DeDRM_files:
                                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw'))
                            if not DeDRM_files:
                                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw8'))
                            if not DeDRM_files:
                                DeDRM_files = glob.glob(os.path.join(temp_dir, '*_nodrm.azw9'))
                            
                            if len(DeDRM_files) > 0:
                                DeDRM_path = DeDRM_files[0]
                                print(u"  DRM解除: 再試行成功: {}".format(DeDRM_path))
                            else:
                                print(u"  DRM解除: 再試行も失敗")
                            
                            # 一時ストレージフォルダをクリーンアップ
                            kfx_extractor.cleanup_temp_storage()
                        else:
                            print(u"  KFXKeyExtractor: Kindleドキュメントが見つかりません")
                    except KFXKeyExtractorError as e:
                        print(u"  KFXKeyExtractor: エラー: {}".format(str(e)))
                    except Exception as e:
                        print(u"  KFXKeyExtractor: 予期しないエラー: {}".format(str(e)))
        elif fext in ['.AZW3']:
            DeDRM_path = azw_fpath

        if DeDRM_path and unipath.exists(DeDRM_path):
            # KFXファイルかチェック
            is_kfx_file = False
            with open(DeDRM_path, 'rb') as f:
                magic = f.read(8)
                if magic == b'\xeaDRMION\xee':
                    is_kfx_file = True
            
            if is_kfx_file and KFX_AVAILABLE:
                # KFXファイルの場合、ディレクトリ全体を画像抽出処理に渡す
                # （KFX本は複数のファイルで構成されている）
                print(u"  KFX画像抽出処理: 開始: {}".format(temp_dir))
                
                # fname.txtが存在する場合は読み込む
                fname_txt = None
                fname_path = os.path.join(temp_dir, "fname.txt")
                if unipath.exists(fname_path):
                    fname_file = codecs.open(fname_path, 'r', 'utf-8')
                    fname_txt = fname_file.readline().rstrip()
                    fname_file.close()
                    if debug_mode:
                        print(u"  デバッグ: fname.txtから読み込み: {}".format(fname_txt))
                
                kfx_output_files = process_kfx_to_images(
                    temp_dir,  # ディレクトリ全体を渡す
                    out_dir,
                    fname_txt,  # ファイル名のベースを渡す
                    output_zip, 
                    output_epub, 
                    compress_zip, 
                    debug_mode
                )
                
                if kfx_output_files:
                    print(u"  KFX画像抽出処理: 完了")
                    for output_file in kfx_output_files:
                        print(u"    出力: {}".format(output_file))
                else:
                    print(u"  KFX画像抽出処理: 失敗")
            else:
                # DRM解除されたファイルがKFX形式かチェック
                is_dedrm_kfx = False
                try:
                    with open(DeDRM_path, 'rb') as f:
                        magic = f.read(8)
                        if magic[:4] == b'CONT' or magic == b'\xeaDRMION\xee':
                            is_dedrm_kfx = True
                except Exception:
                    pass
                
                if is_dedrm_kfx or DeDRM_path.endswith(('.kfx', '.kfx-zip', '.azw8', '.azw9')):
                    # KFX形式の場合、KFX画像抽出処理
                    print(u"  KFX画像抽出処理: 開始: {}".format(os.path.dirname(DeDRM_path)))
                    
                    # fname.txtが存在する場合は読み込む
                    fname_txt = None
                    fname_path = os.path.join(temp_dir, "fname.txt")
                    if unipath.exists(fname_path):
                        fname_file = codecs.open(fname_path, 'r', 'utf-8')
                        fname_txt = fname_file.readline().rstrip()
                        fname_file.close()
                        if debug_mode:
                            print(u"  デバッグ: fname.txtから読み込み: {}".format(fname_txt))
                    
                    kfx_output = process_kfx_to_images(
                        os.path.dirname(DeDRM_path),
                        out_dir,
                        fname_txt,  # ファイル名のベースを渡す
                        output_zip, 
                        output_epub, 
                        compress_zip, 
                        debug_mode
                    )
                    
                    if kfx_output:
                        print(u"  KFX画像抽出処理: 成功")
                    else:
                        print(u"  KFX画像抽出処理: 失敗")
                else:
                    # 通常のKindle書籍変換
                    print(u"  書籍変換: 開始: {}".format(DeDRM_path))

                #unpack_dir = os.path.join(temp_dir, os.path.splitext(os.path.basename(DeDRM_path))[0])
                unpack_dir = temp_dir
                if debug_mode:
                    kindleunpack.kindleunpack(DeDRM_path, unpack_dir, cfg)
                else:
                    with redirect_stdout(open(os.devnull, 'w')):
                        kindleunpack.kindleunpack(DeDRM_path, unpack_dir, cfg)

                # 作成したファイル名を取得
                fname_path = os.path.join(temp_dir, "fname.txt")
                if unipath.exists(fname_path):
                    fname_file = codecs.open(fname_path, 'r', 'utf-8')
                    fname_txt = fname_file.readline().rstrip()
                    fname_file.close()

                    for format in output_format:
                        if format[0]:
                            # まず一時ディレクトリ内でファイルを検索（再帰的）
                            temp_output_fpath = os.path.join(temp_dir, "**", "*" + format[2])
                            temp_files = glob.glob(temp_output_fpath, recursive=True)
                            if debug_mode:
                                print(u"  デバッグ: 検索パス: {}".format(temp_output_fpath))
                                print(u"  デバッグ: 見つかったファイル: {}".format(temp_files))
                                # 一時ディレクトリ内の全ファイルを表示
                                print(u"  デバッグ: 一時ディレクトリ内容:")
                                for root, dirs, files in os.walk(temp_dir):
                                    for file in files:
                                        if file.endswith('.epub'):
                                            full_path = os.path.join(root, file)
                                            print(u"    EPUB発見: {}".format(full_path))
                            if temp_files:
                                # ファイルが見つかったら出力ディレクトリに移動
                                final_output_fpath = os.path.join(out_dir, fname_txt + format[2])
                                if debug_mode:
                                    print(u"  デバッグ: {} -> {}".format(temp_files[0], final_output_fpath))
                                shutil.move(temp_files[0], final_output_fpath)
                                output_files = [final_output_fpath]
                            else:
                                # glob検索で見つからない場合、実際のEPUBファイルを直接移動
                                if debug_mode:
                                    print(u"  デバッグ: glob検索失敗、直接EPUBファイルを探索")
                                for root, dirs, files in os.walk(temp_dir):
                                    for file in files:
                                        if file.endswith('.epub'):
                                            source_path = os.path.join(root, file)
                                            final_output_fpath = os.path.join(out_dir, fname_txt + format[2])
                                            if debug_mode:
                                                print(u"  デバッグ: 直接移動: {} -> {}".format(source_path, final_output_fpath))
                                            shutil.move(source_path, final_output_fpath)
                                            output_files = [final_output_fpath]
                                            break
                                    if output_files:
                                        break
                                if not output_files:
                                    # 出力ディレクトリ内も確認（既存の処理）
                                    output_fpath = os.path.join(out_dir, fname_txt + format[2])
                                    output_files = glob.glob(output_fpath.replace('[', '[[]'))
                            if (len(output_files)):
                                try:
                                    print(u"  {}変換: 完了: {}".format(format[1], output_files[0]))
                                except UnicodeEncodeError:
                                    print(u"  {}変換: 完了: {}".format(format[1], output_files[0].encode('cp932', 'replace').decode('cp932')))
                else:
                    print(u"  書籍変換: 失敗:")
        else:
            print(u"  DRM解除: 失敗:")

        if not debug_mode:
            shutil.rmtree(temp_dir)
            print(u" 作業ディレクトリ: 削除: {}".format(temp_dir))

        print(u"変換完了: {}".format(azw_dir))

    return 0

if __name__ == '__main__':
	sys.exit(main())
