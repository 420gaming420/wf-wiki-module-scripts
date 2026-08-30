#!/usr/bin/env python3
"""
Debug script to test path resolution for request.py
"""

from pathlib import Path
import json


def main():
    print("=== Python path test ===")
    print(f"CWD: {Path.cwd()}")
    
    metadata_dir = Path("data/json")
    print(f"data/json exists: {metadata_dir.exists()}")
    print(f"data/json resolved: {metadata_dir.resolve()}")
    
    meta_files = list(metadata_dir.glob("*.meta.json")) if metadata_dir.exists() else []
    print(f"Files found: {len(meta_files)}")
    
    sample_file = Path("data/json/Module-Ability-Conclave-data.meta.json")
    print(f"Sample file exists: {sample_file.exists()}")
    
    if sample_file.exists():
        with open(sample_file, 'r') as f:
            data = json.load(f)
        print(f"Sample file content: {json.dumps(data, indent=2)}")
    
    # Also test with absolute path
    abs_path = Path("/tmp/scripts/data/json")
    print(f"\n=== Absolute path test ===")
    print(f"Absolute path exists: {abs_path.exists()}")
    print(f"Absolute path resolved: {abs_path.resolve()}")
    abs_files = list(abs_path.glob("*.meta.json")) if abs_path.exists() else []
    print(f"Absolute path files found: {len(abs_files)}")


if __name__ == "__main__":
    main()
