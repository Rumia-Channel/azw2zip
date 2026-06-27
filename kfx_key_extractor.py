#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
KFX key extraction wrappers for Kindle for PC and Microsoft Store Kindle.

- KFXKeyExtractor:    wrapper for KFXKeyExtractor28.exe / KFXKeyExtractor282.exe
                      (legacy Kindle for PC 2.8.x)
- MSIXKFXArchiver:    wrapper for MSIXKFXArchiver*.exe
                      (Microsoft Store version of Kindle for Windows)
"""

import os
import subprocess
import tempfile
from pathlib import Path

__license__ = 'GPL v3'
__version__ = "0.2"


class KFXKeyExtractorError(Exception):
    """KFX key extraction failed"""
    pass


class KFXKeyExtractor:
    """Wrapper for KFXKeyExtractor28.exe / KFXKeyExtractor282.exe"""

    EXTRACTOR_CANDIDATES = [
        "KFXKeyExtractor282.exe",
        "KFXKeyExtractor28.exe",
    ]

    def __init__(self, extractor_path=None):
        if extractor_path is not None:
            self.extractor_paths = [Path(extractor_path)]
        else:
            script_dir = Path(__file__).parent
            self.extractor_paths = []
            for candidate in self.EXTRACTOR_CANDIDATES:
                candidate_path = script_dir / "DeDRM_tools" / candidate
                if candidate_path.exists():
                    self.extractor_paths.append(candidate_path)
            if not self.extractor_paths:
                raise KFXKeyExtractorError(
                    f"No KFX key extractor found in {script_dir / 'DeDRM_tools'}. "
                    f"Tried: {', '.join(self.EXTRACTOR_CANDIDATES)}")

        self.extractor_path = self.extractor_paths[0]

    def _try_extract_with_extractor(self, extractor_path, kindle_docs_path, output_file, k4i_file,
                                     cleanup_output, cleanup_k4i):
        """
        指定された extractor で1回だけキー抽出を試行する
        """
        # The Nuitka-compiled exe cannot run subprocess for KFXKeyExtractor at all
        # (ACCESS_VIOLATION on any pipe/handle inheritance). Use
        # subprocess.CREATE_NO_WINDOW to prevent handle inheritance.
        cmd = [
            str(extractor_path),
            str(kindle_docs_path),
            str(output_file),
            str(k4i_file)
        ]
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000

        try:
            result = subprocess.run(
                cmd,
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300
            )
        except subprocess.TimeoutExpired:
            if cleanup_output and output_file.exists():
                output_file.unlink()
            if cleanup_k4i and k4i_file.exists():
                k4i_file.unlink()
            raise KFXKeyExtractorError("KFX key extractor timed out after 5 minutes")
        except Exception as e:
            if cleanup_output and output_file.exists():
                output_file.unlink()
            if cleanup_k4i and k4i_file.exists():
                k4i_file.unlink()
            raise KFXKeyExtractorError(f"Failed to run KFX key extractor: {e}")

        if not output_file.exists() or output_file.stat().st_size == 0:
            if result.returncode != 0:
                raise KFXKeyExtractorError(
                    f"KFX key extractor failed with code {result.returncode} "
                    f"and no output was created")
            raise KFXKeyExtractorError("KFX key extractor produced no output")
        if not k4i_file.exists():
            raise KFXKeyExtractorError("K4i file not created")

        return {
            'output_file': str(output_file),
            'k4i_file': str(k4i_file),
            'stdout': '',
            'stderr': '',
            'returncode': result.returncode
        }

    def extract_keys(self, kindle_docs_path, output_file=None, k4i_file=None):
        """
        Extract KFX keys using available KFXKeyExtractor executables.
        Tries all available extractor candidates in order and falls back to the
        next one if the previous fails.

        Args:
            kindle_docs_path: Path to Kindle documents folder (with _EBOK folders)
            output_file: Output file path (optional, uses temp if None)
            k4i_file: Output k4i file path (optional, uses temp if None)

        Returns:
            dict with keys 'output_file', 'k4i_file', 'stdout', 'stderr'

        Raises:
            KFXKeyExtractorError: If all extractors fail
        """
        kindle_docs_path = Path(kindle_docs_path)
        if not kindle_docs_path.exists():
            raise KFXKeyExtractorError(f"Kindle documents path not found: {kindle_docs_path}")

        # Create temp files if not specified
        cleanup_output = False
        cleanup_k4i = False

        if output_file is None:
            fd, output_file = tempfile.mkstemp(suffix=".txt", prefix="kfx_keys_")
            os.close(fd)
            cleanup_output = True

        if k4i_file is None:
            fd, k4i_file = tempfile.mkstemp(suffix=".k4i", prefix="kfx_")
            os.close(fd)
            cleanup_k4i = True

        output_file = Path(output_file)
        k4i_file = Path(k4i_file)

        last_error = None
        for extractor_path in self.extractor_paths:
            try:
                return self._try_extract_with_extractor(
                    extractor_path, kindle_docs_path, output_file, k4i_file,
                    cleanup_output, cleanup_k4i)
            except KFXKeyExtractorError as e:
                last_error = e
                print(u"  KFXKeyExtractor {} 失敗: {}".format(extractor_path.name, str(e)))
                # 次の候補を試す前に、失敗した候補が作成した空の出力ファイルをクリーンアップ
                if cleanup_output and output_file.exists():
                    output_file.unlink()
                if cleanup_k4i and k4i_file.exists():
                    k4i_file.unlink()
                continue

        if last_error:
            raise last_error
        raise KFXKeyExtractorError("All KFX key extractors failed")

    def extract_keys_to_default(self, kindle_docs_path=None):
        """
        Extract KFX keys with automatic path detection

        Args:
            kindle_docs_path: Path to Kindle documents (default: %LOCALAPPDATA%/Amazon/Kindle/My Kindle Content)

        Returns:
            dict with keys 'output_file', 'k4i_file', 'stdout', 'stderr'
        """
        if kindle_docs_path is None:
            # Try default Kindle location
            local_appdata = os.environ.get('LOCALAPPDATA', '')
            if local_appdata:
                kindle_docs_path = Path(local_appdata) / "Amazon" / "Kindle" / "My Kindle Content"
            else:
                raise KFXKeyExtractorError("Could not find Kindle documents path")

        return self.extract_keys(kindle_docs_path)

    @staticmethod
    def read_k4i_file(k4i_path):
        """
        Read k4i file contents

        Args:
            k4i_path: Path to k4i file

        Returns:
            str: File contents
        """
        k4i_path = Path(k4i_path)
        if not k4i_path.exists():
            raise KFXKeyExtractorError(f"K4i file not found: {k4i_path}")

        with open(k4i_path, 'r', encoding='utf-8') as f:
            return f.read()

    def cleanup_temp_storage(self):
        """
        Clean up temporary /storage folder created by KFXKeyExtractor28.exe
        in %LOCALAPPDATA%
        """
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        if local_appdata:
            storage_path = Path(local_appdata) / "storage"
            if storage_path.exists() and storage_path.is_dir():
                import shutil
                shutil.rmtree(storage_path, ignore_errors=True)
                return True
        return False


class MSIXKFXArchiver:
    """
    Wrapper for MSIXKFXArchiver*.exe

    Microsoft Store version of Kindle for Windows stores books and keys in
    isolated MSIX package folders.  This external tool decrypts the books and
    produces ready-to-use .kfx-zip files plus a JSON .k4i key file.
    """

    ARCHIVER_CANDIDATES = [
        "MSIXKFXArchiverMobi1_16118.exe",
        "MSIXKFXArchiverMobi1_16034.exe",
        "MSIXKFXArchiverMobi1_15230.exe",
        "MSIXKFXArchiver1_16118.exe",
        "MSIXKFXArchiver1_16034.exe",
        "MSIXKFXArchiver1_15230.exe",
    ]

    def __init__(self, archiver_path=None):
        if archiver_path is None:
            script_dir = Path(__file__).parent
            for candidate in self.ARCHIVER_CANDIDATES:
                candidate_path = script_dir / "DeDRM_tools" / candidate
                if candidate_path.exists():
                    archiver_path = candidate_path
                    break
            else:
                raise KFXKeyExtractorError(
                    f"No MSIX KFX archiver found in {script_dir / 'DeDRM_tools'}. "
                    f"Tried: {', '.join(self.ARCHIVER_CANDIDATES)}")

        self.archiver_path = Path(archiver_path)
        if not self.archiver_path.exists():
            raise KFXKeyExtractorError(f"MSIX KFX archiver not found: {self.archiver_path}")

    @staticmethod
    def find_msstore_kindle_content():
        """
        Find Microsoft Store Kindle content directory.

        Returns:
            Path or None
        """
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        if not local_appdata:
            return None

        import glob
        pattern = os.path.join(
            local_appdata, 'Packages', 'AMZNKindle.AmazonKindleReadingApp_*',
            'LocalState', 'Classic', 'Content'
        )
        matches = glob.glob(pattern)
        for path in matches:
            if os.path.isdir(path):
                return Path(path)
        return None

    @staticmethod
    def is_msstore_kindle_content(path):
        """
        Check if a path looks like Microsoft Store Kindle content folder.

        Args:
            path: Path to check

        Returns:
            bool
        """
        if path is None:
            return False
        norm = os.path.normpath(str(path)).replace('/', '\\').lower()
        return (
            'amznkindle.amazonkindlereadingapp_' in norm and
            'localstate\\classic\\content' in norm
        )

    def extract_keys(self, kindle_docs_path=None, output_dir=None, k4i_file=None,
                     dll_dir=None, extra_k4i_files=None, capture_output=False,
                     timeout=600):
        """
        Run MSIXKFXArchiver to decrypt MS Store Kindle books.

        Args:
            kindle_docs_path: Path to Kindle documents folder (with _EBOK folders).
                              If None, auto-detect MS Store Kindle content.
            output_dir: Directory for archived_kfx output (default: current dir)
            k4i_file: Output k4i file path (default: output_dir/oldbooks.k4i)
            dll_dir: Folder containing KindleReader DLLs (KatxopoApp).
                     Usually auto-detected by the archiver.
            extra_k4i_files: List of additional k4i files for key hints.
            capture_output: If True, capture stdout/stderr instead of DEVNULL.
                            Note: Nuitka-built exe may crash with pipes.
            timeout: Timeout in seconds.

        Returns:
            dict with keys 'output_dir', 'k4i_file', 'stdout', 'stderr', 'returncode'

        Raises:
            KFXKeyExtractorError: If extraction fails
        """
        if kindle_docs_path is None:
            kindle_docs_path = self.find_msstore_kindle_content()
            if kindle_docs_path is None:
                raise KFXKeyExtractorError(
                    "Could not find Microsoft Store Kindle content folder")

        kindle_docs_path = Path(kindle_docs_path)
        if not kindle_docs_path.exists():
            raise KFXKeyExtractorError(
                f"Kindle documents path not found: {kindle_docs_path}")

        if output_dir is None:
            output_dir = Path.cwd()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if k4i_file is None:
            k4i_file = output_dir / "oldbooks.k4i"
        k4i_file = Path(k4i_file)

        # MSIXKFXArchiver writes .kfx-zip files directly into the folder
        # passed as the 2nd argument. We pass output_dir/archived_kfx so
        # that the default layout (archived_kfx/*.kfx-zip) is preserved.
        archived_kfx_dir = output_dir / "archived_kfx"
        archived_kfx_dir.mkdir(parents=True, exist_ok=True)

        cmd = [str(self.archiver_path)]
        cmd.append(str(kindle_docs_path))
        cmd.append(str(archived_kfx_dir))
        cmd.append(str(k4i_file))

        if dll_dir is not None:
            cmd.append(str(dll_dir))
        else:
            # Use "default" placeholder so archiver falls back to installed dir
            cmd.append("default")

        if extra_k4i_files:
            for extra in extra_k4i_files:
                cmd.append(str(extra))

        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000

        kwargs = {
            'creationflags': DETACHED_PROCESS | CREATE_NO_WINDOW,
            'stdin': subprocess.DEVNULL,
            'timeout': timeout,
        }
        if capture_output:
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            # Encoding may include non-ASCII; use errors='replace' later
        else:
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL

        try:
            result = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired:
            raise KFXKeyExtractorError(
                f"MSIX KFX archiver timed out after {timeout} seconds")
        except Exception as e:
            raise KFXKeyExtractorError(f"Failed to run MSIX KFX archiver: {e}")

        stdout_text = ''
        stderr_text = ''
        if capture_output:
            if result.stdout:
                stdout_text = result.stdout.decode('utf-8', errors='replace')
            if result.stderr:
                stderr_text = result.stderr.decode('utf-8', errors='replace')

        if result.returncode != 0:
            # The archiver sometimes returns non-zero but still produces output.
            # Fall through and check file existence.
            pass

        if not archived_kfx_dir.exists() or not any(archived_kfx_dir.iterdir()):
            raise KFXKeyExtractorError(
                f"MSIX KFX archiver did not produce archived_kfx output. "
                f"returncode={result.returncode}")

        return {
            'output_dir': str(output_dir),
            'archived_kfx_dir': str(archived_kfx_dir),
            'k4i_file': str(k4i_file),
            'stdout': stdout_text,
            'stderr': stderr_text,
            'returncode': result.returncode
        }


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract KFX DRM keys using KFXKeyExtractor28.exe or MSIXKFXArchiver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kfx_key_extractor.py
  python kfx_key_extractor.py -d "C:\\Users\\User\\AppData\\Local\\Amazon\\Kindle\\My Kindle Content"
  python kfx_key_extractor.py -d "X:\\Kindle" -o keys.txt -k device.k4i
  python kfx_key_extractor.py --msix
  python kfx_key_extractor.py --msix -d "C:\\Users\\User\\AppData\\Local\\Packages\\AMZNKindle.AmazonKindleReadingApp_...\\LocalState\\Classic\\Content"
  python kfx_key_extractor.py --cleanup

Notes:
  - Legacy extractor requires Kindle.exe version 2.8.0(70980)
  - MSIX extractor requires Microsoft Store Kindle app
        """
    )

    parser.add_argument('-d', '--docs', metavar='PATH',
                        help='Path to Kindle documents folder (default: auto-detect)')
    parser.add_argument('-o', '--output', metavar='FILE',
                        help='Output file path (default: temp file)')
    parser.add_argument('-k', '--k4i', metavar='FILE',
                        help='Output k4i file path (default: temp file)')
    parser.add_argument('-e', '--extractor', metavar='PATH',
                        help='Path to KFXKeyExtractor28.exe (default: DeDRM_tools/KFXKeyExtractor28.exe)')
    parser.add_argument('--msix', action='store_true',
                        help='Use MSIXKFXArchiver for Microsoft Store Kindle')
    parser.add_argument('--msix-output-dir', metavar='DIR',
                        help='Output directory for MSIXKFXArchiver (default: current dir)')
    parser.add_argument('--cleanup', action='store_true',
                        help='Clean up temporary storage folder and exit')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    try:
        # Cleanup mode (legacy only)
        if args.cleanup and not args.msix:
            extractor = KFXKeyExtractor(args.extractor)
            if extractor.cleanup_temp_storage():
                print("Temporary storage folder cleaned up")
            else:
                print("No temporary storage folder found")
            return 0

        if args.msix:
            archiver = MSIXKFXArchiver(args.extractor)
            print("Extracting MS Store Kindle books...")
            if args.docs:
                print(f"  Kindle documents: {args.docs}")
            else:
                print("  Kindle documents: auto-detect")

            result = archiver.extract_keys(
                kindle_docs_path=args.docs,
                output_dir=args.msix_output_dir,
                k4i_file=args.k4i,
                capture_output=args.verbose
            )

            print("\nSuccess!")
            print(f"  Output dir: {result['output_dir']}")
            print(f"  Archived kfx dir: {result['archived_kfx_dir']}")
            print(f"  K4i file: {result['k4i_file']}")
            if args.verbose and result['stdout']:
                print(f"\nStdout:\n{result['stdout']}")
            if args.verbose and result['stderr']:
                print(f"\nStderr:\n{result['stderr']}")
            return 0

        extractor = KFXKeyExtractor(args.extractor)

        # Extract keys
        print("Extracting KFX keys...")
        if args.docs:
            print(f"  Kindle documents: {args.docs}")
        else:
            print("  Kindle documents: auto-detect")

        result = extractor.extract_keys(args.docs, args.output, args.k4i)

        print("\nSuccess!")
        print(f"  Output file: {result['output_file']}")
        print(f"  K4i file: {result['k4i_file']}")

        if args.verbose and result['stdout']:
            print(f"\nStdout:\n{result['stdout']}")
        if args.verbose and result['stderr']:
            print(f"\nStderr:\n{result['stderr']}")

        # Show k4i contents if verbose
        if args.verbose:
            print("\nK4i file contents:")
            print(extractor.read_k4i_file(result['k4i_file']))

        return 0

    except KFXKeyExtractorError as e:
        print(f"Error: {e}", file=__import__('sys').stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted", file=__import__('sys').stderr)
        return 2


if __name__ == '__main__':
    import sys
    sys.exit(main())
