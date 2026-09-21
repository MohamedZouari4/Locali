"""
LOCALI — retrieval evaluation  (EXP-009 / EXP-010, gates LOC-48)

Compares two orderings of the SAME candidate set:
    baseline  = hybrid merge order            (P2-E3-T2)
    reranked  = cross-encoder order           (P2-E3-T3)

Retrieval runs once per query and both arms score that one candidate list.
Re-running retrieval per arm would introduce differences unrelated to reranking.

Usage:
    python eval_retrieval.py pool  --fixtures fixtures/retrieval_eval.yaml
    python eval_retrieval.py run   --fixtures fixtures/retrieval_eval.yaml
    python eval_retrieval.py run   --fixtures ... --json results/run-01.json

`pool` emits an unlabelled candidate pool for judging. `run` evaluates.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# ADAPTER — the only block you should need to edit.
# Point these at whatever P2-E3-T1/T2 actually named things.
# ---------------------------------------------------------------------------

from app.AI.retrieval.hybrid_retriever import hybrid_search  # noqa: E402  -> merged candidates
from app.AI.retrieval.reranker import rerank, warmup  # noqa: E402
from app.config import RERANK_CANDIDATES  # noqa: E402


def fetch_candidates(query: str, k: int):
    """Return the merged candidate list for a query, in P2-E3-T2 order."""
    return hybrid_search(query, k=k)


def source_of(candidate) -> str:
    """Source file for a candidate, normalised to forward slashes.

    Labels are at file level, not chunk level: chunk IDs die on every
    re-chunk, file paths survive the chunking and TOP_K experiments.
    """
    if isinstance(candidate, (tuple, list)):
        raw = candidate[1] if len(candidate) > 1 else ""
    elif isinstance(candidate, dict):
        raw = (candidate.get("source")
               or candidate.get("path")
               or (candidate.get("metadata") or {}).get("source")
               or (candidate.get("metadata") or {}).get("path")
               or "")
    else:
        raw = (getattr(candidate, "source", None)
               or getattr(candidate, "path", None)
               or "")
    return str(raw).replace("\\", "/").lstrip("./")


def text_of(candidate) -> str:
    if isinstance(candidate, (tuple, list)):
        return str(candidate[0]) if candidate else ""
    if isinstance(candidate, dict):
        return candidate.get("text") or candidate.get("document") or ""
    return getattr(candidate, "text", "") or ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def load_fixtures(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            sys.exit("pyyaml not installed — python -m pip install pyyaml, "
                     "or use a .json fixture file")
        items = yaml.safe_load(raw)
    else:
        items = json.loads(raw)

    for item in items:
        item.setdefault("kind", "semantic")
        item["relevant"] = [str(r).replace("\\", "/").lstrip("./")
                            for r in item.get("relevant", [])]
    return items


def matches(candidate_source: str, labelled: str) -> bool:
    """Tolerant path match. Exact wins; otherwise a suffix match, so
    'src/tools.py' in the labels finds 'D:/DEV/Locali/src/tools.py'.

    Suffix matching can collide when two files share a tail (a/utils.py vs
    b/utils.py). If your tree has those, label full paths and tighten this
    to equality.
    """
    if not candidate_source or not labelled:
        return False
    if candidate_source == labelled:
        return True
    return candidate_source.endswith("/" + labelled) or labelled.endswith("/" + candidate_source)


def relevant_ranks(ordering, relevant_files) -> list[int]:
    """1-based ranks at which a relevant FILE first appears.

    Deduplicated by file: two chunks from tools.py are one hit, not two,
    otherwise a chunky file inflates the score for free.
    """
    seen, ranks = set(), []
    for position, candidate in enumerate(ordering, start=1):
        src = source_of(candidate)
        for label in relevant_files:
            if label in seen:
                continue
            if matches(src, label):
                seen.add(label)
                ranks.append(position)
    return sorted(ranks)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def hit_at(ranks: list[int], k: int) -> float:
    return 1.0 if ranks and ranks[0] <= k else 0.0


def reciprocal_rank(ranks: list[int]) -> float:
    """The metric reranking should move most — its job is lifting a result
    that was already retrieved, not finding new ones."""
    return 1.0 / ranks[0] if ranks else 0.0


def sign_test(improved: int, regressed: int) -> float:
    """Two-sided sign test on per-query MRR deltas. Ties excluded.

    Answers the question the means hide: is 9-vs-3 a real effect or a
    coin landing heads a few extra times?
    """
    n = improved + regressed
    if n == 0:
        return 1.0
    extreme = min(improved, regressed)
    tail = sum(math.comb(n, i) for i in range(extreme + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


# ---------------------------------------------------------------------------
# pool — unlabelled candidates for judging
# ---------------------------------------------------------------------------

def cmd_pool(args):
    fixtures = load_fixtures(Path(args.fixtures))
    out_lines = []

    for item in fixtures:
        candidates = fetch_candidates(item["query"], RERANK_CANDIDATES)
        reranked = rerank(item["query"], candidates, top_n=len(candidates))

        # Union of both arms, shuffled. Judging in either system's order
        # biases the labels toward that system.
        pool = {source_of(c) for c in candidates} | {source_of(c) for c in reranked}
        pool = sorted(p for p in pool if p)
        random.shuffle(pool)

        out_lines.append(f"\n# {item['id']} [{item['kind']}]  {item['query']}")
        out_lines.append("#   mark relevant files, then copy into the fixture's `relevant:` list")
        out_lines += [f"#     [ ] {p}" for p in pool]

    text = "\n".join(out_lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"pool written to {args.out}  ({len(fixtures)} queries)")
    else:
        print(text)


# ---------------------------------------------------------------------------
# run — the comparison
# ---------------------------------------------------------------------------

def cmd_run(args):
    fixtures = load_fixtures(Path(args.fixtures))
    answerable = [f for f in fixtures if f["relevant"]]
    absent = [f for f in fixtures if not f["relevant"]]

    if len(answerable) < 30:
        print(f"! only {len(answerable)} answerable queries — below ~30 you cannot "
              f"separate an improvement from noise\n", file=sys.stderr)

    warmup()

    rows, latencies, absent_scores = [], [], []

    for item in fixtures:
        candidates = fetch_candidates(item["query"], RERANK_CANDIDATES)
        if not candidates:
            print(f"! {item['id']}: retrieval returned nothing", file=sys.stderr)
            continue

        started = time.perf_counter()
        reranked = rerank(item["query"], candidates, top_n=len(candidates))
        latencies.append((time.perf_counter() - started) * 1000)

        if not item["relevant"]:
            # Nothing to rank. What matters for an absent query is whether the
            # top score is low enough to abstain on later — collect, don't score.
            absent_scores.append((item["id"], source_of(reranked[0]) if reranked else ""))
            continue

        base_ranks = relevant_ranks(candidates, item["relevant"])
        rr_ranks = relevant_ranks(reranked, item["relevant"])

        rows.append({
            "id": item["id"],
            "kind": item["kind"],
            "query": item["query"],
            "base": {"hit1": hit_at(base_ranks, 1), "hit3": hit_at(base_ranks, 3),
                     "hit5": hit_at(base_ranks, 5), "mrr": reciprocal_rank(base_ranks),
                     "first_rank": base_ranks[0] if base_ranks else None},
            "rerank": {"hit1": hit_at(rr_ranks, 1), "hit3": hit_at(rr_ranks, 3),
                       "hit5": hit_at(rr_ranks, 5), "mrr": reciprocal_rank(rr_ranks),
                       "first_rank": rr_ranks[0] if rr_ranks else None},
        })

    if not rows:
        sys.exit("no answerable queries produced results")

    def mean(arm, metric):
        return sum(r[arm][metric] for r in rows) / len(rows)

    improved = [r for r in rows if r["rerank"]["mrr"] > r["base"]["mrr"]]
    regressed = [r for r in rows if r["rerank"]["mrr"] < r["base"]["mrr"]]
    unchanged = len(rows) - len(improved) - len(regressed)
    p = sign_test(len(improved), len(regressed))

    print(f"\n{len(rows)} answerable queries · {len(absent)} absent · "
          f"candidate set {RERANK_CANDIDATES}\n")
    print(f"{'metric':<10}{'baseline':>10}{'reranked':>10}{'delta':>10}")
    print("-" * 40)
    for metric, label in (("hit1", "Hit@1"), ("hit3", "Hit@3"),
                          ("hit5", "Hit@5"), ("mrr", "MRR")):
        b, r = mean("base", metric), mean("rerank", metric)
        print(f"{label:<10}{b:>10.3f}{r:>10.3f}{r - b:>+10.3f}")

    # Recall at the candidate-set size is identical by construction —
    # reranking reorders, it cannot add. Reporting it would be theatre.

    print(f"\nlatency   median {statistics.median(latencies):>6.0f} ms   "
          f"max {max(latencies):>6.0f} ms")
    print(f"\nimproved {len(improved)}   regressed {len(regressed)}   "
          f"unchanged {unchanged}   (sign test p={p:.3f})")
    if p > 0.05:
        print("          -> not distinguishable from noise at this sample size")

    print("\nby kind:")
    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    for kind, group in sorted(by_kind.items()):
        b = sum(x["base"]["hit3"] for x in group) / len(group)
        rr = sum(x["rerank"]["hit3"] for x in group) / len(group)
        flag = "  <-- regression" if rr < b else ""
        print(f"  {kind:<14} n={len(group):<4} Hit@3 {b:.2f} -> {rr:.2f}{flag}")
    print("  exact_term is the one to watch: cross-encoders are trained on prose\n"
          "  passage ranking and can rank a paragraph ABOUT a function above the\n"
          "  function itself.")

    if regressed:
        print("\nregressions:")
        for r in sorted(regressed, key=lambda x: x["base"]["mrr"] - x["rerank"]["mrr"],
                        reverse=True):
            print(f"  {r['id']} [{r['kind']}] rank {r['base']['first_rank']} "
                  f"-> {r['rerank']['first_rank']}   {r['query'][:60]}")

    if absent_scores:
        print(f"\nabsent queries (excluded from means — nothing to rank).")
        print("  Reranking assigns scores to noise too. Use these to pick an")
        print("  abstention threshold later:")
        for qid, top in absent_scores[:5]:
            print(f"    {qid}  top result: {top or '(none)'}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "candidates": RERANK_CANDIDATES,
            "n_answerable": len(rows),
            "summary": {m: {"base": mean("base", m), "rerank": mean("rerank", m)}
                        for m in ("hit1", "hit3", "hit5", "mrr")},
            "latency_ms": {"median": statistics.median(latencies), "max": max(latencies)},
            "improved": len(improved), "regressed": len(regressed),
            "unchanged": unchanged, "sign_test_p": p,
            "queries": rows,
        }, indent=2), encoding="utf-8")
        print(f"\nwritten to {args.json}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pool = sub.add_parser("pool", help="emit unlabelled candidates for judging")
    p_pool.add_argument("--fixtures", required=True)
    p_pool.add_argument("--out")
    p_pool.set_defaults(func=cmd_pool)

    p_run = sub.add_parser("run", help="baseline vs reranked")
    p_run.add_argument("--fixtures", required=True)
    p_run.add_argument("--json", help="also write full results here")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()