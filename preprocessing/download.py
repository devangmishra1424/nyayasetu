"""
Download Indian Supreme Court judgments from Kaggle.
Uses kagglehub to download directly - no manual zip extraction needed.
Output: data/raw_judgments.jsonl

WHY kagglehub? Programmatic download - reproducible, no manual steps.
Anyone cloning this repo can run this script and get the same data.
"""

import kagglehub
import json
import os
import glob

def download_judgments():
    print("Downloading SC Judgments dataset from Kaggle...")
    
    # Downloads to a local cache folder, returns the path
    path = kagglehub.dataset_download("adarshsingh0903/legal-dataset-sc-judgments-india-19502024")
    print(f"Dataset downloaded to: {path}")
    
    # See what files we got
    all_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            full_path = os.path.join(root, file)
            all_files.append(full_path)
            print(f"  Found: {full_path}")
    
    print(f"\nTotal files found: {len(all_files)}")
    return path, all_files

if __name__ == "__main__":
    path, files = download_judgments()