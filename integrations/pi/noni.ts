// noni hook: injects `noni brief` at session start and after each compaction, and
// keeps one standing reminder in the prompt. See README.md for install and limits.

import { existsSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BRIEF_TIMEOUT_MS = 30_000;
const LINE_LIMIT = 300;
const PATH_TOKEN = /(?:[^\s"'`]+\/)+[^\s"'`]+/g;
const REMINDER =
  "noni holds this project's product direction and decisions. Work in the " +
  "order it gives and follow its recorded decisions; do not invent direction. " +
  "When something is undecided, ask the operator and record the answer with " +
  "the noni decide command.";

function stateRoot(env: Record<string, string | undefined>, cwd: string): string | undefined {
  const fromEnv = env["NONI_STATE_ROOT"];
  if (fromEnv) return fromEnv;
  for (const candidate of [join(cwd, ".noni-state"), cwd]) {
    if (existsSync(join(candidate, "noni"))) return candidate;
  }
  return undefined;
}

// The first stderr line, capped, with every path token replaced by "state root".
function failureLine(reason: string): string {
  const first = reason.split("\n")[0]?.trim() || "no reason given";
  const scrubbed = first.replace(PATH_TOKEN, "state root");
  const line = `noni: could not read the brief (${scrubbed})`;
  return line.length <= LINE_LIMIT ? line : line.slice(0, LINE_LIMIT - 1) + "\u2026";
}

// Why a run that printed nothing could not read the brief: a kill is a timeout,
// an exit 0 printed nothing, and anything else is the first line of stderr.
function failureReason(r: { code: number; stderr: string; killed: boolean }) {
  if (r.killed) return "timed out";
  if (r.code === 0) return "printed nothing";
  return r.stderr.trim() || `exit code ${r.code}`;
}

export default function noniHook(pi: ExtensionAPI) {
  // Set by the two start events, cleared by the run that returns it.
  let pendingBrief: string | undefined;
  let inflight: Promise<void> | undefined;

  async function fetchBrief(cwd: string): Promise<void> {
    try {
      const root = stateRoot(process.env, cwd);
      if (!root) return;
      const result = await pi.exec("noni", ["brief", "--repo", root], { timeout: BRIEF_TIMEOUT_MS });
      const stdout = result.stdout.trim();
      pendingBrief = stdout || failureLine(failureReason(result));
    } catch {
      pendingBrief = failureLine("could not run the brief");
    }
  }

  // The two start events only start the fetch: no handler awaits it here, and
  // headless child agents get the reminder but never a brief.
  pi.on("session_start", (_event, ctx) => {
    if (ctx.hasUI) inflight = fetchBrief(ctx.cwd);
  });
  pi.on("session_compact", (_event, ctx) => {
    if (ctx.hasUI) inflight = fetchBrief(ctx.cwd);
  });

  pi.on("before_agent_start", async (event) => {
    const options = event.systemPromptOptions;
    const guidelines = options.promptGuidelines ?? [];
    if (!guidelines.includes(REMINDER)) guidelines.push(REMINDER);
    options.promptGuidelines = guidelines;
    if (event.messageType !== "user") return undefined;
    await inflight;
    if (pendingBrief === undefined) return undefined;
    const content = pendingBrief;
    pendingBrief = undefined;
    return { message: { customType: "noni-brief", content, display: true } };
  });
}
