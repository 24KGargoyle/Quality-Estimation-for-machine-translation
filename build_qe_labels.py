#!/usr/bin/env python3
"""
build_qe_labels.py

Compute HTER-like labels (approx) for QE:
HTER ≈ WER(PostEdit, MT)

Input: Dataset_Challenge_2.xlsx with columns:
  - English Source
  - MT System
  - Post-Edit Text
  - Nature of change/Comments (optional)

Output:
  - qe_dataset_with_hter.csv (adds columns src_en, mt_es, pe_es, comments, hter_label)
"""

import pandas as pd
import jiwer
import argparse
import os

def sentence_ter(mt, pe):
    # Approximate HTER using word-level WER between Post-Edit (reference) and MT (hypothesis)
    try:
        return jiwer.wer(str(pe), str(mt))
    except Exception:
        return 1.0  # fallback high error if something unexpected

def main(infile, outfile):
    if not os.path.exists(infile):
        raise FileNotFoundError(f"Input file not found: {infile}")

    df = pd.read_excel(infile)

    # Normalize column names and map to our expected names
    colmap = {}
    for c in df.columns:
        low = c.strip().lower()
        if "english" in low and "source" in low:
            colmap[c] = "src_en"
        elif "mt" in low or "machine" in low:
            colmap[c] = "mt_es"
        elif "post" in low or "post-edit" in low or "post edit" in low:
            colmap[c] = "pe_es"
        elif "comment" in low or "nature" in low or "change" in low:
            colmap[c] = "comments"

    df = df.rename(columns=colmap)

    # Ensure required columns exist
    required = ["src_en", "mt_es", "pe_es"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Required columns missing in input file: {missing}. Found columns: {list(df.columns)}")

    # Drop rows with missing core data
    df = df.dropna(subset=["src_en", "mt_es", "pe_es"]).reset_index(drop=True)

    # Compute hter labels
    df["hter_label"] = df.apply(lambda r: sentence_ter(r["mt_es"], r["pe_es"]), axis=1)

    # Save csv
    df.to_csv(outfile, index=False)
    print(f"Saved QE dataset with HTER to: {outfile}")
    print(df[["src_en", "mt_es", "pe_es", "hter_label"]].head())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build QE HTER labels from Challenge 2 Excel.")
    parser.add_argument("--input", "-i", default="Dataset_Challenge_2.xlsx", help="Input Excel file path")
    parser.add_argument("--output", "-o", default="qe_dataset_with_hter.csv", help="Output CSV path")
    args = parser.parse_args()
    main(args.input, args.output)
