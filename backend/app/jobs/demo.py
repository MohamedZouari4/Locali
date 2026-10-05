"""A demo job kind for trying the job system before real job kinds exist: counts to `steps`,
waiting `delay` seconds per step, reporting progress and stopping when cancelled.

Registered only when the backend starts with LOCALI_DEMO_JOBS=1, so it never ships in normal use.
"""

import time

from app.jobs import worker

KIND = "demo"


def run_demo(params, ctx):
    steps = min(max(int(params.get("steps", 30)), 1), 1000)
    delay = min(max(float(params.get("delay", 0.5)), 0.0), 5.0)
    for step in range(1, steps + 1):
        ctx.check_cancelled()
        time.sleep(delay)
        ctx.progress(step, steps, f"Step {step} of {steps}")
    return {"steps": steps}


def register():
    worker.HANDLERS[KIND] = run_demo
