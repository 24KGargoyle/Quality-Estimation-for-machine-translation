#!/usr/bin/env python3
"""
train_qe_regression.py

Train a regression QE model to predict HTER (hter_label) using a multilingual BERT encoder.

Inputs:
 - qe_dataset_with_hter.csv (must contain input fields src_en, mt_es, hter_label)

Outputs:
 - Saved model directory (./qe_mbert_regression by default)
 - Predictions CSV on held-out eval set (qe_eval_predictions.csv)
"""

import pandas as pd
import numpy as np
import argparse
import os
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
)
import torch

def pearsonr_manual(a, b):
    a = np.array(a); b = np.array(b)
    if a.size == 0: return 0.0
    if np.std(a) == 0 or np.std(b) == 0: return 0.0
    return float(np.corrcoef(a, b)[0,1])

def spearmanr_manual(a, b):
    import pandas as pd
    a_rank = pd.Series(a).rank().to_numpy()
    b_rank = pd.Series(b).rank().to_numpy()
    if np.std(a_rank) == 0 or np.std(b_rank) == 0: return 0.0
    return float(np.corrcoef(a_rank, b_rank)[0,1])

def compute_metrics(eval_pred):
    preds, labels = eval_pred
    preds = np.array(preds).squeeze()
    labels = np.array(labels).squeeze()
    mse = float(np.mean((preds - labels)**2))
    pearson = pearsonr_manual(preds, labels)
    spearman = spearmanr_manual(preds, labels)
    return {"pearson": pearson, "spearman": spearman, "mse": mse}

def main(infile, model_out_dir, epochs, batch_size, lr):
    if not os.path.exists(infile):
        raise FileNotFoundError(f"Input file not found: {infile}")

    df = pd.read_csv(infile)
    # rename if needed
    if "src_en" not in df.columns:
        for c in df.columns:
            if "english" in c.lower() and "source" in c.lower():
                df = df.rename(columns={c: "src_en"})
    if "mt_es" not in df.columns:
        for c in df.columns:
            if "mt" in c.lower() or "machine" in c.lower():
                df = df.rename(columns={c: "mt_es"})
    if "hter_label" not in df.columns:
        raise KeyError("hter_label column not found in input CSV.")

    # Build input_text
    df["input_text"] = df.apply(lambda r: f"EN: {r['src_en']}\nES_MT: {r['mt_es']}", axis=1)

    dataset = Dataset.from_pandas(df[["input_text", "hter_label"]])
    splits = dataset.train_test_split(test_size=0.2, seed=42)
    train_ds = splits["train"]
    eval_ds = splits["test"]

    MODEL_NAME = "bert-base-multilingual-cased"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    def tokenize(batch):
        out = tokenizer(batch["input_text"], truncation=True, padding="max_length", max_length=256)
        out["labels"] = batch["hter_label"]
        return out

    tokenized_train = train_ds.map(tokenize, batched=True, remove_columns=["input_text","hter_label"])
    tokenized_eval = eval_ds.map(tokenize, batched=True, remove_columns=["input_text","hter_label"])

    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=1, problem_type="regression")

    training_args = TrainingArguments(
        output_dir=model_out_dir,
        evaluation_strategy="epoch" if "evaluation_strategy" in TrainingArguments.__init__.__code__.co_varnames else "no",
        learning_rate=lr,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        num_train_epochs=epochs,
        weight_decay=0.01,
        logging_steps=10,
        save_total_limit=1,
        fp16=torch.cuda.is_available()
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_eval,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(model_out_dir)

    # Predictions on eval set
    preds_output = trainer.predict(tokenized_eval)
    preds = np.array(preds_output.predictions).squeeze()
    labels = np.array(preds_output.label_ids).squeeze()

    # Build eval CSV
    eval_texts = splits["test"]["input_text"]
    eval_df = pd.DataFrame({"input_text": eval_texts, "hter_true": labels, "hter_pred": preds})
    eval_df.to_csv("qe_eval_predictions.csv", index=False)
    print("Saved qe_eval_predictions.csv")
    print("Final eval metrics:", compute_metrics((preds, labels)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train QE regression model")
    parser.add_argument("--input", "-i", default="qe_dataset_with_hter.csv")
    parser.add_argument("--out", "-o", default="./qe_mbert_regression")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5)
    args = parser.parse_args()
    main(args.input, args.out, args.epochs, args.batch_size, args.lr)
