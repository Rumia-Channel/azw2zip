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
* Python 3.10〜3.12
* uv (Python package manager)

### 必要なパッケージ
* pycryptodome (DRM解除)
* lxml (XML処理)
* pypdf (KFX処理)
* Pillow (画像処理)
* beautifulsoup4 (HTML処理)
* zstandard (KFXコンテナの展開)

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
azw2zip [-zefptscodKj] <azw_indir> [outdir]

-z        ZIP形式で出力（画像のみ）
-e        EPUB形式で出力
-f        画像ファイルをディレクトリに出力
-p        PDF形式で出力（PrintReplica書籍の場合のみ）
-t        ファイル名の作品名にUpdated_Titleを使用
-s        作者名を昇順でソート
-c        ZIP出力時に圧縮する
-o        出力時に上書きする
-d        デバッグモード（詳細出力＆作業ディレクトリを保持）
-K        k4i / kfx_keys を再生成する（書籍が増減した場合に使用）
-j FILE   変換結果をJSONL形式（1行1JSON）でFILEに追記出力
```

出力形式（`-z` / `-e` / `-f` / `-p`）を1つも指定しない場合は ZIP 出力がデフォルトになります。
各オプションの既定値は `azw2zip.json` でも設定できます（後述）。詳しくは readme.txt を参照。

### JSONL出力（`-j`）

`-j result.jsonl` を付けると、書籍ごとに次の形式の1行JSONを追記します（バッチ処理の結果集計向け）。

```json
{"input": "...", "status": "success", "title": "...", "authors": ["..."], "publisher": "", "format": "epub", "output": ["...\\作品名.epub"], "error": null}
```

`status` は `success` / `skipped`（既存出力あり）/ `failure` のいずれかです。

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
- Microsoft Store版Kindle for Windows（MSIXKFXArchiver使用）

## Building Executable

### ビルド環境
* Python 3.10〜3.12
* uv
* Visual Studio Build Tools または Windows SDK
* Nuitka（`pyproject.toml` の依存として導入されます）

### ビルド手順

```cmd
build.cmd
```

`build.cmd` は `uv sync` で依存を同期したのち、Nuitka の standalone モードで `azw2zip.exe` を生成し、
`DeDRM_Plugin` / `KindleUnpack` / `kfxlib` / `DeDRM_tools` を出力フォルダにコピーします。
最後に出力フォルダ `build\azw2zip.dist` を `build\azw2zip` へリネームして完了します。

### 出力

`build\azw2zip\` ディレクトリに以下が生成されます:
- `azw2zip.exe` - メイン実行ファイル
- `DeDRM_Plugin\` - DRM解除プラグイン
- `KindleUnpack\` - Kindle展開ライブラリ
- `kfxlib\` - KFX処理ライブラリ
- `DeDRM_tools\` - キー抽出・アーカイブ用の外部ツール（下記）
- 依存ライブラリ・Pythonランタイム一式（Nuitka standalone）

`DeDRM_tools\` に同梱される主なバイナリ:
- `KFXKeyExtractor282.exe` / `KFXKeyExtractor28.exe` - Kindle for PC 2.8.x 用キー抽出（282を優先）
- `MSIXKFXArchiverMobi1_16118.exe` - Microsoft Store版Kindle用のアーカイバ
- `KFXArchiver291.exe` / `KRFKeyExtractor.exe` - 補助ツール（任意）

**重要**: `build\azw2zip\` ディレクトリ全体が必要です（standalone形式）

## Development Environment
* Kindle for PC 2.8.0 (70980)
* Kindle for Windows (Microsoft Store版)
* Python 3.10〜3.12
* Windows 10/11

## Note

### KFX処理に関する注意

1. **初回実行時のキー抽出**
   - KFX DRMが検出されると、`KFXKeyExtractor282.exe`（無い場合は `28.exe`）が自動実行されます
   - `%LOCALAPPDATA%\Amazon\Kindle` または `Documents\My Kindle Content` からKindleドキュメントを検索
   - 抽出されたキーは `device.k4i` / `kfx_extracted.k4i` および `kfx_keys.txt` としてスクリプトと同じディレクトリに保存されます
   - 既存のキーがある場合はそれを再利用します。書籍を追加・削除してキーを作り直したいときは `-K` を付けて実行してください

2. **Microsoft Store版Kindle for Windowsの場合**
   - Microsoft Store版Kindleを検出すると、`DeDRM_tools\MSIXKFXArchiver*.exe` を使用して書籍を復号します
   - コンテンツの保存場所: `%LOCALAPPDATA%\Packages\AMZNKindle.AmazonKindleReadingApp_*\LocalState\Classic\Content`
   - `MSIXKFXArchiver*.exe` がない場合は `sample\DeDRM_bin\` からコピーするか、対応バージョンを別途入手してください
   - MSIXKFXArchiverはKindleアプリのバージョンに依存するため、対応していないバージョンでは動作しません

3. **必要な環境**
   - Kindle for PC 2.8.0 (70980) 推奨
   - 少なくとも1冊のKFX本がダウンロード済みであること

4. **トラブルシューティング**
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

### 原作者
* junk2ool
* https://www.junk2ool.net/
* https://github.com/junk2ool/azw2zip

### このフォークについて
本リポジトリは junk2ool 氏の azw2zip をベースに、KFX 対応・自動DRM解除（KFXKeyExtractor）・
Microsoft Store版Kindle対応（MSIXKFXArchiver）・EPUB変換（kfxlib）・JSONL出力などを追加したフォークです。
* https://github.com/Rumia-Channel/azw2zip

## References
* DeDRM_tools (DeDRM_Plugin v10.0.20 同梱)  
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
