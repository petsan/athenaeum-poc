"""Run the judging benchmark (owner decision 11) against a live model.

    python scripts/run_judging_benchmark.py [--model olmo3-7b] [--repeats 2] [--record DATA_DIR]

Prints the score and every miss. With --record, appends the result to that
data dir's model-fitness store (the API's is data/api-run), which is what
decides whether the model's re-examination challenges count: only a score
at or above the threshold, for the current benchmark and prompt versions.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_body.storage.content_addressed import ContentAddressedStore  # noqa: E402
from athenaeum_body.storage.checkpoint import CheckpointLog  # noqa: E402
from athenaeum_body.model_fitness_store import ModelFitnessStore  # noqa: E402
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL  # noqa: E402
from athenaeum_brain.judging_benchmark import run_benchmark, challenger_qualified  # noqa: E402


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--record", type=Path, default=None, help="data dir whose model-fitness store records the result")
    args = p.parse_args(argv)
    result = run_benchmark(args.model, repeats=args.repeats)
    print(f"{args.model}: {result['correct']}/{result['total']} = {result['accuracy']:.0%} "
          f"(needs {result['threshold']:.0%}) -> {'QUALIFIES' if result['passed'] else 'does not qualify'}")
    for miss in result["misses"]:
        truth = "correct" if miss["is_correct"] else "incorrect"
        print(f"  miss: {miss['judged']} the {truth} answer {miss['answer']!r} to {miss['question']!r}")
    if args.record:
        store = ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(args.record / "cas"),
                                                index_path=args.record / "model-fitness.txt"))
        store.record_judging(args.model, result)
        print("recorded; challenges now count?", challenger_qualified(store, args.model))
    return result


if __name__ == "__main__":
    main()
