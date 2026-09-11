# Spec template

Every queued issue is written in this shape. A spec that cannot be filled in
concretely is not ready to be built — leave it in the roadmap and say why.

---

**What a reader gets**

One or two sentences, in the words a reader would use. No jargon. If you cannot
say what a person gets out of this, it is not worth building.

**Where the numbers come from**

The exact files in `data/`, by name, and the exact columns. If a file does not
exist yet, say which collector has to write it first and stop — a page cannot
be specified before its data.

**What to build**

The files to add or change, by path. What each one does in a line. Anything
deliberately left out.

**Plain language**

The words this page must not use (the banned list), and the phrases to use
instead for anything technical it has to express.

**Verification**

The exact commands to run and what passing looks like. Always at least:

```bash
python3 -m py_compile <changed .py>
python3 tools/check_freshness.py
python3 tools/check_page.py            # if any .html changed
```

Plus one check specific to this work — a count, a total, a figure checked by
hand against the source.

**Done when**

A short list, each item either true or false, nothing that needs a judgement
call.

**Out of scope**

What a builder might reasonably think belongs here and must not do.
