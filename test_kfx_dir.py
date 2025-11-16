#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os

# kfxlibをインポート
from kfxlib.yj_book import YJ_Book

def test_kfx_directory(directory):
    print(u"Testing directory: {}".format(directory))
    
    # ディレクトリ内のファイルを表示
    print(u"\nFiles in directory:")
    for f in os.listdir(directory):
        fpath = os.path.join(directory, f)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            print(u"  {} ({} bytes)".format(f, size))
    
    try:
        # YJ_Bookでディレクトリを読み込み
        print(u"\nCreating YJ_Book with directory...")
        book = YJ_Book(directory, credentials=[])
        
        # locate_book_datafilesを呼び出し
        print(u"\nLocating book datafiles...")
        book.locate_book_datafiles()
        
        print(u"\nFound {} container datafiles:".format(len(book.container_datafiles)))
        for df in book.container_datafiles:
            print(u"  {}".format(df.name))
        
        # デコードを試みる
        print(u"\nAttempting to decode book...")
        book.decode_book()
        
        print(u"\nSuccess! Found {} fragments".format(len(book.fragments)))
        
        # 固定レイアウトかチェック
        is_fixed_layout = hasattr(book, 'page_order_images') and book.page_order_images
        print(u"Is fixed layout: {}".format(is_fixed_layout))
        
        if is_fixed_layout:
            print(u"This is a fixed-layout book (comic/image-based)")
            print(u"Page order images: {}".format(len(book.page_order_images)))
        
    except Exception as e:
        print(u"\nError: {}".format(str(e)))
        import traceback
        traceback.print_exc()
        
        # エラーでもフラグメント情報を表示
        try:
            if hasattr(book, 'fragments'):
                print(u"\nFragments collected before error: {}".format(len(book.fragments)))
                # $260フラグメントがあるか確認
                count_260 = sum(1 for f in book.fragments if f.ftype == "$260")
                print(u"$260 fragments found: {}".format(count_260))
        except:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_kfx_dir.py <directory>")
        sys.exit(1)
    
    test_kfx_directory(sys.argv[1])
