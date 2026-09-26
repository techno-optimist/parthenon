"""Local graph.search (spec §6): analysis, channels, fusion, rerankers, filters, context.

Fixtures are inserted directly through the store (``seed``); no LLM is involved.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from zep_cloud.errors import BadRequestError, NotFoundError
from zep_cloud.types import DateFilter, EntityEdge, EntityNode, Episode, GraphSearchResults, SearchFilters

from app.memory import LocalMemorySettings, MemoryStore, StoreCaps
from app.memory.search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    RERANKERS,
    DenseCandidate,
    GraphSearcher,
    MentionIndex,
    QueryTerm,
    analyze_query,
    build_context,
    fts_match_expression,
)
from app.memory.store import TOKENIZER_NONE, TOKENIZER_UNICODE61
from app.memory.textnorm import name_key

EN_PROFILE_QUERY = "All information, activities, events, relationships and background about {name}"
ZH_PROFILE_QUERY = "关于{name}的所有信息、活动、事件、关系和背景"


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _update(store: MemoryStore, table: str, uuid: str, **columns: Any) -> None:
    assignments = ", ".join(f"{name} = ?" for name in columns)
    with store.write() as conn:
        conn.execute(f"UPDATE {table} SET {assignments} WHERE uuid = ?", (*columns.values(), uuid))


def _link_node_episode(store: MemoryStore, node_uuid: str, episode_uuid: str) -> None:
    with store.write() as conn:
        conn.execute("INSERT INTO node_episodes(node_uuid, episode_uuid) VALUES (?, ?)", (node_uuid, episode_uuid))


def _uuids(items: list[Any]) -> list[str]:
    return [item.uuid_ for item in items]


def _assert_scores(items: list[Any]) -> None:
    scores = [item.score for item in items]
    assert all(0.0 < score <= 1.0 for score in scores), scores
    assert scores == sorted(scores, reverse=True)
    if scores:
        assert scores[0] == 1.0
    assert all(item.relevance == item.score for item in items)


@pytest.fixture
def searcher(local, memory_settings) -> GraphSearcher:
    return GraphSearcher(local.store, memory_settings)


@pytest.fixture
def corpus(local, seed) -> SimpleNamespace:
    """A small mixed English/Chinese graph (``g1``) used by most tests."""

    g = seed.graph("g1")
    n = SimpleNamespace(graph_id=g)
    n.alice = seed.node(g, "Alice Chen", "Person", summary="Alice Chen is the chief executive of Acme Corp.",
                        aliases=("Dr. Alice Chen",))
    n.acme = seed.node(g, "Acme Corp", "Organization", summary="Acme Corp builds industrial robots.")
    n.beta = seed.node(g, "Beta Labs", "Organization", summary="Beta Labs is a research lab.")
    n.chen_wei = seed.node(g, "Chen Wei", "Person", summary="Chen Wei is an engineer.")
    n.paris = seed.node(g, "Paris", "Location", summary="Paris is the capital of France.")
    n.alice_smith = seed.node(g, "Alice Smith", "Person", summary="Alice Smith is a journalist.")
    n.chen_long = seed.node(g, "Chen Long", "Person", summary="Chen Long is a photographer.")
    n.zhang = seed.node(g, "张伟", "Person", summary="张伟是阿里巴巴的工程师。")
    n.alibaba = seed.node(g, "阿里巴巴", "Organization", summary="阿里巴巴是一家科技公司。")

    n.ep_join = seed.episode(g, "Alice Chen joined Acme Corp in 2021 as chief executive.")
    n.ep_paris = seed.episode(g, "Alice Chen moved to Paris.")
    n.ep_lina = seed.episode(g, "李娜在上海发布了一条帖子。", kind="activity",
                             source_description="MiroFish simulation activity batch")

    n.e_acme = seed.edge(g, n.alice, n.acme, "WORKS_FOR", "Alice Chen works for Acme Corp as chief executive.",
                         episodes=(n.ep_join,))
    n.e_paris = seed.edge(g, n.alice, n.paris, "LIVES_IN", "Alice Chen lives in Paris.", episodes=(n.ep_paris,))
    n.e_old = seed.edge(g, n.alice, n.beta, "WORKS_FOR", "Alice Chen worked for Beta Labs.")
    _update(local.store, "edges", n.e_old, invalid_at="2020-12-31T00:00:00.000000Z",
            expired_at="2021-01-02T00:00:00.000000Z")
    n.e_chen_beta = seed.edge(g, n.chen_wei, n.beta, "WORKS_FOR", "Chen Wei works for Beta Labs.")
    n.e_partners = seed.edge(g, n.acme, n.beta, "PARTNERS_WITH",
                             "Acme Corp partners with Beta Labs on robotics research.")
    n.e_smith = seed.edge(g, n.alice_smith, n.chen_long, "MET", "Alice Smith met Chen Long.")
    n.e_zhang = seed.edge(g, n.zhang, n.alibaba, "WORKS_FOR", "张伟在阿里巴巴担任工程师。")
    n.e_lina = seed.edge(g, n.zhang, n.alibaba, "DISCUSSED_WITH", "张伟和李娜讨论了机器人。")
    n.alice_edges = {n.e_acme, n.e_paris, n.e_old}
    return n


# ---------------------------------------------------------------------------
# Query analysis (§6.2)
# ---------------------------------------------------------------------------


def test_analysis_strips_profile_templates_and_stopwords():
    english = analyze_query(EN_PROFILE_QUERY.format(name="Alice Chen"))
    assert english.fts_terms == ("alice", "chen")
    assert english.short_terms == ()
    assert english.match == '"alice" OR "chen"'

    chinese = analyze_query(ZH_PROFILE_QUERY.format(name="张伟"))
    assert chinese.fts_terms == ()
    assert chinese.short_terms == ("张伟",)
    assert chinese.like_terms == (QueryTerm("张伟"),)


def test_analysis_builds_cjk_trigrams_and_short_terms():
    analysis = analyze_query("阿里巴巴的工程师 AI 张 x")
    assert analysis.fts_terms == ("阿里巴", "里巴巴", "巴巴的", "巴的工", "的工程", "工程师")
    # 1-character runs are dropped; 2-character Latin words match whole words only.
    assert analysis.like_terms == (QueryTerm("ai", whole_word=True),)

    mixed = analyze_query("ＡＩ李娜")  # full-width letters are NFKC-normalized
    assert mixed.short_terms == ("ai", "李娜")
    assert mixed.like_terms == (QueryTerm("ai", whole_word=True), QueryTerm("李娜"))


def test_analysis_dedupes_and_caps_terms():
    words = " ".join(f"word{i:03d}" for i in range(100))
    analysis = analyze_query(f"{words} word000 word001")
    assert len(analysis.fts_terms) == 48
    assert len(set(analysis.fts_terms)) == 48
    short = " ".join(f"{chr(97 + i)}{chr(97 + i)}" for i in range(20))
    assert len(analyze_query(short).short_terms) == 8
    assert len(analyze_query("x" * 5000).query) == 2000


def test_analysis_routes_terms_by_tokenizer():
    query = "robots 担任工程师 李娜"
    unicode61 = analyze_query(query, TOKENIZER_UNICODE61)
    assert unicode61.fts_terms == ("robots",)
    assert [term.text for term in unicode61.like_terms] == ["李娜", "担任工", "任工程", "工程师"]

    none = analyze_query(query, TOKENIZER_NONE)
    assert none.fts_terms == ()
    assert none.match == ""
    assert [term.text for term in none.like_terms] == ["李娜", "robots", "担任工", "任工程", "工程师"]
    assert {term.text for term in none.coverage_terms} == {term.text for term in none.like_terms}


def test_fts_match_expression_quotes_every_term():
    assert fts_match_expression(["abc", 'a"b']) == '"abc" OR "a""b"'
    assert fts_match_expression([]) == ""


# ---------------------------------------------------------------------------
# Mention detection (§6.3, channel 3)
# ---------------------------------------------------------------------------


def _index(*names: tuple[str, str]) -> MentionIndex:
    return MentionIndex((name_key(name), uuid, True, 1) for name, uuid in names)


def test_mentions_need_word_boundaries_for_latin_keys():
    index = _index(("AI", "n-ai"))
    assert [m.node_uuid for m in index.find("AI policy in the EU")] == ["n-ai"]
    assert index.find("he said so") == []
    assert [m.node_uuid for m in index.find("ai小组")] == ["n-ai"]


def test_mentions_keep_the_longest_match():
    index = _index(("Alice Chen", "n-alice"), ("Chen", "n-chen"))
    assert [m.node_uuid for m in index.find("about Alice Chen")] == ["n-alice"]
    # A separate occurrence of the shorter key still counts.
    assert [m.node_uuid for m in index.find("Chen met Alice Chen")] == ["n-alice", "n-chen"]


def test_mentions_ignore_template_phrases_and_stopword_keys():
    index = _index(("关系", "n-rel"), ("张伟", "n-zhang"), ("US", "n-us"), ("阿里巴巴", "n-ali"))
    assert [m.node_uuid for m in index.find(ZH_PROFILE_QUERY.format(name="张伟"))] == ["n-zhang"]
    assert index.find("tell us about it") == []
    # CJK keys match as substrings.
    assert [m.node_uuid for m in index.find("张伟在阿里巴巴工作")] == ["n-ali", "n-zhang"]


# ---------------------------------------------------------------------------
# Validation (§6.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("overrides", [
    {"user_id": "u1"},
    {"graph_id": None},
    {"graph_id": ""},
    {"query": ""},
    {"query": "   "},
    {"query": None},
    {"query": 42},
    {"limit": 0},
    {"limit": -3},
    {"limit": "many"},
    {"limit": True},
    {"scope": "everything"},
    {"reranker": "bm25"},
    {"reranker": "node_distance"},
    {"mmr_lambda": 1.5},
    {"mmr_lambda": "high"},
    {"max_characters": 0},
    {"center_node_uuid": ""},
    {"bfs_origin_node_uuids": "not-a-list"},
    {"bfs_origin_node_uuids": [1, 2]},
    {"search_filters": "Person"},
    {"search_filters": {"node_labels": 5}},
    {"search_filters": {"edge_types": ["WORKS_FOR", 3]}},
])
def test_invalid_arguments_raise_400(searcher, corpus, overrides):
    kwargs = {"query": "Alice", "graph_id": corpus.graph_id, **overrides}
    with pytest.raises(BadRequestError) as caught:
        searcher.search(**kwargs)
    assert caught.value.status_code == 400


def test_missing_graph_raises_zep_not_found(searcher, corpus):
    with pytest.raises(NotFoundError) as caught:
        searcher.search(query="Alice", graph_id="no-such-graph")
    assert caught.value.status_code == 404
    assert type(caught.value).__module__.startswith("zep_cloud")


def test_node_distance_with_unknown_center_is_not_found(searcher, corpus):
    with pytest.raises(NotFoundError):
        searcher.search(query="Alice", graph_id=corpus.graph_id, reranker="node_distance",
                        center_node_uuid="missing-node")


def test_sdk_omit_sentinel_request_options_and_raw_flag_are_accepted(searcher, corpus):
    result = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, limit=..., scope=..., reranker=...,
                             search_filters=..., mmr_lambda=..., return_raw_results=True,
                             request_options={"timeout_in_seconds": 5})
    assert result.edges and result.nodes == [] and result.episodes == []


# ---------------------------------------------------------------------------
# Scopes (§6.1, §6.5)
# ---------------------------------------------------------------------------


def test_edge_scope_returns_sdk_edges_with_episodes(searcher, corpus):
    result = searcher.search(query="Alice Chen Paris", graph_id=corpus.graph_id)
    assert isinstance(result, GraphSearchResults)
    assert result.nodes == [] and result.episodes == []
    assert result.observations == [] and result.thread_summaries == []
    assert result.context is None
    assert all(isinstance(edge, EntityEdge) for edge in result.edges)
    top = result.edges[0]
    assert top.uuid_ == corpus.e_paris
    assert top.name == "LIVES_IN"
    assert top.source_node_uuid == corpus.alice and top.target_node_uuid == corpus.paris
    assert top.episodes == [corpus.ep_paris]
    old = next(edge for edge in result.edges if edge.uuid_ == corpus.e_old)
    assert old.invalid_at == "2020-12-31T00:00:00.000000Z" and old.expired_at is not None
    _assert_scores(result.edges)


def test_node_scope_returns_sdk_nodes(searcher, corpus):
    result = searcher.search(query="robots", graph_id=corpus.graph_id, scope="nodes")
    assert result.edges == [] and result.episodes == []
    assert all(isinstance(node, EntityNode) for node in result.nodes)
    assert _uuids(result.nodes) == [corpus.acme]
    assert result.nodes[0].labels == ["Entity", "Organization"]
    assert result.nodes[0].summary == "Acme Corp builds industrial robots."
    _assert_scores(result.nodes)


def test_episode_scope_returns_episodes_newest_first_on_ties(searcher, seed):
    g = seed.graph("g-episodes")
    older = seed.episode(g, "Quarterly robotics review.")
    newer = seed.episode(g, "Quarterly robotics review.")
    other = seed.episode(g, "Weather report.")
    result = searcher.search(query="robotics review", graph_id=g, scope="episodes")
    assert _uuids(result.episodes) == [newer, older]
    assert other not in _uuids(result.episodes)
    episode = result.episodes[0]
    assert isinstance(episode, Episode)
    assert episode.content == "Quarterly robotics review."
    assert episode.processed is False and episode.metadata == {}
    _assert_scores(result.episodes)


def test_auto_scope_fills_every_list_and_builds_context(searcher, corpus):
    result = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, scope="auto", limit=6)
    assert result.edges and result.nodes and result.episodes
    assert len(result.edges) <= 6
    assert len(result.nodes) <= 3 and len(result.episodes) <= 3
    assert result.nodes[0].uuid_ == corpus.alice
    context = result.context
    assert context.startswith("FACTS and ENTITIES represent relevant context to the current conversation.")
    assert "<FACTS>" in context and "</ENTITIES>" in context
    assert "  - Alice Chen worked for Beta Labs. (Date range: unknown - 2020-12-31T00:00:00.000000Z)" in context
    assert "  - Alice Chen: Alice Chen is the chief executive of Acme Corp." in context


def test_max_characters_builds_a_bounded_context_for_any_scope(searcher, corpus):
    result = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, max_characters=320)
    assert result.context is not None and len(result.context) <= 320
    assert result.context.endswith("</ENTITIES>")
    assert "<FACTS>" in result.context


@pytest.mark.parametrize("scope", ["observations", "thread_summaries"])
def test_unsupported_result_scopes_return_empty_lists(searcher, corpus, scope):
    result = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, scope=scope)
    assert (result.edges, result.nodes, result.episodes) == ([], [], [])
    assert (result.observations, result.thread_summaries) == ([], [])


def test_limit_defaults_to_10_and_clamps_to_50(searcher, seed):
    g = seed.graph("g-bulk")
    hub = seed.node(g, "Hub")
    for i in range(60):
        seed.edge(g, hub, seed.node(g, f"Item {i}"), "REPORTS", f"Widget report number {i}.")
    assert len(searcher.search(query="widget", graph_id=g).edges) == DEFAULT_LIMIT
    assert len(searcher.search(query="widget", graph_id=g, limit=100).edges) == MAX_LIMIT
    assert len(searcher.search(query="widget", graph_id=g, limit=3).edges) == 3


# ---------------------------------------------------------------------------
# Channels (§6.3)
# ---------------------------------------------------------------------------


def test_cjk_trigram_query_hits_the_fts_index(searcher, corpus):
    assert analyze_query("担任工程师").fts_terms  # FTS only: no node is named in the query
    result = searcher.search(query="担任工程师", graph_id=corpus.graph_id)
    assert _uuids(result.edges)[0] == corpus.e_zhang


def test_two_character_cjk_name_is_found_via_like(searcher, corpus):
    analysis = analyze_query("李娜")
    assert analysis.fts_terms == () and analysis.like_terms == (QueryTerm("李娜"),)
    edges = searcher.search(query="李娜", graph_id=corpus.graph_id).edges
    assert _uuids(edges) == [corpus.e_lina]
    episodes = searcher.search(query="李娜", graph_id=corpus.graph_id, scope="episodes").episodes
    assert _uuids(episodes) == [corpus.ep_lina]


def test_mention_channel_ranks_the_entitys_edges_first(searcher, corpus):
    query = EN_PROFILE_QUERY.format(name="Alice Chen")
    edges = searcher.search(query=query, graph_id=corpus.graph_id, limit=30, reranker="rrf").edges
    ranked = _uuids(edges)
    # "Alice Smith met Chen Long." matches both words and is shorter, but only
    # Alice Chen herself is mentioned: all her edges come first.
    assert set(ranked[:3]) == corpus.alice_edges
    assert ranked.index(corpus.e_smith) > 2
    # The invalidated fact is still returned, below the active ones.
    assert ranked.index(corpus.e_old) == 2

    nodes = searcher.search(query=query, graph_id=corpus.graph_id, limit=20, scope="nodes").nodes
    assert nodes[0].uuid_ == corpus.alice


def test_chinese_profile_query_finds_the_entity(searcher, corpus):
    query = ZH_PROFILE_QUERY.format(name="张伟")
    edges = searcher.search(query=query, graph_id=corpus.graph_id, limit=30).edges
    assert set(_uuids(edges)) == {corpus.e_zhang, corpus.e_lina}
    nodes = searcher.search(query=query, graph_id=corpus.graph_id, limit=20, scope="nodes").nodes
    assert nodes[0].uuid_ == corpus.zhang


def test_short_latin_terms_match_whole_words_only(searcher, seed):
    g = seed.graph("g-ai")
    board, member = seed.node(g, "Board"), seed.node(g, "Member")
    hit = seed.edge(g, board, member, "DISCUSSED", "The AI safety board met.")
    seed.edge(g, member, board, "SAID", "He said the board met.")
    assert _uuids(searcher.search(query="AI", graph_id=g).edges) == [hit]


def test_empty_or_stopword_only_queries_return_empty_lists(searcher, corpus):
    for query in ("the and of about", "???", "张", "关于的所有信息"):
        result = searcher.search(query=query, graph_id=corpus.graph_id, scope="auto")
        assert (result.edges, result.nodes, result.episodes) == ([], [], []), query
        assert result.observations == [] and result.thread_summaries == []


# ---------------------------------------------------------------------------
# Rerankers (§6.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["edges", "nodes", "episodes"])
@pytest.mark.parametrize("reranker", RERANKERS)
def test_every_reranker_is_accepted_and_deterministic(searcher, corpus, scope, reranker):
    kwargs: dict[str, Any] = {"query": "Alice Chen Acme Paris", "graph_id": corpus.graph_id,
                              "scope": scope, "reranker": reranker}
    if reranker == "node_distance":
        kwargs["center_node_uuid"] = corpus.alice
    first = searcher.search(**kwargs)
    searcher.invalidate()
    second = searcher.search(**kwargs)
    items = getattr(first, scope)
    assert items, (scope, reranker)
    assert [(i.uuid_, i.score) for i in items] == [(i.uuid_, i.score) for i in getattr(second, scope)]
    _assert_scores(items)


def test_cross_encoder_rewards_term_coverage(searcher, corpus):
    edges = searcher.search(query="Alice Paris", graph_id=corpus.graph_id, reranker="cross_encoder").edges
    assert edges[0].uuid_ == corpus.e_paris


def test_mmr_diversifies_near_duplicate_facts(searcher, seed):
    g = seed.graph("g-mmr")
    person, org1, org2, city = (seed.node(g, name) for name in ("P1", "O1", "O2", "L1"))
    corp = seed.edge(g, person, org1, "WORKS_FOR", "Alice Chen works for Acme Corp.")
    corporation = seed.edge(g, person, org2, "WORKS_FOR", "Alice Chen works for Acme Corporation.")
    paris = seed.edge(g, person, city, "LIVES_IN", "Alice Chen lives in Paris.")
    query = "Alice Chen works for Acme"

    assert _uuids(searcher.search(query=query, graph_id=g).edges) == [corp, corporation, paris]
    mmr = searcher.search(query=query, graph_id=g, reranker="mmr").edges
    assert _uuids(mmr) == [corp, paris, corporation]
    _assert_scores(mmr)
    # lambda = 1 is pure relevance.
    assert _uuids(searcher.search(query=query, graph_id=g, reranker="mmr", mmr_lambda=1.0).edges) == [
        corp, corporation, paris]


def test_episode_mentions_boosts_edges_seen_in_more_episodes(searcher, seed):
    g = seed.graph("g-mentions")
    a, b, c, d = (seed.node(g, name) for name in ("N1", "N2", "N3", "N4"))
    once = seed.edge(g, a, b, "ACQUIRED", "Gamma Corp acquired Delta Inc.")
    episodes = tuple(seed.episode(g, f"Report {i}") for i in range(3))
    thrice = seed.edge(g, c, d, "ACQUIRED", "Gamma Corp acquired Delta Inc.", episodes=episodes)

    assert _uuids(searcher.search(query="Gamma acquired", graph_id=g).edges) == [once, thrice]
    boosted = searcher.search(query="Gamma acquired", graph_id=g, reranker="episode_mentions").edges
    assert _uuids(boosted) == [thrice, once]
    assert boosted[0].episodes == list(episodes)


def test_node_distance_prefers_edges_near_the_center(searcher, corpus):
    plain = _uuids(searcher.search(query="works", graph_id=corpus.graph_id).edges)
    assert plain[:2] == [corpus.e_chen_beta, corpus.e_acme]

    near_alice = searcher.search(query="works", graph_id=corpus.graph_id, reranker="node_distance",
                                 center_node_uuid=corpus.alice).edges
    ranked = _uuids(near_alice)
    assert ranked[0] == corpus.e_acme
    # The two-hop neighbourhood joins as a channel; unrelated edges do not.
    assert {corpus.e_paris, corpus.e_old, corpus.e_partners} <= set(ranked)
    assert not {corpus.e_lina, corpus.e_smith} & set(ranked)
    # Zhang's edge matches only through its relation name (WORKS_FOR) and is
    # far from Alice, so it comes last.
    assert ranked[-1] == corpus.e_zhang

    near_chen = searcher.search(query="works", graph_id=corpus.graph_id, reranker="node_distance",
                                center_node_uuid=corpus.chen_wei).edges
    assert near_chen[0].uuid_ == corpus.e_chen_beta

    nodes = searcher.search(query="Chen", graph_id=corpus.graph_id, scope="nodes", reranker="node_distance",
                            center_node_uuid=corpus.chen_wei).nodes
    assert nodes[0].uuid_ == corpus.chen_wei


def test_episode_scope_uses_node_links_for_distance_and_bfs(local, searcher, corpus):
    _link_node_episode(local.store, corpus.alice, corpus.ep_join)   # 2 hops from Chen Wei
    _link_node_episode(local.store, corpus.paris, corpus.ep_paris)  # 3 hops from Chen Wei
    plain = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, scope="episodes").episodes
    assert _uuids(plain) == [corpus.ep_paris, corpus.ep_join]

    near = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, scope="episodes",
                           reranker="node_distance", center_node_uuid=corpus.chen_wei).episodes
    assert _uuids(near) == [corpus.ep_join, corpus.ep_paris]
    region = searcher.search(query="Alice Chen", graph_id=corpus.graph_id, scope="episodes",
                             bfs_origin_node_uuids=[corpus.chen_wei]).episodes
    assert _uuids(region) == [corpus.ep_join]


def test_node_scope_episode_mentions_counts_node_links(local, searcher, corpus):
    for episode in (corpus.ep_join, corpus.ep_paris):
        _link_node_episode(local.store, corpus.chen_long, episode)
    plain = _uuids(searcher.search(query="Chen", graph_id=corpus.graph_id, scope="nodes").nodes)
    assert plain[0] != corpus.chen_long
    boosted = searcher.search(query="Chen", graph_id=corpus.graph_id, scope="nodes",
                              reranker="episode_mentions").nodes
    assert boosted[0].uuid_ == corpus.chen_long


def test_invalidated_edges_are_penalized(local, seed, memory_settings):
    g = seed.graph("g-penalty")
    a, b, c = (seed.node(g, name) for name in ("N1", "N2", "N3"))
    invalid = seed.edge(g, a, b, "HIRED", "Omega Ltd hired Sigma.")  # lower id: FTS rank 1
    _update(local.store, "edges", invalid, invalid_at="2024-01-01T00:00:00.000000Z")
    active = seed.edge(g, a, c, "HIRED", "Omega Ltd hired Sigma.")

    penalized = GraphSearcher(local.store, memory_settings).search(query="Omega hired", graph_id=g).edges
    assert _uuids(penalized) == [active, invalid]
    # base(invalid) = 1.0 * 0.7 (FTS rank 1); base(active) = (1/62) / (1/61) (rank 2).
    assert penalized[1].score == pytest.approx(0.7 / (61 / 62), abs=1e-6)

    no_penalty = LocalMemorySettings(search_invalid_penalty=1.0)
    unpenalized = GraphSearcher(local.store, no_penalty).search(query="Omega hired", graph_id=g).edges
    assert _uuids(unpenalized) == [invalid, active]


# ---------------------------------------------------------------------------
# Filters (§6.6)
# ---------------------------------------------------------------------------


def test_edge_filters(searcher, corpus):
    g = corpus.graph_id

    def edges(query: str, filters: Any) -> set[str]:
        return set(_uuids(searcher.search(query=query, graph_id=g, limit=50, search_filters=filters).edges))

    works_for = edges("Alice Chen", {"edge_types": ["WORKS_FOR"]})
    assert works_for and corpus.e_paris not in works_for
    assert corpus.e_acme in works_for and corpus.e_old in works_for
    assert corpus.e_paris not in edges("Alice Chen", {"node_labels": ["Person", "Organization"]})
    assert corpus.e_acme in edges("Alice Chen", {"node_labels": ["Person", "Organization"]})
    # Both endpoints must carry one of the labels.
    assert edges("Acme Beta", {"node_labels": ["Organization"]}) == {corpus.e_partners}
    assert corpus.e_paris not in edges("Alice Chen", {"exclude_node_labels": ["Location"]})
    assert not {corpus.e_acme, corpus.e_old} & edges("Alice Chen", {"exclude_edge_types": ["WORKS_FOR"]})
    assert edges("Alice Chen", {"edge_uuids": [corpus.e_paris]}) == {corpus.e_paris}
    assert edges("Alice Chen", SearchFilters(edge_types=["LIVES_IN"])) == {corpus.e_paris}


def test_node_label_filters(searcher, corpus):
    def nodes(filters: Any) -> list[EntityNode]:
        return searcher.search(query="Alice Chen Acme Paris", graph_id=corpus.graph_id, scope="nodes",
                               search_filters=filters).nodes

    people = nodes(SearchFilters(node_labels=["Person"]))
    assert people and all("Person" in node.labels for node in people)
    others = nodes({"exclude_node_labels": ["Person"]})
    assert others and all("Person" not in node.labels for node in others)
    assert {corpus.acme, corpus.paris} <= set(_uuids(others))


def test_unsupported_filters_are_accepted_and_ignored(searcher, corpus):
    baseline = _uuids(searcher.search(query="Alice Chen", graph_id=corpus.graph_id).edges)
    filters = SearchFilters(
        created_at=[[DateFilter(comparison_operator=">", date="2030-01-01T00:00:00Z")]],
        valid_at=[[DateFilter(comparison_operator="<", date="2000-01-01T00:00:00Z")]],
    )
    assert _uuids(searcher.search(query="Alice Chen", graph_id=corpus.graph_id, search_filters=filters).edges) \
        == baseline
    loose = {"property_filters": [{"property_name": "x"}], "episode_metadata_filters": {"k": "v"}}
    assert _uuids(searcher.search(query="Alice Chen", graph_id=corpus.graph_id, search_filters=loose).edges) \
        == baseline


def test_bfs_origins_restrict_results_to_two_hops(searcher, corpus):
    # Chen Wei -> Beta Labs (1 hop) -> Acme Corp, Alice Chen (2 hops).
    unrestricted = set(_uuids(searcher.search(query="Alice", graph_id=corpus.graph_id).edges))
    assert corpus.e_smith in unrestricted
    restricted = set(_uuids(searcher.search(query="Alice", graph_id=corpus.graph_id,
                                            bfs_origin_node_uuids=[corpus.chen_wei]).edges))
    assert corpus.e_smith not in restricted
    assert corpus.e_acme in restricted and corpus.e_paris in restricted

    nodes = set(_uuids(searcher.search(query="Chen", graph_id=corpus.graph_id, scope="nodes",
                                       bfs_origin_node_uuids=[corpus.chen_wei]).nodes))
    assert nodes == {corpus.chen_wei, corpus.alice}

    nowhere = searcher.search(query="Alice", graph_id=corpus.graph_id, bfs_origin_node_uuids=["missing"])
    assert nowhere.edges == []


# ---------------------------------------------------------------------------
# Capability fallbacks (§6.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("caps", [StoreCaps(fts5=True, trigram=False), StoreCaps(fts5=False, trigram=False)],
                         ids=["unicode61", "no-fts5"])
def test_search_works_without_trigram_or_fts5(tmp_path, seed, memory_settings, caps):
    store = MemoryStore(tmp_path / "fallback.sqlite3", caps=caps)
    try:
        seeder = type(seed)(store)
        g = seeder.graph("g-fallback")
        acme, zhang, board = seeder.node(g, "Acme Corp", "Organization"), seeder.node(g, "张伟"), seeder.node(g, "Board")
        robots = seeder.edge(g, acme, board, "BUILDS", "Acme Corp builds industrial robots in Shenzhen.")
        engineer = seeder.edge(g, zhang, acme, "WORKS_FOR", "张伟在阿里巴巴担任工程师。")
        lina = seeder.edge(g, zhang, board, "DISCUSSED", "张伟和李娜讨论了机器人。")
        ai = seeder.edge(g, board, acme, "DISCUSSED", "The AI safety board met.")
        seeder.edge(g, acme, zhang, "SAID", "He said the board met.")
        searcher = GraphSearcher(store, memory_settings)

        def top(query: str) -> list[str]:
            return _uuids(searcher.search(query=query, graph_id=g).edges)

        assert top("robots")[0] == robots
        assert top("担任工程师")[0] == engineer
        assert top("李娜") == [lina]
        assert top("AI") == [ai]
        nodes = searcher.search(query="Acme", graph_id=g, scope="nodes").nodes
        assert nodes[0].uuid_ == acme
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Context string (§6.7)
# ---------------------------------------------------------------------------


def _edge(fact: str, **fields: Any) -> EntityEdge:
    return EntityEdge(uuid_=fact, name="X", fact=fact, source_node_uuid="a", target_node_uuid="b",
                      created_at="2024-01-01T00:00:00.000000Z", **fields)


def test_context_lists_date_ranges_and_entities():
    context = build_context(
        [_edge("Active fact.", valid_at="2024-01-01T00:00:00.000000Z"),
         _edge("Expired\nfact.", expired_at="2024-06-01T00:00:00.000000Z")],
        [EntityNode(uuid_="n", name="Alice", labels=["Entity"], summary="A person.", created_at="t")],
    )
    assert context.split("\n") == [
        "FACTS and ENTITIES represent relevant context to the current conversation.",
        "# These are the most relevant facts and their valid date ranges",
        "<FACTS>",
        "  - Active fact. (Date range: 2024-01-01T00:00:00.000000Z - present)",
        "  - Expired fact. (Date range: unknown - 2024-06-01T00:00:00.000000Z)",
        "</FACTS>",
        "# These are the most relevant entities",
        "<ENTITIES>",
        "  - Alice: A person.",
        "</ENTITIES>",
    ]


def test_context_truncates_on_line_boundaries():
    edges = [_edge(f"Fact number {i} with some padding text.") for i in range(200)]
    context = build_context(edges, [])
    assert len(context) <= 5000 and context.endswith("</ENTITIES>")
    bounded = build_context(edges, [], max_characters=400)
    assert len(bounded) <= 400 and bounded.endswith("</ENTITIES>")
    assert all(line.endswith("- present)") for line in bounded.split("\n") if line.startswith("  - "))
    assert "Fact number 0 " in bounded
    tiny = build_context(edges, [], max_characters=80)
    assert len(tiny) <= 80
    assert tiny == "FACTS and ENTITIES represent relevant context to the current conversation."


# ---------------------------------------------------------------------------
# Caching, hooks, transactions and concurrency (§6.8, §6.9)
# ---------------------------------------------------------------------------


def test_mention_index_follows_graph_changes(local, seed, searcher, corpus):
    with local.store.read() as conn:
        first = searcher.mention_index(conn, corpus.graph_id)
        assert searcher.mention_index(conn, corpus.graph_id) is first
    assert first.find("Delta Force") == []

    # A writer that forgets to bump graphs.version still invalidates the cache.
    delta = seed.node(corpus.graph_id, "Delta Force", "Organization")
    with local.store.read() as conn:
        second = searcher.mention_index(conn, corpus.graph_id)
    assert second is not first
    assert [m.node_uuid for m in second.find("news about Delta Force")] == [delta]

    with local.store.write() as conn:
        conn.execute("UPDATE graphs SET version = version + 1 WHERE graph_id = ?", (corpus.graph_id,))
    with local.store.read() as conn:
        third = searcher.mention_index(conn, corpus.graph_id)
        assert third is not second
        searcher.invalidate(corpus.graph_id)
        assert searcher.mention_index(conn, corpus.graph_id) is not third


def test_dense_retriever_adds_one_rrf_channel(local, memory_settings, seed):
    g = seed.graph("g-dense")
    a, b, c = (seed.node(g, name) for name in ("N1", "N2", "N3"))
    first = seed.edge(g, a, b, "HIRED", "Omega Ltd hired Sigma.")
    second = seed.edge(g, a, c, "HIRED", "Omega Ltd hired Sigma.")

    class Dense:
        def __init__(self) -> None:
            self.calls: list[list[DenseCandidate]] = []

        def rank(self, graph_id, query, candidates):
            self.calls.append(list(candidates))
            return [(second, 0.9)]

    dense = Dense()
    ranked = GraphSearcher(local.store, memory_settings, dense_retriever=dense).search(
        query="Omega hired", graph_id=g).edges
    assert _uuids(ranked) == [second, first]
    assert {c.uuid for c in dense.calls[0]} == {first, second}
    assert {c.kind for c in dense.calls[0]} == {"edge"}

    class Broken:
        def rank(self, graph_id, query, candidates):
            raise RuntimeError("embedding service down")

    fallback = GraphSearcher(local.store, memory_settings, dense_retriever=Broken()).search(
        query="Omega hired", graph_id=g).edges
    assert _uuids(fallback) == [first, second]


def test_search_inside_a_write_sees_uncommitted_rows(local, seed, searcher, corpus):
    with local.store.write():
        omega = seed.node(corpus.graph_id, "Omega AI Lab", "Organization")
        edge = seed.edge(corpus.graph_id, corpus.alice, omega, "ADVISES", "Alice Chen advises the AI lab.")
        result = searcher.search(query="AI lab", graph_id=corpus.graph_id)
        assert result.edges[0].uuid_ == edge


def test_concurrent_searches_while_writing(local, seed, searcher, corpus):
    stop = threading.Event()
    errors: list[BaseException] = []
    written: list[str] = []

    def writer() -> None:
        try:
            i = 0
            while not stop.is_set():
                written.append(seed.edge(corpus.graph_id, corpus.alice, corpus.acme, "MET",
                                         f"Alice Chen met the Acme board, meeting {i}."))
                i += 1
                stop.wait(0.002)
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    queries = [
        {"query": EN_PROFILE_QUERY.format(name="Alice Chen"), "scope": "edges", "limit": 30},
        {"query": ZH_PROFILE_QUERY.format(name="张伟"), "scope": "nodes", "limit": 20},
        {"query": "Acme board", "scope": "auto", "reranker": "cross_encoder"},
        {"query": "robots", "scope": "episodes", "reranker": "mmr"},
    ]

    def reader(n: int) -> None:
        try:
            for i in range(12):
                result = searcher.search(graph_id=corpus.graph_id, **queries[(n + i) % len(queries)])
                for items in (result.edges, result.nodes, result.episodes):
                    assert isinstance(items, list)
                    assert all(0.0 < item.score <= 1.0 for item in items)
        except BaseException as error:
            errors.append(error)

    write_thread = threading.Thread(target=writer)
    readers = [threading.Thread(target=reader, args=(n,)) for n in range(16)]
    write_thread.start()
    for thread in readers:
        thread.start()
    for thread in readers:
        thread.join(timeout=60)
    stop.set()
    write_thread.join(timeout=30)
    assert not errors, errors[:3]
    assert written
    assert searcher.search(query="meeting", graph_id=corpus.graph_id, limit=50).edges
