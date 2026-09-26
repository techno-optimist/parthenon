from unittest.mock import MagicMock

from app.services.report_agent import ReportAgent, ReportOutline, ReportSection


class ScriptedLLM:
    """Replies from a list, recording every conversation it was shown."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


def make_agent(llm):
    agent = ReportAgent(
        graph_id="g",
        simulation_id="s",
        simulation_requirement="Will Psammos sign the Kiln Compact?",
        llm_client=llm,
        zep_tools=MagicMock(),
    )
    agent.report_logger = None
    agent._execute_tool = MagicMock(return_value="Stelios Moraitis: warm water empties the seagrass.")
    return agent


def write_section(agent, title="The Offer Hardens Against a Pause"):
    outline = ReportOutline(title="Psammos", summary="", sections=[ReportSection(title=title)])
    return agent._generate_section_react(outline.sections[0], outline, previous_sections=[])


PLAN_ONLY = "I'll start by mapping the full timeline of the offer and the Nerve."


def test_a_model_that_narrates_instead_of_calling_gets_the_search_made_for_it():
    llm = ScriptedLLM([
        PLAN_ONLY,
        PLAN_ONLY,  # second stall: the agent makes the search itself
        '<tool_call>{"name": "quick_search", "parameters": {"query": "pause"}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "nerve"}}</tool_call>',
        "Final Answer: The bay refused the lease as written.",
    ])
    agent = make_agent(llm)

    assert write_section(agent) == "The bay refused the lease as written."

    first = agent._execute_tool.call_args_list[0]
    assert first.args[0] == "panorama_search"
    assert first.args[1] == {"query": "The Offer Hardens Against a Pause"}
    assert agent._execute_tool.call_count == 3
    # The fallback's result reached the model as an observation.
    assert any("warm water empties the seagrass" in m["content"] for m in llm.seen[2] if m["role"] == "user")


def test_the_first_stall_is_answered_with_a_ready_tool_call_block():
    llm = ScriptedLLM([
        PLAN_ONLY,
        '<tool_call>{"name": "panorama_search", "parameters": {"query": "offer"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "pause"}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "nerve"}}</tool_call>',
        "Final Answer: Done.",
    ])
    agent = make_agent(llm)

    assert write_section(agent) == "Done."

    nudge = llm.seen[1][-1]["content"]
    assert "<tool_call>" in nudge
    assert '"name": "panorama_search"' in nudge
    assert "The Offer Hardens Against a Pause" in nudge
    # Only the model's own calls ran; no fallback was needed.
    assert [c.args[0] for c in agent._execute_tool.call_args_list] == ["panorama_search", "quick_search", "insight_forge"]


def test_a_real_tool_call_resets_the_stall_count():
    llm = ScriptedLLM([
        PLAN_ONLY,
        '<tool_call>{"name": "panorama_search", "parameters": {"query": "offer"}}</tool_call>',
        PLAN_ONLY,  # one stall after a real call is only nudged
        '<tool_call>{"name": "quick_search", "parameters": {"query": "pause"}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "nerve"}}</tool_call>',
        "Final Answer: Done.",  # the forced answer after the last iteration
    ])
    agent = make_agent(llm)
    agent.MAX_TOOL_CALLS_PER_SECTION = 10

    write_section(agent)

    assert [c.args[0] for c in agent._execute_tool.call_args_list][:2] == ["panorama_search", "quick_search"]


def test_a_short_plan_after_enough_searching_is_not_taken_as_the_section():
    llm = ScriptedLLM([
        '<tool_call>{"name": "panorama_search", "parameters": {"query": "offer"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "pause"}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "nerve"}}</tool_call>',
        "The panorama leaves the paper open. Next I need who still holds a choice.",
        "Final Answer: " + "Despina Nomikou still holds the casting vote. " * 20,
    ])
    agent = make_agent(llm)

    section = write_section(agent)

    assert section.startswith("Despina Nomikou still holds the casting vote.")
    assert "Final Answer:" in llm.seen[4][-1]["content"]


def test_a_substantial_unmarked_reply_is_still_accepted():
    body = "Despina Nomikou still holds the casting vote. " * 20
    llm = ScriptedLLM([
        '<tool_call>{"name": "panorama_search", "parameters": {"query": "offer"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "pause"}}</tool_call>',
        '<tool_call>{"name": "insight_forge", "parameters": {"query": "nerve"}}</tool_call>',
        body,
    ])
    agent = make_agent(llm)

    assert write_section(agent) == body.strip()
