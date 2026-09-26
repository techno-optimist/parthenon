"""The real ``ZepGraphMemoryUpdater`` against the local backend (spec §5.4)."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from app.memory.activity import ActivityPolicy
from app.services.zep_graph_memory_updater import AgentActivity, ZepGraphMemoryUpdater


def _activities(simulation_round: int = 1) -> list[AgentActivity]:
    stamp = f"2026-05-10T09:0{simulation_round}:00"

    def make(action, args, agent="Alice Chen", agent_id=1):
        return AgentActivity(platform="twitter", agent_id=agent_id, agent_name=agent, action_type=action,
                             action_args=args, round_num=simulation_round, timestamp=stamp)

    return [
        make("CREATE_POST", {"content": "智巡平台今天在海城市上线，我支持这个项目。"}),
        make("LIKE_POST", {"post_content": "海岳能源宣布终止联合部署协议", "post_author_name": "Bruno"}),
        make("FOLLOW", {"target_user_name": "Bruno"}),
        make("REPOST", {"original_content": "新的管理团队首次公开亮相", "original_author_name": "Bruno"}),
        make("CREATE_COMMENT", {"content": "我不同意", "post_content": "智巡平台今天上线",
                                "post_author_name": "Bruno"}, agent="Chandra", agent_id=2),
    ]


@pytest.fixture
def graph(local):
    local.graph.create(graph_id="mirofish_sim_graph")
    return "mirofish_sim_graph"


def test_rules_mode_updater_round_trip(local, graph, fake_llm):
    updater = ZepGraphMemoryUpdater(graph, api_key=None, simulation_id="sim-1")
    assert updater.client is local
    updater.start()
    for activity in _activities():
        updater.add_activity(activity)
    updater.stop()

    stats = updater.get_stats()
    assert stats["items_sent"] == 5
    assert stats["failed_count"] == 0
    assert stats["pending_episode_count"] == 0
    assert fake_llm.call_count == 0

    episodes = local.graph.episode.get_by_graph_id(graph).episodes
    assert episodes and all(episode.processed for episode in episodes)
    assert episodes[0].metadata["source"] == "mirofish_simulation"
    assert episodes[0].metadata["simulation_id"] == "sim-1"
    edges = {edge.name for edge in local.graph.edge.get_by_graph_id(graph)}
    assert {"POSTED", "LIKED_POST_OF", "FOLLOWS", "REPOSTED", "COMMENTED_ON_POST_OF"} <= edges
    names = {node.name for node in local.graph.node.get_by_graph_id(graph)}
    assert {"Alice Chen", "Bruno", "Chandra", "Twitter"} <= names
    # Every rules fact is searchable once stop() returns.
    results = local.graph.search(query="Alice Chen 智巡平台", graph_id=graph, scope="edges", limit=10)
    assert any("智巡平台" in edge.fact for edge in results.edges)


def _english_activities() -> list[AgentActivity]:
    stamp = "2026-05-10T10:01:00"

    def make(action, args, agent="Alice Chen", agent_id=1):
        return AgentActivity(platform="twitter", agent_id=agent_id, agent_name=agent, action_type=action,
                             action_args=args, round_num=2, timestamp=stamp)

    return [
        make("CREATE_POST", {"content": "Zhixun launched in Harbor City today and I back the project."}),
        make("LIKE_POST", {"post_content": "Haiyue Energy ends the joint deployment deal",
                           "post_author_name": "Bruno O'Neil"}),
        make("FOLLOW", {"target_user_name": "Bruno O'Neil"}),
        make("REPOST", {"original_content": "The new leadership team appears in public",
                        "original_author_name": "Bruno O'Neil"}),
        make("CREATE_COMMENT", {"content": "I disagree", "post_content": "Zhixun launched today",
                                "post_author_name": "Alice Chen"}, agent="Chandra", agent_id=2),
    ]


def test_english_and_chinese_runs_share_one_graph(local, graph, fake_llm):
    english = ZepGraphMemoryUpdater(graph, api_key=None, simulation_id="sim-en", locale="en")
    english.start()
    for activity in _english_activities():
        english.add_activity(activity)
    english.stop()

    chinese = ZepGraphMemoryUpdater(graph, api_key=None, simulation_id="sim-zh", locale="zh")
    chinese.start()
    for activity in _activities():
        chinese.add_activity(activity)
    chinese.stop()

    assert english.get_stats()["items_sent"] == chinese.get_stats()["items_sent"] == 5
    assert fake_llm.call_count == 0
    names: dict[str, set[str]] = {}
    facts: dict[str, list[str]] = {}
    for edge in local.graph.edge.get_by_graph_id(graph):
        names.setdefault(edge.attributes["simulation_id"], set()).add(edge.name)
        facts.setdefault(edge.attributes["simulation_id"], []).append(edge.fact)
    # Both languages yield the same kinds of edges.
    assert names["sim-en"] == names["sim-zh"] == {
        "POSTED", "LIKED_POST_OF", "FOLLOWS", "REPOSTED", "COMMENTED_ON_POST_OF",
    }
    assert "On Twitter, Alice Chen followed the user “Bruno O'Neil”" in facts["sim-en"]
    assert "On Twitter, Chandra commented on Alice Chen's post “Zhixun launched today”: “I disagree”" in facts["sim-en"]
    assert "Alice Chen在Twitter关注了用户「Bruno」" in facts["sim-zh"]
    assert all(fact.startswith("On Twitter, ") for fact in facts["sim-en"])
    assert not any(fact.startswith("On ") for fact in facts["sim-zh"])

    nodes = {node.name: node for node in local.graph.node.get_by_graph_id(graph)}
    # Accounts first seen in the English run keep English summaries.
    assert nodes["Alice Chen"].summary == "Alice Chen is a simulated account on Twitter."
    assert nodes["Twitter"].summary == "Twitter is the social media platform used in the simulation."
    assert nodes["Bruno"].summary == "Bruno是Twitter上的模拟账号。"
    results = local.graph.search(query="Zhixun Harbor City", graph_id=graph, scope="edges", limit=10)
    assert any("Harbor City" in edge.fact for edge in results.edges)


def test_llm_mode_updater_waits_for_enrichment(local, graph, fake_llm, monkeypatch):
    settings = replace(local.settings, activity_mode="llm", activity_group_wait_seconds=0.0)
    monkeypatch.setattr(local, "settings", settings)
    monkeypatch.setattr(local.worker, "settings", settings)
    monkeypatch.setattr(local.worker, "activity_policy", ActivityPolicy.from_settings(settings))
    fake_llm.script = lambda _messages: {
        "entities": [{"name": "Alice Chen", "type": "Entity"}, {"name": "智巡平台", "type": "Entity"}],
        "relations": [{"source": "Alice Chen", "target": "智巡平台", "type": "SUPPORTS",
                       "fact": "Alice Chen支持智巡平台。", "chunks": [1]}],
    }

    stop_draining = threading.Event()

    def drain_until_stopped():
        while not stop_draining.is_set():
            local.worker.drain()
            stop_draining.wait(0.05)

    helper = threading.Thread(target=drain_until_stopped, daemon=True)
    helper.start()
    try:
        updater = ZepGraphMemoryUpdater(graph, api_key=None, simulation_id="sim-llm")
        updater.start()
        for activity in _activities():
            updater.add_activity(activity)
        updater.stop()
    finally:
        stop_draining.set()
        helper.join(10)

    stats = updater.get_stats()
    assert stats["items_sent"] == 5 and stats["pending_episode_count"] == 0
    assert fake_llm.call_count >= 1
    episodes = local.graph.episode.get_by_graph_id(graph).episodes
    assert all(episode.processed for episode in episodes)
    assert {episode.extraction_status for episode in episodes} <= {"succeeded", "skipped"}
    assert "SUPPORTS" in {edge.name for edge in local.graph.edge.get_by_graph_id(graph)}


def test_updater_needs_no_key_locally_but_does_in_zep_mode(local, graph, monkeypatch):
    from app.config import Config

    ZepGraphMemoryUpdater(graph, api_key=None)
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    with pytest.raises(ValueError):
        ZepGraphMemoryUpdater(graph, api_key=None)


def test_english_run_keeps_distinct_short_actions_and_skips_nameless_agents(local, graph, fake_llm):
    def make(action, args, agent="Alice Chen"):
        return AgentActivity(platform="twitter", agent_id=1, agent_name=agent, action_type=action,
                             action_args=args, round_num=1, timestamp="2026-05-10T11:00:00")

    updater = ZepGraphMemoryUpdater(graph, api_key=None, simulation_id="sim-en", locale="en")
    updater.start()
    for activity in [
        make("SEARCH_POSTS", {"query": "no"}), make("SEARCH_POSTS", {"query": "yes"}),
        make("SEARCH_USER", {"query": "NASA"}), make("SEARCH_USER", {"query": "WHO"}),
        make("QUOTE_POST", {"original_author_name": "Bob", "quote_content": "true"}),
        make("QUOTE_POST", {"original_author_name": "Bob", "quote_content": "false"}),
        make("CREATE_POST", {"content": "second"}, agent=""),
        make("LIKE_POST", {"post_content": "x", "post_author_name": "Carol"}, agent=""),
    ]:
        updater.add_activity(activity)
    updater.stop()

    assert updater.get_stats()["failed_count"] == 0
    facts = sorted(edge.fact for edge in local.graph.edge.get_by_graph_id(graph))
    assert facts == [
        "On Twitter, Alice Chen quoted a post by Bob, adding: “false”",
        "On Twitter, Alice Chen quoted a post by Bob, adding: “true”",
        "On Twitter, Alice Chen searched for the user “NASA”",
        "On Twitter, Alice Chen searched for the user “WHO”",
        "On Twitter, Alice Chen searched for “no”",
        "On Twitter, Alice Chen searched for “yes”",
    ]
    assert {node.name for node in local.graph.node.get_by_graph_id(graph)} == {"Alice Chen", "Bob", "Twitter"}
