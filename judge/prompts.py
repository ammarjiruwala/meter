"""The templated prompts the console offers, in the order a judge runs them.

**Why templated and not editable** (PITCH.md §3.2). Prediction accuracy is keyed on
`(project, feature)`. A free-text prompt on an unknown tag falls through the ladder to the
raw heuristic — roughly 65-80% median error against ~10% — so an editable box would make a
working product look broken, and would add a failure mode nobody can support
asynchronously. The judge chooses *when* to run, not *what*.

**Why these tags.** Every one was measured in a real run of the walkthrough by someone who
did not write it (EXPERIENCE.md §5). `sql-from-question` came in at 9% and
`pr-description` at 2%. The tags that read badly there are deliberately absent from the
opening sequence: `commit-message` at 31%, `ticket-classify` at 88% and `test-plan` at
92%. Two of those are honest — a 9-token answer predicted as 15 is 88% wrong and costs
$0.000012, which says more about percentage error at that scale than about the model — but
a judge meeting them first would reasonably stop reading.

`commit-message` appears only as the *control* in the breaker act, where its job is to
succeed while another tag is throttled. Its accuracy is not the claim being made there.

Owner: Ammar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Prompt:
    """One templated call, plus what the console should say about it."""

    id: str
    feature: str
    title: str
    prompt: str
    #: What this step is trying to prove, shown beside the result.
    claim: str
    #: Set when the tag is known to read badly, so the console can pre-empt the reaction
    #: at the moment it happens rather than in a footnote nobody reaches.
    caveat: str | None = None
    max_tokens: int = 400
    tags: tuple[str, ...] = field(default_factory=tuple)


TICKET = (
    "Summarise this support ticket in two sentences for the on-call engineer: The "
    "notification fanout times out under load. Users report it started this morning. "
    "Logs point at the connection pool. We saw OperationalError: database is locked in "
    "the pod events."
)

SEQUENCE: tuple[Prompt, ...] = (
    Prompt(
        id="first",
        feature="ticket-summary",
        title="Summarise a support ticket",
        prompt=TICKET,
        claim=(
            "The cost was predicted before the call ran, by a model that had never seen "
            "this prompt. Watch the estimate land before the answer does."
        ),
    ),
    Prompt(
        id="sql",
        feature="sql-from-question",
        title="Write a SQL query from a question",
        prompt=(
            "Write a SQL query answering: how many times did the notification fanout "
            "report 'OperationalError: database is locked' per day over the last week? "
            "Table events(ts, service, message)."
        ),
        claim="A different feature, a different shape of answer, the same accuracy. "
              "Measured at 9% median error in a real run.",
        # Capped well below the 400 the others use. Uncapped this returned ~280 tokens of
        # SQL, which pushed the accuracy panel beside it off the screen -- and the whole
        # point of putting them side by side is that both are visible at once.
        max_tokens=160,
    ),
    Prompt(
        id="pr",
        feature="pr-description",
        title="Draft a pull request description",
        prompt=(
            "Write a pull request description for a change to the connection pool in our "
            "Python notification fanout. The bug was that it times out under load. "
            "Include what changed and how to test it."
        ),
        claim="Three calls in, the median and the within-2x figure start to mean "
              "something. Measured at 2% in a real run.",
    ),
)

#: The control in the breaker act. It runs *after* another tag has been throttled, and
#: succeeding is the entire point: the runaway feature is cut off while everything else
#: keeps serving. Judged on the 200, not on its error.
CONTROL = Prompt(
    id="control",
    feature="commit-message",
    title="A different feature, while the first is throttled",
    prompt=(
        "Write a conventional-commit message (subject line plus one body line) for a "
        "change that fixes the connection pool in the notification fanout, which "
        "previously times out under load."
    ),
    claim="This is the claim worth understanding: the runaway tag is throttled while "
          "everything else on the same key keeps serving. Not a key-wide cut.",
    caveat="Its error will read high, and that is honest: a 9-token answer predicted as "
           "15 is 60% wrong and costs a millionth of a dollar. Judge this one by cost.",
    max_tokens=120,
)

#: What the breaker act fires, repeatedly, to clear the session's demo-scale floor.
RUNAWAY = Prompt(
    id="runaway",
    feature="ticket-summary",
    title="A runaway agent, retrying in a loop",
    prompt=TICKET,
    claim="Spend over a floor is a WHERE clause. Spend over a floor AND several times "
          "this tag's own trailing rate is the part that does not fire on a feature "
          "that is merely expensive.",
)

BY_ID = {p.id: p for p in (*SEQUENCE, CONTROL, RUNAWAY)}


def as_dict(p: Prompt) -> dict:
    """Serialise for the console. The prompt text ships so it can be shown read-only."""
    return {
        "id": p.id,
        "feature": p.feature,
        "title": p.title,
        "prompt": p.prompt,
        "claim": p.claim,
        "caveat": p.caveat,
        "max_tokens": p.max_tokens,
        "model": "gpt-4o-mini",
    }
