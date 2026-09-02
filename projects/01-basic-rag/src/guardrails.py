"""Checks on what comes back, so a failure is visible rather than blank.

The pipeline can fail without raising anything. A model that returns no text
is not an error as far as LangChain is concerned — it is simply an answer of
length zero, which reaches the terminal as an empty line and tells you
nothing about what went wrong.
"""


class NoAnswerError(Exception):
    """The model produced no text at all."""


def check_answer_is_not_empty(answer: str) -> None:
    """Raise if the model gave back nothing.

    Seen in practice: with reasoning enabled, the model sometimes streamed
    only reasoning tokens, wandered off, and ended without writing an answer.
    Reasoning is now off, which removes that cause — but a rate limit, a
    provider error or the model simply stopping would look identical, and all
    of them are worth a message rather than a blank line.
    """
    if not answer.strip():
        raise NoAnswerError(
            "The model returned no answer. Nothing was written — this is not "
            "the model saying it does not know. Try asking again."
        )
