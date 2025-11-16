#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
KFXKeyExtractor28.exe wrapper for extracting KFX DRM keys
"""

import os
import subprocess
import tempfile
from pathlib import Path

__license__ = 'GPL v3'
__version__ = "0.1"


class KFXKeyExtractorError(Exception):
    """KFX key extraction failed"""
    pass


class KFXKeyExtractor:
    """Wrapper for KFXKeyExtractor28.exe"""
    
    def __init__(self, extractor_path=None):
        """
        Initialize KFX key extractor
        
        Args:
            extractor_path: Path to KFXKeyExtractor28.exe (default: DeDRM_tools/KFXKeyExtractor28.exe)
        """
        if extractor_path is None:
            script_dir = Path(__file__).parent
            extractor_path = script_dir / "DeDRM_tools" / "KFXKeyExtractor28.exe"
        
        self.extractor_path = Path(extractor_path)
        if not self.extractor_path.exists():
            raise KFXKeyExtractorError(f"KFXKeyExtractor28.exe not found: {self.extractor_path}")
    
    def extract_keys(self, kindle_docs_path, output_file=None, k4i_file=None):
        """
        Extract KFX keys using KFXKeyExtractor28.exe
        
        Args:
            kindle_docs_path: Path to Kindle documents folder (with _EBOK folders)
            output_file: Output file path (optional, uses temp if None)
            k4i_file: Output k4i file path (optional, uses temp if None)
        
        Returns:
            dict with keys 'output_file', 'k4i_file', 'stdout', 'stderr'
        
        Raises:
            KFXKeyExtractorError: If extraction fails
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
        
        # Build command
        cmd = [
            str(self.extractor_path),
            str(kindle_docs_path),
            str(output_file),
            str(k4i_file)
        ]
        
        try:
            # Run extractor
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            
            # Check for success
            if result.returncode != 0:
                error_msg = f"KFXKeyExtractor28.exe failed with code {result.returncode}"
                if result.stderr:
                    error_msg += f"\nStderr: {result.stderr}"
                raise KFXKeyExtractorError(error_msg)
            
            # Verify outputs exist
            if not output_file.exists():
                raise KFXKeyExtractorError(f"Output file not created: {output_file}")
            if not k4i_file.exists():
                raise KFXKeyExtractorError(f"K4i file not created: {k4i_file}")
            
            return {
                'output_file': str(output_file),
                'k4i_file': str(k4i_file),
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        
        except subprocess.TimeoutExpired:
            raise KFXKeyExtractorError("KFXKeyExtractor28.exe timed out after 5 minutes")
        except Exception as e:
            # Clean up temp files on error
            if cleanup_output and output_file.exists():
                output_file.unlink()
            if cleanup_k4i and k4i_file.exists():
                k4i_file.unlink()
            raise KFXKeyExtractorError(f"Failed to run KFXKeyExtractor28.exe: {e}")
    
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


def main():
    """Command-line interface"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract KFX DRM keys using KFXKeyExtractor28.exe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kfx_key_extractor.py
  python kfx_key_extractor.py -d "C:\\Users\\User\\AppData\\Local\\Amazon\\Kindle\\My Kindle Content"
  python kfx_key_extractor.py -d "X:\\Kindle" -o keys.txt -k device.k4i
  python kfx_key_extractor.py --cleanup

Notes:
  - At least one KFX book using account secrets must be downloaded for proper k4i generation
  - Requires Kindle.exe version 2.8.0(70980) with md5 93fce0fedb6cd17514f9a72f963dbdba
  - Creates temporary /storage folder in %LOCALAPPDATA% (use --cleanup to remove)
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
    parser.add_argument('--cleanup', action='store_true',
                        help='Clean up temporary storage folder and exit')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    try:
        extractor = KFXKeyExtractor(args.extractor)
        
        # Cleanup mode
        if args.cleanup:
            if extractor.cleanup_temp_storage():
                print("Temporary storage folder cleaned up")
            else:
                print("No temporary storage folder found")
            return 0
        
        # Extract keys
        print(f"Extracting KFX keys...")
        if args.docs:
            print(f"  Kindle documents: {args.docs}")
        else:
            print(f"  Kindle documents: auto-detect")
        
        result = extractor.extract_keys(args.docs, args.output, args.k4i)
        
        print(f"\nSuccess!")
        print(f"  Output file: {result['output_file']}")
        print(f"  K4i file: {result['k4i_file']}")
        
        if args.verbose and result['stdout']:
            print(f"\nStdout:\n{result['stdout']}")
        if args.verbose and result['stderr']:
            print(f"\nStderr:\n{result['stderr']}")
        
        # Show k4i contents if verbose
        if args.verbose:
            print(f"\nK4i file contents:")
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
