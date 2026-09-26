import pytest

from app.services.report_agent import _final_answer_text


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("Final Answer:\n\nThe city", "The city"),
        # Grok bolds the marker; its closing ** used to open the section.
        ("**Final Answer:**\n\nThe city", "The city"),
        ("**Final Answer**: The city", "The city"),
        ("*Final Answer:* The city", "The city"),
        ("__Final Answer__:\nThe city", "The city"),
        # Emphasis that belongs to the answer itself stays.
        ("Thought\nFinal Answer: **Key point** holds", "**Key point** holds"),
        ("**Final Answer:** **Key** x", "**Key** x"),
        # The last marker wins, as with the old split.
        ("Final Answer: draft\n**Final Answer:** real", "real"),
        ("no marker", "no marker"),
    ],
)
def test_final_answer_text(response, expected):
    assert _final_answer_text(response) == expected
