"""Repeat regression and UI journeys until interrupted by the operator."""
from datetime import datetime
from pathlib import Path
import json
import os
import random
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data" / "private" / "continuous_qa"
OUTPUT.mkdir(parents=True, exist_ok=True)
(OUTPUT / "process.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


if "--cycle" in sys.argv:
    seed = int(sys.argv[-1])
    tests = list(flatten(unittest.defaultTestLoader.discover(str(ROOT / "tests"))))
    random.Random(seed).shuffle(tests)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
    raise SystemExit(0 if result.wasSuccessful() else 1)

cycle = 0
while True:
    cycle += 1
    started = datetime.now().isoformat(timespec="seconds")
    print(f"Starting QA cycle {cycle}: fresh process, shuffled order", flush=True)
    with (OUTPUT / f"cycle-{cycle:04d}.txt").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--cycle", str(cycle)],
                                stdout=log, stderr=subprocess.STDOUT)
    summary = {"cycle": cycle, "started": started, "finished": datetime.now().isoformat(timespec="seconds"),
               "passed": result.returncode == 0, "exit_code": result.returncode}
    with (OUTPUT / "cycles.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(summary) + "\n")
    print(json.dumps(summary), flush=True)
