# Baseline

Measured on the current version before the Phase 1 changes, so every later phase can be compared
on the same 10 questions. Re-run from `backend/` with:

```powershell
.\.venv\Scripts\python.exe -m scripts.baseline --questions ../docs/private/baseline/questions.yaml --json ../docs/private/baseline/<date>.json
```

The questions, expected answers and full model answers quote personal documents, so they live in
`docs/private/baseline/` (git-ignored). This file keeps only the numbers and a neutral label per question.

## Machine

- CPU: Intel Core i7-12650H (10 cores / 16 threads)
- RAM: 24 GB
- GPU: NVIDIA GeForce RTX 3050 Laptop 6 GB (driver 610.62), plus Intel UHD
- Disk: MSI M450 1 TB NVMe SSD (project drive), HS-SSD-E100 512 GB SSD
- OS: Windows 11 Pro 10.0.26200
- Python 3.12.10 · Ollama 0.20.3
- Power: plugged in, Windows "Balanced" power plan

## Run 1 — 2026-10-07 · commit 6df2df6

- Folder: one real folder of personal documents (resume, motivation letter, two recommendation letters): 5 files, 18 chunks
- Models: chat `qwen3:4b-instruct` (Q4_K_M), embeddings `nomic-embed-text`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Cold start (first question after launch): retrieval 88.7 s, first token 10.6 s, total 10.6 s

| # | Question | Kind | Retrieval s | First token s | Total s | Backend MB | Correct |
|---|---|---|---|---|---|---|---|
| b01 | Current employer | fact | 2.90 | 6.38 | 8.06 | 1483 | ❌ |
| b02 | Who supervised an internship, and where they work | fact | 2.95 | 6.90 | 7.66 | 1471 | ✅ |
| b03 | Course taught by a referee | fact | 2.93 | 6.47 | 6.87 | 1473 | ✅ |
| b04 | A percentage from the resume | exact | 2.92 | 6.73 | 7.12 | 1472 | ✅ |
| b05 | Exact project title | exact | 2.95 | 6.75 | 7.46 | 1473 | ✅ |
| b06 | Who a letter is addressed to | fact | 2.94 | 7.55 | 8.09 | 1472 | ✅ |
| b07 | Summarise one internship | summary | 2.94 | 6.82 | 11.37 | 1467 | ✅ |
| b08 | Qualities both recommendation letters share | multi-file | 2.95 | 6.66 | 10.40 | 1467 | ⚠️ |
| b09 | Summarise a letter in three sentences | summary | 2.90 | 6.21 | 8.77 | 1479 | ✅ |
| b10 | A grade that is not in the folder | absent | 2.97 | 6.35 | 7.25 | 1485 | ✅ |

Correct: ✅ right answer from the right file · ⚠️ partly right, or right answer from the wrong source · ❌ wrong or invented

**Summary:** 8/10 correct, 1 partly right, 1 wrong · median first token 6.70 s · median total 7.86 s ·
max total 11.37 s · backend peak 1530 MB · chat model 3406 MB and embedding model 568 MB in Ollama, both 100 % on GPU

How to read the timings: retrieval is timed with its own call, and the answer then retrieves again,
so "first token" includes a second retrieval (~2.9 s). The model itself takes about 3.8 s to its first token.

### Observations

- **Cold start is slow:** the first retrieval after launch took 89 s, about 30 times longer than a
  warm one. Most of this is probably loading the reranker and the embedding model.
- **Retrieval takes ~2.9 s even when warm,** on only 18 chunks, and the time barely changes from
  question to question. That points to a fixed per-query cost rather than search work.
- **b01 is wrong because the model doesn't know today's date.** It treated a job that started in
  09/2026 as being in the future and said there was no current job.
- **b08 overstates overlap:** it listed qualities as shared by both letters when each appears in only one.
- **Sources are imprecise:** almost every answer lists 3–4 files, including unrelated ones (for example,
  recommendation letters are cited for a figure that only appears in the resume).
- The question about missing information (b10) was answered correctly: the assistant said it could
  not find the information instead of making it up.
- The index is behind the folder: 3 newer files and a scanned transcript are not indexed.
