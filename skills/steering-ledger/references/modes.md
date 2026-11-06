# The two steer modes

Two input modes, one record shape. Both end in an operator-confirmed decision
that becomes a committed file under `noni/decisions/`. The agent asks and
distils; the operator answers and confirms. Never answer for the operator.

## Multiple-choice mode

The agent asks **1-4 questions**, each with **2-4 options**, and a free-text
escape hatch is always offered. The bounds are the ones the writer enforces and
both censuses check: a record outside 1-4 questions is refused, and so is a
question holding fewer than two options — except where `--single-option` earns
the marker, which lowers that bound to one.

```
q1: Which release should carry the new scheduler?
  [ ] next train
  [ ] after that
  [ ] drop it
  (or reply with your own choice)
```

- **1-4 questions.** A record with 0 or more than 4 questions is malformed.
- **2-4 options each.** A question with 1 or more than 4 options is malformed.
  The one exception is a record the writer marked: `--single-option` writes
  `single_option: true`, and only that marker lets a question hold exactly one
  option. It exists to record a decision the operator already made, where an
  alternative would have to be invented. The marker is read per record and the
  bound is judged per question: with it set, any question of that record may
  hold one option, and at least one of them must — a marker no question carries
  a one option for is malformed too, because the record then claims a question
  nobody asked. A one-option record without the marker
  is malformed like any other, so the bound is never relaxed by content alone.
- **Free-text escape hatch.** The operator may reply with a choice not in the
  list; the `answer` then stores that free-text string. The bounds constrain the
  *rendered* options, not the operator's reply.
- **Answer names its question by id.** Each question carries an `id` and an
  `answer`; the pair is the record. A three-question record stores three
  `{id, text, options, answer}` objects, and each answer is paired to its
  question by id — no ambiguity about which question a given answer answered.
- **The decider is not the committer.** An agent commits under the operator's
  identity, so `by` names who committed. `--decided-by` records who decided and
  `--on-behalf-of` names the party a delegate acted for; both sit beside `by`
  and never replace it. See `decisions.md`, Attribution.

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
