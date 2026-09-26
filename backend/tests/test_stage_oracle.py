import copy
import json

import pytest

from app import create_app
from app.api import parthenon as parthenon_api
from app.services import stage_oracle
from app.services.stage_oracle import (
    MAX_AUDIENCE,
    StageOracle,
    StageValidationError,
    normalize_stage,
    resolve_fill,
)
from app.utils.llm_client import LLMResponseError


DRAFT_URL = "/api/parthenon/stage/draft"


class FakeLLM:
    """Captures chat_json calls; never touches the network."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {}
        self.error = error
        self.calls = []

    def chat_json(self, messages, **kwargs):
        self.calls.append({"messages": copy.deepcopy(messages), **kwargs})
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.response)


class ExplodingLLM:
    def chat_json(self, messages, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the LLM must not be called for invalid input")


def _stage(**overrides):
    stage = {
        "title": "",
        "format": "panel",
        "era": "now",
        "setting": "A data-centre rooftop in Athens, 2026",
        "topic": "Should AI agents be allowed to vote on behalf of citizens?",
        "speakers": [
            {
                "name": "Socrates",
                "role": "Gadfly",
                "ideas": "The unexamined life; wisdom as knowing you do not know.",
                "voice": "Ironic questions",
                "words": "",
            },
            {
                "name": "Hypatia of Alexandria",
                "role": "Mathematician",
                "ideas": "Neoplatonism, astronomy, teaching in public.",
                "voice": "Calm and exact",
                "words": "",
            },
        ],
        "audience": [
            {"name": "Nikos the Courier", "description": "Delivers food; fears being automated."},
        ],
        "question": "",
        "happensNext": "",
    }
    stage.update(overrides)
    return stage


def _client(monkeypatch, llm):
    monkeypatch.setattr(
        parthenon_api, "StageOracle", lambda: StageOracle(llm_client=llm)
    )
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _user_payload(call):
    return call["messages"][1]["content"]


# ------------------------------------------------------------ normalisation

def test_normalize_stage_coerces_types_and_caps_lengths():
    raw = {
        "title": "  " + "T" * 200 + "  ",
        "format": "Circus",
        "era": "  FUTURE ",
        "setting": 42,
        "topic": "x" * 5000,
        "speakers": [
            {"name": "  Socrates  ", "role": "r" * 500, "ideas": "i" * 2000,
             "voice": "v" * 400, "words": "w" * 5000},
            {"name": "", "role": "nameless is dropped"},
            "not a dict",
            {"name": "socrates", "role": "duplicate by name is dropped"},
            {"name": "N" * 100},
        ] + [{"name": f"Extra {i}"} for i in range(10)],
        "audience": [{"name": f"Citizen {i}", "description": "d" * 600} for i in range(30)]
        + [{"description": "no name"}],
        "question": None,
        "happenNext": "  A vote on Friday.  ",
    }

    stage = normalize_stage(raw)

    assert stage["format"] == "panel"
    assert stage["era"] == "future"
    assert stage["setting"] == "42"
    assert len(stage["title"]) == 120
    assert len(stage["topic"]) == 3000
    assert stage["question"] == ""
    assert stage["happensNext"] == "A vote on Friday."

    assert len(stage["speakers"]) == 8
    first = stage["speakers"][0]
    assert first["name"] == "Socrates"
    assert len(first["role"]) == 200
    assert len(first["ideas"]) == 1500
    assert len(first["voice"]) == 300
    assert len(first["words"]) == 4000
    assert len(stage["speakers"][1]["name"]) == 80
    assert [s["name"].lower() for s in stage["speakers"]].count("socrates") == 1

    assert len(stage["audience"]) == 24
    assert all(len(m["description"]) == 400 for m in stage["audience"])


def test_normalize_stage_defaults_format_and_era():
    stage = normalize_stage({
        "speakers": [{"name": "Diogenes"}],
        "question": "What does the crowd decide?",
    })
    assert stage["format"] == "panel"
    assert stage["era"] == "now"
    assert stage["audience"] == []
    assert stage["speakers"][0] == {
        "name": "Diogenes", "role": "", "ideas": "", "voice": "", "words": "",
    }


@pytest.mark.parametrize(
    "raw, message",
    [
        (None, "JSON object"),
        ({"speakers": [], "topic": "AI"}, "named speaker"),
        ({"speakers": [{"name": "  "}], "topic": "AI"}, "named speaker"),
        ({"speakers": [{"name": "Plato"}], "topic": " ", "question": ""}, "topic or the question"),
    ],
)
def test_normalize_stage_rejects_invalid_stages(raw, message):
    with pytest.raises(ValueError, match=message):
        normalize_stage(raw)


# ------------------------------------------------------------ fill selection

def test_default_fill_selects_every_empty_part():
    assert resolve_fill(normalize_stage(_stage()), None) == [
        "words", "audience", "question", "title", "happensNext",
    ]


def test_default_fill_skips_written_parts():
    stage = _stage(
        title="The Vote of the Machines",
        question="How does the crowd react?",
        happensNext="The referendum is on Sunday.",
        audience=[{"name": f"Citizen {i}", "description": "d"} for i in range(8)],
    )
    for speaker in stage["speakers"]:
        speaker["words"] = "I have written my own words."
    with pytest.raises(StageValidationError, match="Nothing left"):
        resolve_fill(normalize_stage(stage), None)

    stage["speakers"][1]["words"] = ""
    assert resolve_fill(normalize_stage(stage), []) == ["words"]


def test_explicit_fill_is_ordered_and_validated():
    stage = normalize_stage(_stage(title="Already titled"))
    assert resolve_fill(stage, ["title", "words", "title"]) == ["words", "title"]
    with pytest.raises(StageValidationError, match="Unknown part"):
        resolve_fill(stage, ["words", "poems"])
    with pytest.raises(StageValidationError, match="list of parts"):
        resolve_fill(stage, {"words": True})


def test_explicit_words_never_target_speakers_with_their_own_words():
    stage = _stage()
    for speaker in stage["speakers"]:
        speaker["words"] = "Mine."
    normalized = normalize_stage(stage)
    assert resolve_fill(normalized, ["words", "question"]) == ["question"]
    with pytest.raises(StageValidationError):
        resolve_fill(normalized, ["words"])


# ------------------------------------------------------------ drafting

def test_draft_calls_llm_with_expected_options_and_prompt():
    llm = FakeLLM({"title": "Ballots for Machines"})
    StageOracle(llm_client=llm).draft(_stage(), ["title"])

    call = llm.calls[0]
    assert call["temperature"] == 0.8
    assert call["max_tokens"] == 6000
    assert call["max_attempts"] == 2
    system, user = call["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert "Oracle of Parthenon" in system["content"]
    assert "famous quotes" in system["content"]
    assert "Should AI agents be allowed to vote" in user["content"]
    assert '"title"' in user["content"]


def test_user_written_words_are_context_and_never_overwritten():
    stage = _stage()
    stage["speakers"][0]["words"] = "MY OWN WORDS, written by the user."
    llm = FakeLLM({
        "speakers": [
            {"name": "Socrates", "words": "The Oracle tried to rewrite Socrates."},
            {"name": "Hypatia of Alexandria", "words": "Friends, measure before you trust."},
        ],
    })

    draft = StageOracle(llm_client=llm).draft(stage, ["words"])

    assert draft["speakers"] == [
        {"name": "Hypatia of Alexandria", "words": "Friends, measure before you trust."},
    ]
    assert draft["filled"] == ["words"]
    user = _user_payload(llm.calls[0])
    assert "MY OWN WORDS, written by the user." in user
    request_part = json.loads(user.split("What to draft:\n", 1)[1].rsplit("\n\nReturn", 1)[0])
    assert request_part["speakers_needing_words"] == ["Hypatia of Alexandria"]
    assert request_part["speakers_with_their_own_words"] == ["Socrates"]


def test_speaker_words_map_by_name_case_insensitively_and_ignore_unknowns():
    llm = FakeLLM({
        "speakers": [
            {"name": "Plato", "words": "Not on this stage."},
            {"name": "  hypatia OF   alexandria ", "words": "# Heading\n\nI teach in public.\n\n\n\nStill here."},
            {"name": "SOCRATES", "words": '"I know that I know nothing about your machines."'},
            {"name": "socrates", "words": "A second answer for the same speaker."},
            {"name": None, "words": "Nameless."},
            {"name": "Hypatia of Alexandria", "words": ""},
        ],
    })

    draft = StageOracle(llm_client=llm).draft(_stage(), ["words"])

    assert draft["speakers"] == [
        {"name": "Socrates", "words": "I know that I know nothing about your machines."},
        {"name": "Hypatia of Alexandria", "words": "Heading\n\nI teach in public.\n\nStill here."},
    ]


def test_audience_is_deduplicated_and_capped():
    existing = [{"name": f"Citizen {i}", "description": "Here already."} for i in range(20)]
    llm = FakeLLM({
        "audience": [
            {"name": "citizen 3", "description": "Duplicate of an existing member."},
            {"name": "SOCRATES", "description": "A speaker is not the crowd."},
            {"name": "Ada the Prompt Farmer", "description": "Trains models for rent; ally."},
            {"name": "ada the prompt farmer", "description": "Duplicate within the answer."},
            {"name": "Missing Description", "description": "  "},
            {"name": "The Delivery Riders Guild", "description": "Fear automation; opposed."},
            {"name": "Irene, a Retired Juror", "description": "Undecided."},
            {"name": "Stavros the Data Clerk", "description": "Affected; his job is on the line."},
            {"name": "One Too Many", "description": "Past the cap of 24."},
        ],
    })

    draft = StageOracle(llm_client=llm).draft(_stage(audience=existing), ["audience"])

    names = [m["name"] for m in draft["audience"]]
    assert names == [
        "Ada the Prompt Farmer",
        "The Delivery Riders Guild",
        "Irene, a Retired Juror",
        "Stavros the Data Clerk",
    ]
    assert len(existing) + len(names) == MAX_AUDIENCE
    request_part = _user_payload(llm.calls[0])
    assert '"existing": 20' in request_part


def test_only_requested_parts_are_returned():
    llm = FakeLLM({
        "title": "“Ballots for Machines”",
        "speakers": [{"name": "Socrates", "words": "Unrequested words."}],
        "audience": [{"name": "Ada", "description": "Unrequested."}],
        "question": "Unrequested question.",
        "happensNext": "Unrequested trigger.",
    })

    draft = StageOracle(llm_client=llm).draft(_stage(), ["title"])

    assert draft == {
        "title": "Ballots for Machines",
        "speakers": [],
        "audience": [],
        "question": None,
        "happensNext": None,
        "filled": ["title"],
    }


def test_answer_without_any_requested_part_is_an_llm_response_error():
    llm = FakeLLM({"title": "", "question": None, "speakers": "nonsense"})
    with pytest.raises(LLMResponseError, match="none of the requested parts"):
        StageOracle(llm_client=llm).draft(_stage(), ["title", "question", "words"])


# ------------------------------------------------------------ API

def test_route_is_registered():
    app = create_app()
    rules = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
    assert DRAFT_URL in rules
    assert "POST" in rules[DRAFT_URL]


def test_api_returns_draft(monkeypatch):
    llm = FakeLLM({
        "title": "Ballots for Machines",
        "speakers": [
            {"name": "socrates", "words": "Tell me, what is a vote?"},
            {"name": "Hypatia of Alexandria", "words": "Let us measure first."},
        ],
        "audience": [{"name": "Ada the Prompt Farmer", "description": "Ally; trains models."}],
        "question": "How does the crowd change its mind? What does it decide?",
        "happensNext": "The city votes on Sunday.",
    })
    client = _client(monkeypatch, llm)

    response = client.post(DRAFT_URL, json={"stage": _stage()})

    assert response.status_code == 200
    assert response.json["success"] is True
    data = response.json["data"]
    assert data["filled"] == ["words", "audience", "question", "title", "happensNext"]
    assert data["speakers"][0] == {"name": "Socrates", "words": "Tell me, what is a vote?"}
    assert data["audience"] == [{"name": "Ada the Prompt Farmer", "description": "Ally; trains models."}]


@pytest.mark.parametrize(
    "body, message",
    [
        ({"fill": ["words"]}, "JSON object"),
        ({"stage": {"speakers": [], "topic": "AI"}}, "named speaker"),
        ({"stage": {"speakers": [{"name": "Plato"}]}}, "topic or the question"),
        ({"stage": _stage(), "fill": ["prophecy"]}, "Unknown part"),
        ({"stage": _stage(), "fill": "words,title"}, "Unknown part"),
    ],
)
def test_api_rejects_invalid_input_with_400(monkeypatch, body, message):
    client = _client(monkeypatch, ExplodingLLM())
    response = client.post(DRAFT_URL, json=body)
    assert response.status_code == 400
    assert response.json["success"] is False
    assert message in response.json["error"]


def test_api_rejects_non_json_body(monkeypatch):
    client = _client(monkeypatch, ExplodingLLM())
    response = client.post(DRAFT_URL, data="stage=1", content_type="text/plain")
    assert response.status_code == 400
    assert response.json["success"] is False


def test_api_maps_llm_response_error_to_safe_502(monkeypatch):
    llm = FakeLLM(error=LLMResponseError(
        "LLM JSON output was truncated at the token limit", finish_reason="length",
    ))
    client = _client(monkeypatch, llm)

    response = client.post(DRAFT_URL, json={"stage": _stage()})

    assert response.status_code == 502
    assert response.json["success"] is False
    assert "token limit" in response.json["error"]
    assert "Should AI agents" not in response.get_data(as_text=True)


def test_api_does_not_expose_provider_error_body(monkeypatch):
    class ProviderError(RuntimeError):
        status_code = 401
        request_id = "req-safe-42<script>"
        body = {"error": {"message": "SECRET-PROVIDER-BODY"}}

    client = _client(monkeypatch, FakeLLM(error=ProviderError("SECRET-PROVIDER-BODY")))

    response = client.post(DRAFT_URL, json={"stage": _stage()})

    text = response.get_data(as_text=True)
    assert response.status_code == 502
    assert "HTTP 401" in response.json["error"]
    assert "req-safe-42script" in response.json["error"]
    assert "SECRET-PROVIDER-BODY" not in text
    assert "<script>" not in text
    assert "Should AI agents" not in text


def test_api_maps_unexpected_errors_to_generic_500(monkeypatch):
    client = _client(monkeypatch, FakeLLM(error=RuntimeError("SECRET-INTERNAL")))
    response = client.post(DRAFT_URL, json={"stage": _stage()})
    assert response.status_code == 500
    assert "SECRET-INTERNAL" not in response.get_data(as_text=True)


def test_api_reports_missing_llm_configuration_as_503(monkeypatch):
    def no_key():
        raise ValueError("LLM_API_KEY 未配置")

    monkeypatch.setattr(stage_oracle, "LLMClient", no_key)
    monkeypatch.setattr(parthenon_api, "StageOracle", StageOracle)
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(DRAFT_URL, json={"stage": _stage()})

    assert response.status_code == 503
    assert response.json["success"] is False
    assert "Oracle" in response.json["error"]


def test_api_appends_language_instruction(monkeypatch):
    llm = FakeLLM({"title": "Ballots for Machines"})
    client = _client(monkeypatch, llm)

    response = client.post(
        DRAFT_URL,
        json={"stage": _stage(), "fill": ["title"]},
        headers={"Accept-Language": "en"},
    )

    assert response.status_code == 200
    system = llm.calls[0]["messages"][0]["content"]
    assert system.rstrip().endswith("Please respond in English.")
