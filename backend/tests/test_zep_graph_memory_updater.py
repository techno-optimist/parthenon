from types import SimpleNamespace
import json
import threading
from queue import Queue

import pytest
from flask import Flask

from app.services import zep_graph_memory_updater as updater_module
from app.services.zep_graph_memory_updater import (
    AgentActivity,
    ZepGraphMemoryManager,
    ZepGraphMemoryUpdater,
)
from app.utils.locale import get_locale, set_locale


def _activity(index=1, content="hello"):
    return AgentActivity(
        platform="twitter",
        agent_id=index,
        agent_name=f"Agent {index}",
        action_type="CREATE_POST",
        action_args={"content": content},
        round_num=index,
        timestamp="2026-07-22T12:00:00+08:00",
    )


def _client(add):
    return SimpleNamespace(
        graph=SimpleNamespace(
            add=add,
            episode=SimpleNamespace(
                get=lambda **_kwargs: SimpleNamespace(processed=True)
            ),
        )
    )


def _updater(monkeypatch, add, simulation_id="sim-1"):
    client = _client(add)
    monkeypatch.setattr(updater_module, "get_zep_client", lambda _key: client)
    updater = ZepGraphMemoryUpdater(
        "graph-1",
        api_key="test-key",
        simulation_id=simulation_id,
    )
    updater.SEND_INTERVAL = 0
    return updater


def test_stop_drains_an_immediately_queued_tail_activity(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
    )

    updater.start()
    updater.add_activity(_activity())
    updater.stop()

    assert len(writes) == 1
    assert updater.get_stats()["items_sent"] == 1
    assert updater.get_stats()["queue_size"] == 0


def test_network_write_happens_outside_the_buffer_lock(monkeypatch):
    lock_was_available = []
    updater = None

    def add(**_kwargs):
        acquired = updater._buffer_lock.acquire(blocking=False)
        lock_was_available.append(acquired)
        if acquired:
            updater._buffer_lock.release()
        return SimpleNamespace(uuid_="episode-1")

    updater = _updater(monkeypatch, add)
    updater.start()
    for index in range(updater.BATCH_SIZE):
        updater.add_activity(_activity(index))
    updater.stop()

    assert lock_was_available == [True]


def test_activity_episode_has_provenance_time_and_a_safe_size(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
        simulation_id="sim-provenance",
    )

    updater._send_batch_activities(
        [_activity(content="x" * 20_000)],
        "twitter",
    )

    assert len(writes) == 1
    write = writes[0]
    assert len(write["data"]) <= updater.MAX_EPISODE_CHARS
    assert write["created_at"] == "2026-07-22T12:00:00+08:00"
    assert write["source_description"] == "MiroFish simulation activity batch"
    assert write["metadata"]["simulation_id"] == "sim-provenance"
    assert write["metadata"]["platform"] == "twitter"
    assert write["metadata"]["activity_count"] == 1


def test_failed_non_idempotent_write_is_reported_by_stop(monkeypatch):
    def add(**_kwargs):
        raise RuntimeError("write failed")

    updater = _updater(monkeypatch, add)
    updater.start()
    updater.add_activity(_activity())

    with pytest.raises(RuntimeError, match="ingestion is incomplete"):
        updater.stop()

    assert updater.get_stats()["failed_count"] == 1


def test_failed_simulation_action_is_not_ingested(monkeypatch):
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="unused"),
    )

    updater.add_activity_from_dict(
        {
            "agent_id": 1,
            "agent_name": "Agent",
            "action_type": "CREATE_POST",
            "action_args": {"content": "not actually posted"},
            "success": False,
        },
        "twitter",
    )

    assert updater.get_stats()["queue_size"] == 0
    assert updater.get_stats()["skipped_count"] == 1


def test_stop_cannot_finish_between_acceptance_check_and_enqueue(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
    )

    put_entered = threading.Event()
    allow_put = threading.Event()

    class BlockingQueue(Queue):
        def put(self, item, block=True, timeout=None):
            put_entered.set()
            assert allow_put.wait(timeout=2)
            return super().put(item, block=block, timeout=timeout)

    updater._activity_queue = BlockingQueue()
    updater.start()
    producer = threading.Thread(target=updater.add_activity, args=(_activity(),))
    producer.start()
    assert put_entered.wait(timeout=1)

    stopper = threading.Thread(target=updater.stop)
    stopper.start()
    stopper.join(timeout=0.1)
    assert stopper.is_alive()

    allow_put.set()
    producer.join(timeout=2)
    stopper.join(timeout=2)

    assert not producer.is_alive()
    assert not stopper.is_alive()
    assert len(writes) == 1


def test_pending_episode_wait_has_a_deadline(monkeypatch):
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-1"]
    updater.client.graph.episode.get = lambda **_kwargs: SimpleNamespace(
        processed=False
    )
    timestamps = iter([0.0, 2.0])
    monkeypatch.setattr(updater_module, "ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(updater_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="pending"):
        updater._wait_for_pending_episodes()


def test_explicit_graph_destruction_can_discard_a_stopped_failed_updater():
    updater = SimpleNamespace(
        graph_id="graph-1",
        _running=False,
        _worker_thread=SimpleNamespace(is_alive=lambda: False),
    )
    ZepGraphMemoryManager._updaters["sim-failed"] = updater
    try:
        assert ZepGraphMemoryManager.discard_inactive_updater("sim-failed") is True
        assert "sim-failed" not in ZepGraphMemoryManager._updaters
    finally:
        ZepGraphMemoryManager._updaters.pop("sim-failed", None)


def test_flush_deadline_keeps_unattempted_platform_for_a_safe_retry(monkeypatch):
    now = [0.0]
    writes = []

    def add(**kwargs):
        writes.append(kwargs)
        now[0] = 2.0
        return SimpleNamespace(uuid_=f"episode-{len(writes)}")

    updater = _updater(monkeypatch, add)
    updater._platform_buffers["twitter"] = [_activity(1)]
    reddit_activity = _activity(2)
    reddit_activity.platform = "reddit"
    updater._platform_buffers["reddit"] = [reddit_activity]
    monkeypatch.setattr(updater_module.time, "time", lambda: now[0])

    with pytest.raises(TimeoutError, match="deadline"):
        updater._flush_remaining(deadline=1.0)

    assert updater._platform_buffers["twitter"] == []
    assert updater._platform_buffers["reddit"] == [reddit_activity]

    now[0] = 0.0
    updater._flush_remaining(deadline=1.0)
    assert updater._platform_buffers["reddit"] == []
    assert len(writes) == 2


# ---------------------------------------------------------------------------
# Episode text language: Chinese for a 'zh' run, English for any other locale
# ---------------------------------------------------------------------------

# (action_type, action_args, English description, Chinese description). The
# Chinese column is the upstream MiroFish text and must never change.
DESCRIPTION_CASES = [
    ("CREATE_POST", {"content": "Hi"}, "posted: “Hi”", "发布了一条帖子：「Hi」"),
    ("CREATE_POST", {}, "posted", "发布了一条帖子"),
    ("LIKE_POST", {"post_author_name": "Bob", "post_content": "Hi"},
     "liked Bob's post: “Hi”", "点赞了Bob的帖子：「Hi」"),
    ("LIKE_POST", {"post_content": "Hi"}, "liked a post: “Hi”", "点赞了一条帖子：「Hi」"),
    ("LIKE_POST", {"post_author_name": "Bob"}, "liked a post by Bob", "点赞了Bob的一条帖子"),
    ("LIKE_POST", {}, "liked a post", "点赞了一条帖子"),
    ("DISLIKE_POST", {"post_author_name": "Bob", "post_content": "Hi"},
     "disliked Bob's post: “Hi”", "踩了Bob的帖子：「Hi」"),
    ("DISLIKE_POST", {"post_content": "Hi"}, "disliked a post: “Hi”", "踩了一条帖子：「Hi」"),
    ("DISLIKE_POST", {"post_author_name": "Bob"}, "disliked a post by Bob", "踩了Bob的一条帖子"),
    ("DISLIKE_POST", {}, "disliked a post", "踩了一条帖子"),
    ("REPOST", {"original_author_name": "Bob", "original_content": "Hi"},
     "reposted Bob's post: “Hi”", "转发了Bob的帖子：「Hi」"),
    ("REPOST", {"original_content": "Hi"}, "reposted a post: “Hi”", "转发了一条帖子：「Hi」"),
    ("REPOST", {"original_author_name": "Bob"}, "reposted a post by Bob", "转发了Bob的一条帖子"),
    ("REPOST", {}, "reposted a post", "转发了一条帖子"),
    ("QUOTE_POST", {"original_author_name": "Bob", "original_content": "Hi", "quote_content": "Yes"},
     "quoted Bob's post “Hi”, adding: “Yes”", "引用了Bob的帖子「Hi」，并评论道：「Yes」"),
    ("QUOTE_POST", {"original_author_name": "Bob", "original_content": "Hi"},
     "quoted Bob's post “Hi”", "引用了Bob的帖子「Hi」"),
    ("QUOTE_POST", {"original_content": "Hi", "quote_content": "Yes"},
     "quoted a post “Hi”, adding: “Yes”", "引用了一条帖子「Hi」，并评论道：「Yes」"),
    ("QUOTE_POST", {"original_author_name": "Bob", "content": "Yes"},
     "quoted a post by Bob, adding: “Yes”", "引用了Bob的一条帖子，并评论道：「Yes」"),
    ("QUOTE_POST", {"quote_content": "Yes"}, "quoted a post, adding: “Yes”", "引用了一条帖子，并评论道：「Yes」"),
    ("QUOTE_POST", {}, "quoted a post", "引用了一条帖子"),
    ("FOLLOW", {"target_user_name": "Bob"}, "followed the user “Bob”", "关注了用户「Bob」"),
    ("FOLLOW", {}, "followed a user", "关注了一个用户"),
    ("CREATE_COMMENT", {"post_author_name": "Bob", "post_content": "Hi", "content": "Nice"},
     "commented on Bob's post “Hi”: “Nice”", "在Bob的帖子「Hi」下评论道：「Nice」"),
    ("CREATE_COMMENT", {"post_content": "Hi", "content": "Nice"},
     "commented on a post “Hi”: “Nice”", "在帖子「Hi」下评论道：「Nice」"),
    ("CREATE_COMMENT", {"post_author_name": "Bob", "content": "Nice"},
     "commented on Bob's post: “Nice”", "在Bob的帖子下评论道：「Nice」"),
    ("CREATE_COMMENT", {"content": "Nice"}, "commented: “Nice”", "评论道：「Nice」"),
    ("CREATE_COMMENT", {"post_author_name": "Bob", "post_content": "Hi"}, "left a comment", "发表了评论"),
    ("LIKE_COMMENT", {"comment_author_name": "Bob", "comment_content": "Hi"},
     "liked Bob's comment: “Hi”", "点赞了Bob的评论：「Hi」"),
    ("LIKE_COMMENT", {"comment_content": "Hi"}, "liked a comment: “Hi”", "点赞了一条评论：「Hi」"),
    ("LIKE_COMMENT", {"comment_author_name": "Bob"}, "liked a comment by Bob", "点赞了Bob的一条评论"),
    ("LIKE_COMMENT", {}, "liked a comment", "点赞了一条评论"),
    ("DISLIKE_COMMENT", {"comment_author_name": "Bob", "comment_content": "Hi"},
     "disliked Bob's comment: “Hi”", "踩了Bob的评论：「Hi」"),
    ("DISLIKE_COMMENT", {"comment_content": "Hi"}, "disliked a comment: “Hi”", "踩了一条评论：「Hi」"),
    ("DISLIKE_COMMENT", {"comment_author_name": "Bob"}, "disliked a comment by Bob", "踩了Bob的一条评论"),
    ("DISLIKE_COMMENT", {}, "disliked a comment", "踩了一条评论"),
    ("SEARCH_POSTS", {"query": "AI"}, "searched for “AI”", "搜索了「AI」"),
    ("SEARCH_POSTS", {"keyword": "AI"}, "searched for “AI”", "搜索了「AI」"),
    ("SEARCH_POSTS", {}, "ran a search", "进行了搜索"),
    ("SEARCH_USER", {"query": "Bob"}, "searched for the user “Bob”", "搜索了用户「Bob」"),
    ("SEARCH_USER", {"username": "Bob"}, "searched for the user “Bob”", "搜索了用户「Bob」"),
    ("SEARCH_USER", {}, "searched for users", "搜索了用户"),
    ("MUTE", {"target_user_name": "Bob"}, "muted the user “Bob”", "屏蔽了用户「Bob」"),
    ("MUTE", {}, "muted a user", "屏蔽了一个用户"),
    ("UNFOLLOW", {"target_user_name": "Bob"}, "performed UNFOLLOW", "执行了UNFOLLOW操作"),
    ("", {}, "performed an action", "执行了操作"),
]
PREFIX = "[2026-07-22T12:00:00+08:00] [reddit round 4] Ann Lee: "


def _described(action_type, args):
    return AgentActivity(
        platform="reddit",
        agent_id=3,
        agent_name="Ann Lee",
        action_type=action_type,
        action_args=args,
        round_num=4,
        timestamp="2026-07-22T12:00:00+08:00",
    )


@pytest.mark.parametrize("action_type,args,english,chinese", DESCRIPTION_CASES)
def test_episode_text_is_english_for_en_and_unchanged_chinese_for_zh(action_type, args, english, chinese):
    activity = _described(action_type, args)
    assert activity.to_episode_text("en") == PREFIX + english
    assert activity.to_episode_text("zh") == PREFIX + chinese
    # This thread has no locale set, so it reads in the English default.
    assert activity.to_episode_text() == PREFIX + english


def test_every_non_chinese_locale_gets_english_and_zh_variants_stay_chinese():
    activity = _described("LIKE_POST", {"post_author_name": "Bob", "post_content": "Hi"})
    for locale in ("en", "fr", "de", "", "EN"):
        assert activity.to_episode_text(locale) == PREFIX + "liked Bob's post: “Hi”"
    for locale in ("zh", "zh-CN", "zh_TW", "ZH"):
        assert activity.to_episode_text(locale) == PREFIX + "点赞了Bob的帖子：「Hi」"


def test_quoted_content_and_names_are_kept_verbatim_in_english():
    content = "Braces {x}, “curly”, 「corner」 and\na second line"
    activity = _described("QUOTE_POST", {
        "original_author_name": "Dr. J.-P. O'Brien", "original_content": content, "quote_content": "{0} ok",
    })
    assert activity.to_episode_text("en") == (
        PREFIX + f"quoted Dr. J.-P. O'Brien's post “{content}”, adding: “{{0}} ok”"
    )


def test_episode_text_defaults_to_the_rendering_threads_locale():
    activity = _described("FOLLOW", {"target_user_name": "Bob"})
    rendered = {}

    def render(locale):
        set_locale(locale)
        rendered[locale] = activity.to_episode_text()

    for locale in ("en", "zh"):
        worker = threading.Thread(target=render, args=(locale,))
        worker.start()
        worker.join()
    assert rendered == {
        "en": PREFIX + "followed the user “Bob”",
        "zh": PREFIX + "关注了用户「Bob」",
    }


def _recording_updater(monkeypatch, writes, **kwargs):
    def add(**payload):
        writes.append({
            **payload,
            "thread": threading.current_thread().name,
            "thread_locale": get_locale(),
        })
        return SimpleNamespace(uuid_=f"episode-{len(writes)}")

    client = _client(add)
    monkeypatch.setattr(updater_module, "get_zep_client", lambda _key: client)
    updater = ZepGraphMemoryUpdater("graph-1", api_key="test-key", simulation_id="sim-1", **kwargs)
    updater.SEND_INTERVAL = 0
    return updater


def _record_in(monkeypatch, language):
    asked = []

    def record_language(**ids):
        asked.append(ids)
        return language

    monkeypatch.setattr(updater_module, "record_language", record_language)
    return asked


def test_updater_writes_every_line_in_the_record_language(monkeypatch):
    writes = []
    asked = _record_in(monkeypatch, "en")
    # The run starts from a Chinese request; the gathering's record language decides.
    with Flask(__name__).test_request_context(headers={"Accept-Language": "zh-CN"}):
        updater = _recording_updater(monkeypatch, writes)
    assert updater.locale == "en"
    assert asked == [{"simulation_id": "sim-1"}]

    updater.start()
    # One full batch goes out from the worker; the tail is flushed by stop()
    # on this thread, whose own locale is Chinese.
    for index in range(updater.BATCH_SIZE + 2):
        updater.add_activity(_activity(index))
    set_locale("zh")
    updater.stop()

    lines = [line for write in writes for line in write["data"].splitlines()]
    assert len(lines) == updater.BATCH_SIZE + 2
    assert all(line.endswith(": posted: “hello”") for line in lines)
    tail = [write for write in writes if write["thread"] == threading.current_thread().name]
    assert tail and all(write["thread_locale"] == "zh" for write in tail)
    assert all("posted: “hello”" in write["data"] for write in tail)
    # The local memory is told the record language, so its facts are written in it.
    assert {write["metadata"]["language"] for write in writes} == {"en"}


def test_updater_in_a_chinese_gathering_keeps_the_upstream_text(monkeypatch):
    writes = []
    _record_in(monkeypatch, "zh")
    with Flask(__name__).test_request_context(headers={"Accept-Language": "en"}):
        updater = _recording_updater(monkeypatch, writes)
    assert updater.locale == "zh"
    updater.start()
    updater.add_activity(_activity(1))
    updater.stop()
    assert writes[0]["data"] == (
        "[2026-07-22T12:00:00+08:00] [twitter round 1] Agent 1: 发布了一条帖子：「hello」"
    )
    assert writes[0]["metadata"]["language"] == "zh"


def test_an_unknown_gathering_writes_english_never_the_threads_chinese(monkeypatch):
    monkeypatch.delenv("PARTHENON_RECORD_LANGUAGE", raising=False)
    set_locale("zh")
    writes = []
    updater = _recording_updater(monkeypatch, writes)  # sim-1 has no record on disk
    assert updater.locale == "en"
    assert ZepGraphMemoryUpdater._worker_loop.__defaults__ == (None,)


def test_the_manager_passes_the_record_language_to_the_updater(monkeypatch):
    created = []

    class Recording:
        def __init__(self, graph_id, **kwargs):
            created.append((graph_id, kwargs))

        def start(self):
            pass

    monkeypatch.setattr(updater_module, "ZepGraphMemoryUpdater", Recording)
    try:
        ZepGraphMemoryManager.create_updater("sim-lang", "graph-1", locale="zh")
        assert created == [("graph-1", {"simulation_id": "sim-lang", "locale": "zh", "accounts": None})]
    finally:
        ZepGraphMemoryManager._updaters.pop("sim-lang", None)


def test_an_explicit_updater_locale_wins_over_the_creating_thread(monkeypatch):
    writes = []
    with Flask(__name__).test_request_context(headers={"Accept-Language": "en"}):
        updater = _recording_updater(monkeypatch, writes, locale="zh")
    assert updater.locale == "zh"
    updater._send_batch_activities([_activity(1)], "twitter")
    assert writes[0]["data"].endswith("Agent 1: 发布了一条帖子：「hello」")


def test_the_local_memory_is_told_each_accounts_graph_node(monkeypatch):
    """An English record may name 苏格拉底 "Socrates": the episode says which node he is."""

    writes = []
    client = _client(lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"))
    monkeypatch.setattr(updater_module, "get_zep_client", lambda _key: client)
    accounts = updater_module.account_nodes({"agent_configs": [
        {"agent_id": 1, "entity_name": "Agent 1", "entity_uuid": "node-1"},
        {"agent_id": 2, "entity_name": "Agent 2", "entity_uuid": "node-2"},
        {"agent_id": 3, "entity_name": "Agent 3", "entity_uuid": ""},
        "not an agent",
    ]})
    assert accounts == {"Agent 1": "node-1", "Agent 2": "node-2"}
    assert updater_module.account_nodes(None) == {} and updater_module.account_nodes({"agent_configs": 3}) == {}

    monkeypatch.setattr(updater_module.Config, "MEMORY_BACKEND", "local")
    local = ZepGraphMemoryUpdater("graph-1", simulation_id="sim-1", locale="en", accounts=accounts)
    local._send_batch_activities([_activity(1)], "twitter")
    # Only the accounts the episode names, as a string (metadata values are scalars).
    assert json.loads(writes[0]["metadata"]["accounts"]) == {"Agent 1": "node-1"}

    # Zep Cloud extracts its own nodes: its episodes carry no accounts.
    monkeypatch.setattr(updater_module.Config, "MEMORY_BACKEND", "zep")
    cloud = ZepGraphMemoryUpdater("graph-1", api_key="test-key", simulation_id="sim-1", locale="en",
                                  accounts=accounts)
    cloud._send_batch_activities([_activity(1)], "twitter")
    assert "accounts" not in writes[1]["metadata"]
