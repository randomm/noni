"""The behavioural driver for the pi harness hook under integrations/pi/.

The static checks in tests/test_pi_extension.py read ``noni.ts`` as text. This
module holds the one form that can observe behaviour: a JavaScript driver that
imports the hook and runs it against a fake ExtensionAPI, launched under node's
own type stripping (the route the ticket names for loading a ``.ts`` hook).

The driver prints one JSON object per scenario and asserts nothing, so every
gate stays a Python assertion in the suite that reads these records. Each
scenario reports what it was given (the cwd, the environment, the spawn argv)
alongside what the hook did, so a case cannot pass by running in a tree that
happens to hold a ``noni/`` directory.

The scenario list:

- ``registrations``: the events the hook registers, in order;
- ``spawns``: one spawn per start event and none across three runs, plus the
  argv and options of the first;
- ``reminder``: how many copies of the standing bullet reach the prompt over
  three runs sharing one options object (pi copies that array once per run, so
  an unconditional push shows up here as 1, 2, 3);
- ``headless``: a non-interactive session gets the reminder and no spawn;
- ``brief``: the brief arrives on the first user run and on nothing after it;
- ``failure`` / ``empty``: what the model is told when the census run fails, and
  that no path survives;
- ``no-state``: with no state root to read, no spawn and no message at all.

A helper module: never named ``test_*``.
"""

from __future__ import annotations

# The scratch layout the driver expects, by name: ``STATE`` is a directory that
# holds a ``noni/`` directory (so the resolver's candidate arm fires) and
# ``NO_STATE`` a bare one (the arm with no root at all). ``EXTENSION`` is
# substituted below with the path of the hook to load.
_ENV_STATE = "STATE"
_ENV_NO_STATE = "NO_STATE"
_EXTENSION_PLACEHOLDER = "__EXTENSION__"

DRIVER = """\
import noniHook from "__EXTENSION__";

const state = process.env.STATE;
const noState = process.env.NO_STATE;

function scenario(name, run) {
  const record = (extra) => console.log(JSON.stringify({ scenario: name, ...(extra || {}) }));
  Promise.resolve().then(run).then(
    (extra) => record(extra),
    (err) => record({ error: String((err && err.stack) || err) }),
  );
}

// One load of the hook with a fake api: records registrations and spawns.
// `start` runs both start handlers and `turn` the per-turn one, both bound here
// so a caller never reaches into `seen` by hand. `cwd` is what the start events
// report, and a case that wants the no-root arm sets it to the bare directory.
function load(result, hasUI) {
  const seen = [];
  const spawns = [];
  const api = {
    on(event, handler) { seen.push([event, handler]); },
    exec(command, args, options) {
      spawns.push({ command, args, options });
      return Promise.resolve(result);
    },
  };
  noniHook(api);
  const forEvent = (event) => seen.find((entry) => entry[0] === event)[1];
  const bound = {
    seen,
    spawns,
    cwd: state,
    start: () => Promise.all([
      forEvent("session_start")({}, { hasUI: hasUI, cwd: bound.cwd }),
      forEvent("session_compact")({}, { hasUI: hasUI, cwd: bound.cwd }),
    ]),
    turn: (messageType, opts) =>
      forEvent("before_agent_start")({ messageType, systemPromptOptions: opts }),
  };
  return bound;
}

const ok = { stdout: "order: 7 then 3\\n", stderr: "", code: 0 };
const freshOptions = () => ({ promptGuidelines: [] });
const count = (items, value) => items.filter((item) => item === value).length;
const REMINDER = "noni holds this project's product direction and decisions. "
  + "Work in the order it gives and follow its recorded decisions; do not invent "
  + "direction. When something is undecided, ask the operator and record the "
  + "answer with the noni decide command.";

scenario("registrations", () => ({ registrations: load(ok, true).seen.map((e) => e[0]) }));

// Two start events, one spawn each, and none across three runs. The per-turn
// handler returns undefined for "nothing to add", which JSON drops the way it
// drops null, so each caller snapshots what it got.
scenario("spawns", async () => {
  const h = load(ok, true);
  await h.start();
  const afterStarts = h.spawns.length;
  const seen = [];
  for (let i = 0; i < 3; i++) {
    seen.push((await h.turn("user", freshOptions())) !== undefined);
  }
  return { afterStarts, spawn: h.spawns[0], turns: h.spawns.length - afterStarts, seen };
});

// The one standing bullet, counted after each of three runs on the same options
// object: pi copies the array once per run, so an unconditional push shows 1, 2, 3.
scenario("reminder", async () => {
  const h = load(ok, true);
  await h.start();
  const shared = { promptGuidelines: [] };
  const copies = [];
  for (let i = 0; i < 3; i++) {
    await h.turn("user", shared);
    copies.push(count(shared.promptGuidelines, REMINDER));
  }
  return { bullets: shared.promptGuidelines, copies };
});

// Headless: no spawn, but the reminder still applies.
scenario("headless", async () => {
  const h = load(ok, false);
  await h.start();
  const shared = { promptGuidelines: [] };
  await h.turn("user", shared);
  return { spawns: h.spawns.length, once: count(shared.promptGuidelines, REMINDER) };
});

// The brief lands once, on the user run only, and never again.
scenario("brief", async () => {
  const h = load(ok, true);
  await h.start();
  const first = await h.turn("user", freshOptions());
  const again = await h.turn("user", freshOptions());
  const custom = await h.turn("custom", freshOptions());
  return { first, again: again !== undefined, custom: custom !== undefined };
});

// Failure arms: what the model is told, and that no path survives. The exit-2
// stderr is the real shape brief.py prints for a bad --repo, path and all.
for (const [name, result] of [
  ["failure", { stdout: "", stderr: "brief: --repo /home/someone/state is not a directory", code: 2 }],
  ["empty", { stdout: "", stderr: "", code: 0 }],
]) {
  scenario(name, async () => {
    const h = load(result, true);
    await h.start();
    return { message: await h.turn("user", freshOptions()) };
  });
}

// With no state root anywhere: no spawn, and no message of any kind. The var the
// resolver reads first is NONI_STATE_ROOT, so the case names it explicitly rather
// than relying on its absence: an empty value falls through to the candidate
// loop, where neither the working directory nor its `.noni-state` holds a
// `noni/` directory.
scenario("no-state", async () => {
  const saved = process.env.NONI_STATE_ROOT;
  process.env.NONI_STATE_ROOT = "";
  try {
    const h = load(ok, true);
    h.cwd = noState;
    await h.start();
    const spawned = h.spawns.length;
    const message = await h.turn("user", freshOptions());
    return {
      cwd: noState,
      env: process.env.NONI_STATE_ROOT,
      spawned,
      message: message !== undefined,
    };
  } finally {
    if (saved === undefined) delete process.env.NONI_STATE_ROOT;
    else process.env.NONI_STATE_ROOT = saved;
  }
});
"""


def driver_source(extension: str) -> str:
    """The driver as JavaScript, wired to load the hook at ``extension``."""
    return DRIVER.replace(_EXTENSION_PLACEHOLDER, extension)
