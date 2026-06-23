# Installing TimesFM 2.5 (the real model)

Two gotchas you already hit:

1. **TimesFM 2.5 is not on PyPI.** `pip install timesfm` installs the old 1.x/2.0
   packages. Version 2.5 must be installed **from the GitHub source**.
2. **Python 3.14 won't work.** PyTorch publishes no 3.14 wheels yet, and TimesFM
   targets Python **3.10–3.12**. Use a 3.11 or 3.12 environment.

The baseline forecaster (`--forecaster baseline`) needs none of this — it runs on
your current Python. Everything below is only for `--forecaster timesfm`.

---

## Windows (PowerShell)

If you don't have Python 3.11/3.12, install one first:
`winget install Python.Python.3.12`  (or download from python.org).

```powershell
cd "C:\Users\Hashim\Desktop\GOLD_CRT_ICT_PD_Array_Strategy\Fable 5 improved strategy\timesfm_direction_test"

# 1) make a dedicated 3.12 virtual env (keeps it away from your 3.14)
py -3.12 -m venv .venv-tfm
.\.venv-tfm\Scripts\Activate.ps1

# 2) core deps + a CPU build of torch (CPU is fine for inference)
python -m pip install --upgrade pip
pip install pandas numpy pyarrow
pip install torch                      # CPU build; for GPU see pytorch.org/get-started

# 3) TimesFM 2.5 FROM SOURCE (requires git installed)
pip install "timesfm[torch] @ git+https://github.com/google-research/timesfm.git"

# 4) run it on your real data
python run_tfm.py --forecaster timesfm
```

No git? Clone-and-install instead of step 3:

```powershell
git clone https://github.com/google-research/timesfm.git C:\tmp\timesfm
pip install -e "C:\tmp\timesfm[torch]"
```

(Or download the repo ZIP from GitHub, extract, and `pip install -e <folder>[torch]`.)

---

## First run

The first `--forecaster timesfm` run downloads the checkpoint
`google/timesfm-2.5-200m-pytorch` from HuggingFace (a few hundred MB, once). You
need internet access for that download; after it's cached, runs are offline.

## Sanity check before the full run

```powershell
python -c "import timesfm, torch; print('timesfm', timesfm.__version__, '| torch', torch.__version__)"
python smoke_test.py        # still uses the baseline; just proves imports/wiring
```

## Getting a usable sample size

The default confidence gate is strict (you saw N=4 per test cell with the
baseline). To get more trades once TimesFM is driving direction:

```powershell
python run_tfm.py --forecaster timesfm --min-move-frac 0.0005      # looser gate
python run_tfm.py --forecaster timesfm --ltf m5                    # more entries
python run_tfm.py --forecaster timesfm --symbol GBPUSD            # second symbol
```

Judge every config on the untouched **test** column (2025-01-01 →), net of costs.
