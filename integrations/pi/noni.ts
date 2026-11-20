// noni hook: injects `noni brief` at session start and after each compaction, and
// keeps one standing reminder in the prompt. See README.md for install and limits.

import { existsSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BRIEF_TIMEOUT_MS = 10_000;
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
  const firstLine = reason.split("\n")[0]?.trim() || "no reason given";
  const line = `noni: could not read the brief (${firstLine.replace(PATH_TOKEN, "state root")})`;
  return line.length <= LINE_LIMIT ? line : line.slice(0, LINE_LIMIT - 1) + "\u2026";
}

export default function noniHook(pi: ExtensionAPI) {
  // Set by the two start events, cleared by the run that returns it.
  let pendingBrief: string | undefined;

  async function fetchBrief(cwd: string): Promise<void> {
    const root = stateRoot(process.env, cwd);
    if (!root) return;
    const result = await pi.exec("noni", ["brief", "--repo", root], { timeout: BRIEF_TIMEOUT_MS });
    const stdout = result.stdout.trim();
    if (result.code === 0 && stdout) {
      pendingBrief = stdout;
      return;
    }
    pendingBrief = failureLine(result.stderr.trim() || `exit code ${result.code}`);
  }

  pi.on("session_start", async (_event, ctx) => {
    // Child agents run headless, so the brief is fetched only for an interactive session.
    if (ctx.hasUI) await fetchBrief(ctx.cwd);
  });

  pi.on("session_compact", async (_event, ctx) => {
    if (ctx.hasUI) await fetchBrief(ctx.cwd);
  });

  pi.on("before_agent_start", async (event) => {
    const options = event.systemPromptOptions;
    const guidelines = options.promptGuidelines ?? [];
    if (!guidelines.includes(REMINDER)) guidelines.push(REMINDER);
    options.promptGuidelines = guidelines;
    if (event.messageType !== "user" || pendingBrief === undefined) return undefined;
    const content = pendingBrief;
    pendingBrief = undefined;
    return { message: { customType: "noni-brief", content, display: true } };
  });
}
