"""Compare ways of framing a question for a model's answer, live.

    python scripts/measure_answer_prompts.py [--model olmo3-7b] [--repeats 6]

For each frame, every question is asked `repeats` times with ONE attempt
(no retry), so the numbers are per-completion. Reports how often the model
skipped the answer (answer_only came back empty) and, for questions with a
known answer, how often the answer was right. A frame is only worth
adopting if it answers more often without answering worse.
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_brain.model_backed_reasoning import ANSWER_FRAME, DEFAULT_MODEL, ask_model  # noqa: E402

FRAMES = {
    "current": ANSWER_FRAME,
    "question-answer": "Question: {question}\nAnswer:",
    "one-line": "Answer the question in one short line.\nQ: {question}\nA:",
    "one-shot": "Q: What is the capital of France?\nA: Paris\nQ: {question}\nA:",
}

# (question, pattern a right answer matches, or None where only the skip rate is measured)
QUESTIONS = [
    ("what force holds the moon in orbit?", r"gravit"),
    ("what force acts on a stationary object?", None),   # the question that skipped 3 times in 12 (batch 10)
    ("what is the chemical symbol for gold?", r"\bAu\b"),
    ("which planet is known as the red planet?", r"mars"),
    ("who wrote Hamlet?", r"shakespeare"),
    ("what gas do plants absorb from the air for photosynthesis?", r"carbon dioxide|co2|co₂"),
    ("what is the largest ocean on Earth?", r"pacific"),
    ("what organ pumps blood through the body?", r"heart"),
    ("how many sides does a hexagon have?", r"\b6\b|six"),
    ("why is the sky blue?", None),
]


def measure(model: str, repeats: int, frames: dict = FRAMES) -> dict:
    results = {}
    for name, frame in frames.items():
        asked = skipped = judged = right = 0
        started = time.time()
        for question, pattern in QUESTIONS:
            for _ in range(repeats):
                answer = ask_model(question, model, frame=frame, max_attempts=1)
                asked += 1
                if not answer:
                    skipped += 1
                    continue
                if pattern is not None:
                    judged += 1
                    right += bool(re.search(pattern, answer, re.IGNORECASE))
        results[name] = r = {"asked": asked, "skipped": skipped, "judged": judged, "right": right,
                             "seconds": round(time.time() - started, 1)}
        # as each frame finishes, so a long live run shows its progress
        print(f"{name:16} skipped {r['skipped']:3}/{r['asked']} ({r['skipped'] / r['asked']:.0%})  "
              f"right {r['right']:3}/{r['judged']} ({r['right'] / max(r['judged'], 1):.0%})  {r['seconds']}s",
              flush=True)
    return results


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--repeats", type=int, default=6)
    args = p.parse_args(argv)
    return measure(args.model, args.repeats)


if __name__ == "__main__":
    main()
