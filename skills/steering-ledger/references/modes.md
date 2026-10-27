# The two steer modes

Two input modes, one record shape. Both end in an operator-confirmed decision
that becomes a committed file under `noni/decisions/`. The agent asks and
distils; the operator answers and confirms. Never answer for the operator.

## Multiple-choice mode

The agent asks **1-4 questions**, each with **2-4 options**, and a free-text
escape hatch is always offered. The bounds are production-verified (AG2,
LangGraph, Claude AskUserQuestion, and the prior-art question renderers all
converge on 1-4 x 2-4).

```
q1: Which release should carry the new scheduler?
  [ ] next train
  [ ] after that
  [ ] drop it
  (or reply with your own choice)
```

- **1-4 questions.** A record with 0 or more than 4 questions is malformed.
- **2-4 options each.** A question with 1 or more than 4 options is malformed.
- **Free-text escape hatch.** The operator may reply with a choice not in the
  list; the `answer` then stores that free-text string. The bounds constrain the
  *rendered* options, not the operator's reply.
- **Answer names its question by id.** Each question carries an `id` and an
  `answer`; the pair is the record. A three-question record stores three
  `{id, text, options, answer}` objects, and each answer is paired to its
  question by id — no ambiguity about which question a given answer answered.

The resolved record stores the chosen option's string as `answer` (or the
free-text string when the escape hatch was used). The question's `id` is what
pairs it to the answer.

## Free-chat mode

The agent distils the conversation into a **candidate record** and shows it to
the operator. The operator **confirms** the candidate; the confirmation is what
triggers the commit. The commit only happens after confirmation.

- The agent drafts `{id, date, asked_by, questions, scope, supersedes}` with
  `status` tentatively `open` and every `answer` `null`.
- The operator confirms (or edits, or declines). On confirmation the `answer`
  field is filled with the operator's stated position and `status` becomes
  `decided`; the file is committed with `by` set from the commit author.
- A **decline or cancel** leaves the question open. Do not write a record to
  "remember" a declined steer that the operator never asked to be kept: the
  steer is simply not recorded. When a declined steer **is** recorded (the
  ledger is meant to show that an answer was not given), it is written as an
  **open chain-root record**: `supersedes: null`, `status: open`, and every
  `answer` written as `null` — never as a supersede, because a supersede whose
  chain holds no answered record resolves to zero live records (census exit
  20). `scripts/decide.py` enforces this: `--supersedes` with an unanswered
  question is exit 2, and the same flags without `--supersedes` write the open
  chain-root record.

## Anti-fabrication

The agent never answers for the operator. This is a **protocol rule agents
follow** — not something the census can verify: git cannot distinguish an
operator answer from an agent-written answer (agents commit under the
operator's identity), and signed, forge-verifiable confirmation is deferred to
a follow-up. Concretely:

- A record with an `answer` must come from an operator confirmation, by agent
  discipline.
- A decline/cancel must leave the question open: `status: open` with every
  `answer` written as `null`, and never an invented answer. If the decline is
  recorded at all it is an open chain-root record, never a supersede.
- The agent may *propose* an answer in the candidate, but the candidate is not a
  record until the operator confirms it.

The reference implementation of answer-legitimacy parsing (the `one`/`many`/
`stranger` tick states, the non-allowed-account reply that voids, marker
spoofing, CR injection, option-label box injection) is the prior-art
answer-legitimacy function; the adapter maps onto it rather than reinventing it.
