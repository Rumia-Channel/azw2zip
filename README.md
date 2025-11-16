# azw2zip

KindleUnpack、DeDRM、DumpAZW6、kfxlibを統合し、Kindleの電子書籍（AZW/AZW3/KFX/KFX-ZIP等）を画像のみの無圧縮ZIPまたはEPUBに変換するツール。

**主な機能**:
- KFX DRM自動解除（KFXKeyExtractor統合）
- KFX→EPUB変換（kfxlib使用）
- HD画像展開（.resファイル対応）
- 漫画・コミックの画像抽出
- ZIP/EPUB出力対応

## Requirement

### 実行環境
* Python 3.10以上
* uv (Python package manager)

### 必要なパッケージ
* pycryptodome (DRM解除)
* lxml (XML処理)
* pypdf (KFX処理)
* Pillow (画像処理)
* beautifulsoup4 (HTML処理)

インストール:
```bash
uv sync
```

## Usage

### 基本的な使い方

```bash
# ZIP形式で出力
uv run python azw2zip.py -z "C:\Users\...\My Kindle Content" "C:\Output"

# EPUB形式で出力
uv run python azw2zip.py -e "C:\Users\...\My Kindle Content" "C:\Output"

# ZIP + EPUB 両方出力
uv run python azw2zip.py -z -e "C:\Users\...\My Kindle Content" "C:\Output"
```

### オプション

```
-z        ZIP形式で出力（画像のみ）
-e        EPUB形式で出力
-f        画像ファイルをディレクトリに出力
-p        PDF形式で出力（PrintReplica書籍の場合のみ）
-t        ファイル名の作品名にUpdated_Titleを使用
-s        作者名を昇順でソート
-c        ZIP出力時に圧縮する
-o        出力時に上書きする
-d        デバッグモード（詳細出力＆作業ディレクトリを保持）
```

詳しくはreadme.txtを参照。

## Supported Formats

* `.azw` (Kindle Format 8, Mobi)
* `.azw3` (Kindle Format 8)
* `.kfx` (Kindle Format X)
* `.azw8` (Kindle Format X variant)
* `.azw9` (Kindle Format X variant)
* `.ion` (Kindle Format X Ion format)
* `.kfx-zip` (Kindle Format X - ZIP Archive)

**注意**: 
- ファイル形式はヘッダー（マジックバイト）で判別されるため、拡張子が異なっていても正しく処理されます
- KFX形式の場合、初回実行時に自動的にキーが抽出されます（KFXKeyExtractor使用）

## KFX対応

### 新機能
- **自動DRM解除**: KFX DRMが検出されると、KFXKeyExtractorで自動的にキーを抽出し再試行
- **EPUB変換**: kfxlibを使用してKFX→EPUB変換
- **HD画像展開**: .resファイルから高解像度画像を抽出
- **KFX-ZIP作成**: 複数のKFXコンテナファイルを自動的にZIPアーカイブ化

### 動作確認済み
- Kindle Unlimited漫画
- 購入済みKFX書籍
- 固定レイアウト（Fixed Layout）書籍

## Building Executable

### ビルド環境
* Python 3.10以上
* uv
* Visual Studio Build Tools または Windows SDK
* Nuitka

### ビルド手順

```cmd
build.cmd
```

詳細は [BUILD.md](BUILD.md) を参照。

### 出力

`build\azw2zip.dist\` ディレクトリに以下が生成されます:
- `azw2zip.exe` - メイン実行ファイル
- `DeDRM_Plugin\` - DRM解除プラグイン
- `KindleUnpack\` - Kindle展開ライブラリ
- `kfxlib\` - KFX処理ライブラリ
- `DeDRM_tools\` - KFXKeyExtractor28.exe等
- `_internal\` - Pythonランタイム・依存ライブラリ

**重要**: `azw2zip.dist\` ディレクトリ全体が必要です（standalone形式）

## Development Environment
* Kindle for PC 2.8.0 (70980)
* Python 3.12
* Windows 10/11

## Note

### KFX処理に関する注意

1. **初回実行時のキー抽出**
   - KFX DRMが検出されると、KFXKeyExtractor28.exeが自動実行されます
   - `%LOCALAPPDATA%\Amazon\Kindle` または `Documents\My Kindle Content` からKindleドキュメントを検索
   - 抽出されたキーは `kfx_extracted.k4i` に保存されます

2. **必要な環境**
   - Kindle for PC 2.8.0 (70980) 推奨
   - 少なくとも1冊のKFX本がダウンロード済みであること

3. **トラブルシューティング**
   - KFX変換が失敗する場合、デバッグモード（`-d`）で実行して詳細を確認
   - `kfx_extracted.k4i` が空の場合、無料本をいくつかダウンロードしてから再試行

### おまじない
[ここ](https://www.mobileread.com/forums/showpost.php?p=3471461)から "disable k4pc download.bat" をダウンロードして実行することを勧める。

## Credits

このプロジェクトは以下のライブラリ・ツールを使用しています:
- **KindleUnpack** - Kindle書籍の展開
- **DeDRM_tools** - DRM解除
- **DumpAZW6** - HD画像展開
- **kfxlib** - KFX処理・EPUB変換
- **KFXKeyExtractor** - KFXキー抽出

## License
[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.ja.html)

## Author
* junk2ool
* https://www.junk2ool.net/
* https://github.com/junk2ool/azw2zip

## References
* DeDRM_tools v10.0.9 (RC1 for 10.1.0)  
https://github.com/noDRM/DeDRM_tools
のDeDRM_Plugin

* DumpAZW6_py3.py  
https://gist.github.com/fireattack/99b7d9f6b2896cfa33944555d9e2a158

* KindleUnpack 0.82  
https://github.com/kevinhendricks/KindleUnpack

* 作者名、作品名をファイル名にする際のダメ文字の置き換えには  
https://fgshun.hatenablog.com/entry/20100213/1266032982  
のsafefilenameを使用してダメ文字の全角化をするようにしています。(/を／等)

* http://rio2016.5ch.net/test/read.cgi/ebooks/1526467330/  
の[>>395](http://rio2016.5ch.net/test/read.cgi/ebooks/1526467330/395)さんの修正も取り込んでいます。
