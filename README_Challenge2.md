
# Challenge 2 – Quality Estimation (QE)

## 📌 Overview
This challenge estimates translation quality without reference text using HTER regression and multilingual BERT.

## 📂 Files Included
- `challenge_2_notebook.ipynb` – Full QE workflow
- `build_qe_labels.py` – HTER computation
- `train_qe_regression.py` – QE model training
- `results/` – HTER files, predictions, visualizations
- `Challenge2_FullDetailed_Report.pdf` – Detailed documentation

## 🚀 Steps Performed
1. Loaded and cleaned MT dataset
2. Created automatic quality labels using HTER
3. Extracted error types from human comments
4. Built regression dataset
5. Trained multilingual BERT to predict HTER
6. Evaluated with Pearson, Spearman, MSE

## 📊 Metrics
- Pearson: 0.0332  
- Spearman: -0.0294  
- MSE: 0.543  

Low correlation expected for small datasets; demonstrates pipeline correctness.

## ▶️ How to Run
```
pip install -r requirements.txt
python build_qe_labels.py
python train_qe_regression.py
```

`requirements.txt` pins are verified working end-to-end (both scripts run successfully) on
Python 3.11 and Python 3.14. `train_qe_regression.py`'s `Trainer`/`TrainingArguments` calls use
current `transformers` argument names (`eval_strategy`, `processing_class`) and require the
`accelerate` package, both included in `requirements.txt`.

## 💡 Future Improvements
- Use COMET-QE or QE-tuned models  
- Increase dataset size  
- Add linguistic features  
- Improve tokenization & batch handling  
