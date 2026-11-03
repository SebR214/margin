#!/usr/bin/env python3
"""agents/collect_restarter.sh against a stub curl (SEB-436): it starts the chain only when no collect run is going or queued,
ignores a one-shot run, and names a missing App permission. No network, no token."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURL = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = open(os.environ["STUB_LOG"], "a")
log.write(" ".join(a) + "\n")
if "-X" in a:                                     # the dispatch
    body = {"message": "Resource not accessible by integration"} if os.environ["STUB_CODE"] == "403" else {}
    open(a[a.index("-o") + 1], "w").write(json.dumps(body))
    sys.stdout.write(os.environ["STUB_CODE"])
else:                                             # a list of runs
    status = [x for x in a if "status=" in x][0].split("status=")[1].split("&")[0]
    sys.stdout.write(json.dumps({"workflow_runs": json.loads(os.environ["STUB_RUNS"]).get(status, [])}))
"""


def run(runs, code="204"):
    with tempfile.TemporaryDirectory() as d:
        agents = os.path.join(d, "agents")
        os.makedirs(agents)
        shutil.copy(os.path.join(HERE, "agents", "collect_restarter.sh"), agents)
        open(os.path.join(agents, "gh_token.sh"), "w").write("#!/usr/bin/env bash\nprintf 'tok'\n")
        os.makedirs(os.path.join(d, "bin"))
        open(os.path.join(d, "bin", "curl"), "w").write(CURL)
        for f in (os.path.join(agents, "collect_restarter.sh"), os.path.join(agents, "gh_token.sh"), os.path.join(d, "bin", "curl")):
            os.chmod(f, 0o755)
        env = dict(os.environ, PATH=os.path.join(d, "bin") + os.pathsep + os.environ["PATH"], STUB_LOG=os.path.join(d, "log"),
                   STUB_RUNS=json.dumps(runs), STUB_CODE=code)
        r = subprocess.run(["bash", os.path.join(agents, "collect_restarter.sh")], capture_output=True, text=True, env=env)
        log = open(os.path.join(d, "log")).read() if os.path.exists(os.path.join(d, "log")) else ""
        return r.returncode, r.stdout + r.stderr, "-X POST" in log


def main():
    one = [{"display_title": "collect slot=2026-11-03T10:35Z"}]
    rc, out, posted = run({"in_progress": one})
    assert rc == 0 and not posted and "chain alive" in out, (rc, out)
    rc, out, posted = run({"queued": one})
    assert rc == 0 and not posted, "a queued run is a live chain"
    rc, out, posted = run({"in_progress": [{"display_title": "collect one-shot"}]})
    assert rc == 0 and posted and "started a collect run" in out, "a one-shot test run is not the chain"
    rc, out, posted = run({})
    assert rc == 0 and posted, (rc, out)
    rc, out, posted = run({}, code="403")
    assert rc == 1 and posted and "Actions: Read and write" in out and "Resource not accessible" in out, (rc, out)
    print("collect_restarter test: ok")


if __name__ == "__main__":
    sys.exit(main())
