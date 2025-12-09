#!/usr/bin/env python3
"""
translate_and_evaluate.py

Translate English source sentences and compute evaluation metrics vs reference.

Approach:
 - Use an EncoderDecoderModel constructed from 'bert-base-multilingual-cased' 
   as encoder + decoder to avoid sentencepiece dependency.
 - Tokenize, generate predictions, compute sacrebleu, chrF, WER, CER.

Input:
 - Dataset_Challenge_1.xlsx (columns: src, tgt) or CSV with same columns.

Output:
 - translations.csv (src, pred, ref)
 - metrics printed to stdout
"""

import pandas as pd
import numpy as np
import argparse
import os
import torch
from transformers import EncoderDecoderModel, AutoTokenizer
import evaluate
import jiwer

def load_dataset(inpath):
    if inpath.endswith(".xlsx") or inpath.endswith(".xls"):
        df = pd.read_excel(inpath)
    else:
        df = pd.read_csv(inpath)
    # Try to find canonical column names
    colmap = {}
    for c in df.columns:
        low = c.strip().lower()
        if low in ["src", "source", "english source", "english"]:
            colmap[c] = "src"
        if low in ["tgt", "target", "reference", "reference translation", "ref"]:
            colmap[c] = "tgt"
    df = df.rename(columns=colmap)
    if "src" not in df.columns or "tgt" not in df.columns:
        raise KeyError("Input file must contain source and target columns (e.g., 'src' and 'tgt')")
    return df[["src", "tgt"]].dropna().reset_index(drop=True)

def compute_metrics(refs, hyps):
    bleu = evaluate.load("sacrebleu")
    chrf = evaluate.load("chrf")
    refs_nested = [[r] for r in refs]  # sacrebleu expects list of refs per hypothesis
    bleu_score = bleu.compute(predictions=hyps, references=refs_nested)["score"]
    chrf_score = chrf.compute(predictions=hyps, references=refs_nested)["score"]
    wer_score = jiwer.wer(refs, hyps)
    cer_score = jiwer.cer(refs, hyps)
    return {"bleu": bleu_score, "chrf": chrf_score, "wer": wer_score, "cer": cer_score}

def main(infile, out_csv, max_examples, batch_size, device_str):
    df = load_dataset(infile)

    if max_examples is not None and max_examples > 0:
        df = df.iloc[:max_examples].reset_index(drop=True)

    MODEL_NAME = "bert-base-multilingual-cased"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    # build encoder-decoder from same pretrained model (demo baseline)
    model = EncoderDecoderModel.from_encoder_decoder_pretrained(MODEL_NAME, MODEL_NAME)

    # Generation config
    model.config.decoder_start_token_id = tokenizer.cls_token_id
    model.config.eos_token_id = tokenizer.sep_token_id
    model.config.pad_token_id = tokenizer.pad_token_id
    device = torch.device(device_str if device_str else ("cuda" if torch.cuda.is_available() else "cpu"))
    model.to(device)
    model.eval()

    src_texts = df["src"].tolist()
    refs = df["tgt"].tolist()
    hyps = []

    def translate_batch(batch_texts):
        inputs = tokenizer(batch_texts, return_tensors="pt", padding=True, truncation=True, max_length=128)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_length=128,
                num_beams=1,
                decoder_start_token_id=model.config.decoder_start_token_id,
                eos_token_id=model.config.eos_token_id,
                pad_token_id=model.config.pad_token_id,
            )
        return tokenizer.batch_decode(out, skip_special_tokens=True)

    for i in range(0, len(src_texts), batch_size):
        batch = src_texts[i:i+batch_size]
        print(f"Translating {i}..{i+len(batch)-1}")
        preds = translate_batch(batch)
        hyps.extend(preds)

    # Save results
    out_df = pd.DataFrame({"src": src_texts, "pred": hyps, "ref": refs})
    out_df.to_csv(out_csv, index=False)
    print(f"Saved translations to {out_csv}")

    # Compute evaluation metrics
    metrics = compute_metrics(refs, hyps)
    print("Final Evaluation on provided dataset:")
    print(f"BLEU: {metrics['bleu']:.2f}")
    print(f"chrF: {metrics['chrf']:.2f}")
    print(f"WER: {metrics['wer']:.3f}")
    print(f"CER: {metrics['cer']:.3f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate and evaluate MT dataset (Challenge-1 baseline)")
    parser.add_argument("--input", "-i", default="Dataset_Challenge_1.xlsx", help="Input file (xlsx/csv) with src/tgt")
    parser.add_argument("--out", "-o", default="translations.csv", help="Output CSV for predictions")
    parser.add_argument("--max_examples", type=int, default=0, help="Limit number of examples (0 = all)")
    parser.add_argument("--batch_size", type=int, default=8, help="Batch size for generation")
    parser.add_argument("--device", type=str, default="", help="Device string, e.g., 'cpu' or 'cuda:0' (auto if empty)")
    args = parser.parse_args()
    main(args.input, args.out, args.max_examples if args.max_examples>0 else None, args.batch_size, args.device)
