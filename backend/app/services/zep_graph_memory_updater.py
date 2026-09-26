"""
Zep图谱记忆更新服务
将模拟中的Agent活动动态更新到Zep图谱中
"""

import time
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale
from ..utils.zep import (
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
    call_zep_read_with_retry,
    client_ingestion_timeout,
    get_zep_client,
)

logger = get_logger('mirofish.zep_graph_memory_updater')


# Activity description templates per language, filled with str.format (braces
# inside the filled-in values are safe). The Chinese set is the upstream
# MiroFish text and must stay byte-for-byte stable; every other locale gets the
# English set. The local memory's rules extractor (app/memory/activity.py)
# parses both sets, so a template change must be mirrored there.
#
# Four-template tuples cover, in order: author and content, content only,
# author only, neither. Two-template tuples: with the value, without it.
_DESCRIPTION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "zh": {
        "post": ("发布了一条帖子：「{content}」", "发布了一条帖子"),
        "like_post": ("点赞了{author}的帖子：「{content}」", "点赞了一条帖子：「{content}」",
                      "点赞了{author}的一条帖子", "点赞了一条帖子"),
        "dislike_post": ("踩了{author}的帖子：「{content}」", "踩了一条帖子：「{content}」",
                         "踩了{author}的一条帖子", "踩了一条帖子"),
        "repost": ("转发了{author}的帖子：「{content}」", "转发了一条帖子：「{content}」",
                   "转发了{author}的一条帖子", "转发了一条帖子"),
        "quote": ("引用了{author}的帖子「{content}」", "引用了一条帖子「{content}」",
                  "引用了{author}的一条帖子", "引用了一条帖子"),
        "quote_suffix": "，并评论道：「{quote}」",
        "follow": ("关注了用户「{name}」", "关注了一个用户"),
        # Keyed by the commented post: {post} is its content, {content} the comment.
        "comment": ("在{author}的帖子「{post}」下评论道：「{content}」", "在帖子「{post}」下评论道：「{content}」",
                    "在{author}的帖子下评论道：「{content}」", "评论道：「{content}」"),
        "comment_empty": "发表了评论",
        "like_comment": ("点赞了{author}的评论：「{content}」", "点赞了一条评论：「{content}」",
                         "点赞了{author}的一条评论", "点赞了一条评论"),
        "dislike_comment": ("踩了{author}的评论：「{content}」", "踩了一条评论：「{content}」",
                            "踩了{author}的一条评论", "踩了一条评论"),
        "search": ("搜索了「{query}」", "进行了搜索"),
        "search_user": ("搜索了用户「{query}」", "搜索了用户"),
        "mute": ("屏蔽了用户「{name}」", "屏蔽了一个用户"),
        "generic": ("执行了{action}操作", "执行了操作"),
    },
    "en": {
        "post": ("posted: “{content}”", "posted"),
        "like_post": ("liked {author}'s post: “{content}”", "liked a post: “{content}”",
                      "liked a post by {author}", "liked a post"),
        "dislike_post": ("disliked {author}'s post: “{content}”", "disliked a post: “{content}”",
                         "disliked a post by {author}", "disliked a post"),
        "repost": ("reposted {author}'s post: “{content}”", "reposted a post: “{content}”",
                   "reposted a post by {author}", "reposted a post"),
        "quote": ("quoted {author}'s post “{content}”", "quoted a post “{content}”",
                  "quoted a post by {author}", "quoted a post"),
        "quote_suffix": ", adding: “{quote}”",
        "follow": ("followed the user “{name}”", "followed a user"),
        "comment": ("commented on {author}'s post “{post}”: “{content}”",
                    "commented on a post “{post}”: “{content}”",
                    "commented on {author}'s post: “{content}”", "commented: “{content}”"),
        "comment_empty": "left a comment",
        "like_comment": ("liked {author}'s comment: “{content}”", "liked a comment: “{content}”",
                         "liked a comment by {author}", "liked a comment"),
        "dislike_comment": ("disliked {author}'s comment: “{content}”",
                            "disliked a comment: “{content}”",
                            "disliked a comment by {author}", "disliked a comment"),
        "search": ("searched for “{query}”", "ran a search"),
        "search_user": ("searched for the user “{query}”", "searched for users"),
        "mute": ("muted the user “{name}”", "muted a user"),
        "generic": ("performed {action}", "performed an action"),
    },
}


def _description_templates(locale: Optional[str]) -> Dict[str, Any]:
    """Chinese templates for a Chinese locale ('zh', 'zh-CN', ...), English otherwise."""
    code = str(locale or "").strip().lower().replace("_", "-")
    return _DESCRIPTION_TEMPLATES["zh" if code == "zh" or code.startswith("zh-") else "en"]


def _shape(author: Any, content: Any) -> int:
    """Index into a four-template tuple: author and content, content, author, neither."""
    if content and author:
        return 0
    if content:
        return 1
    if author:
        return 2
    return 3


@dataclass
class AgentActivity:
    """Agent活动记录"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str
    
    def to_episode_text(self, locale: Optional[str] = None) -> str:
        """
        Render the activity as one episode line for the graph.

        ``locale`` picks the description language: Chinese for 'zh' (and
        'zh-*' variants), English for anything else. When it is None the
        calling thread's locale (get_locale()) is used. ZepGraphMemoryUpdater
        always passes the locale of the run, because a tail flush can run on
        another thread. Quoted content and names are kept verbatim in both
        languages.
        """
        # 根据不同的动作类型生成不同的描述
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }
        
        templates = _description_templates(get_locale() if locale is None else locale)
        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func(templates)
        
        # Keep the event time in the source text as well as episode metadata so
        # temporal extraction does not collapse a multi-action batch.
        return (
            f"[{self.timestamp}] [{self.platform} round {self.round_num}] "
            f"{self.agent_name}: {description}"
        )
    
    def _describe_create_post(self, templates: Dict[str, Any]) -> str:
        content = self.action_args.get("content", "")
        with_content, bare = templates["post"]
        return with_content.format(content=content) if content else bare
    
    def _describe_like_post(self, templates: Dict[str, Any]) -> str:
        """点赞帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        template = templates["like_post"][_shape(post_author, post_content)]
        return template.format(author=post_author, content=post_content)
    
    def _describe_dislike_post(self, templates: Dict[str, Any]) -> str:
        """踩帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        template = templates["dislike_post"][_shape(post_author, post_content)]
        return template.format(author=post_author, content=post_content)
    
    def _describe_repost(self, templates: Dict[str, Any]) -> str:
        """转发帖子 - 包含原帖内容和作者信息"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        template = templates["repost"][_shape(original_author, original_content)]
        return template.format(author=original_author, content=original_content)
    
    def _describe_quote_post(self, templates: Dict[str, Any]) -> str:
        """引用帖子 - 包含原帖内容、作者信息和引用评论"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        
        template = templates["quote"][_shape(original_author, original_content)]
        base = template.format(author=original_author, content=original_content)
        if quote_content:
            base += templates["quote_suffix"].format(quote=quote_content)
        return base
    
    def _describe_follow(self, templates: Dict[str, Any]) -> str:
        """关注用户 - 包含被关注用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        with_name, bare = templates["follow"]
        return with_name.format(name=target_user_name) if target_user_name else bare
    
    def _describe_create_comment(self, templates: Dict[str, Any]) -> str:
        """发表评论 - 包含评论内容和所评论的帖子信息"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if not content:
            return templates["comment_empty"]
        template = templates["comment"][_shape(post_author, post_content)]
        return template.format(author=post_author, post=post_content, content=content)
    
    def _describe_like_comment(self, templates: Dict[str, Any]) -> str:
        """点赞评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        template = templates["like_comment"][_shape(comment_author, comment_content)]
        return template.format(author=comment_author, content=comment_content)
    
    def _describe_dislike_comment(self, templates: Dict[str, Any]) -> str:
        """踩评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        template = templates["dislike_comment"][_shape(comment_author, comment_content)]
        return template.format(author=comment_author, content=comment_content)
    
    def _describe_search(self, templates: Dict[str, Any]) -> str:
        """搜索帖子 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        with_query, bare = templates["search"]
        return with_query.format(query=query) if query else bare
    
    def _describe_search_user(self, templates: Dict[str, Any]) -> str:
        """搜索用户 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        with_query, bare = templates["search_user"]
        return with_query.format(query=query) if query else bare
    
    def _describe_mute(self, templates: Dict[str, Any]) -> str:
        """屏蔽用户 - 包含被屏蔽用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        with_name, bare = templates["mute"]
        return with_name.format(name=target_user_name) if target_user_name else bare
    
    def _describe_generic(self, templates: Dict[str, Any]) -> str:
        # 对于未知的动作类型，生成通用描述
        with_action, bare = templates["generic"]
        # Only an empty type has no name to show; any other value (even None)
        # is rendered as before.
        if self.action_type == "":
            return bare
        return with_action.format(action=self.action_type)


class _DrainDeadlineExceeded(TimeoutError):
    def __init__(self, processed_count: int):
        super().__init__("Zep updater drain deadline elapsed")
        self.processed_count = processed_count


class ZepGraphMemoryUpdater:
    """
    Zep图谱记忆更新器
    
    监控模拟的actions日志文件，将新的agent活动实时更新到Zep图谱中。
    按平台分组，每累积BATCH_SIZE条活动后批量发送到Zep。
    
    所有有意义的行为都会被更新到Zep，action_args中会包含完整的上下文信息：
    - 点赞/踩的帖子原文
    - 转发/引用的帖子原文
    - 关注/屏蔽的用户名
    - 点赞/踩的评论原文
    """
    
    # 批量发送大小（每个平台累积多少条后发送）
    BATCH_SIZE = 5
    
    # 平台名称映射（用于控制台显示）
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '世界1',
        'reddit': '世界2',
    }
    
    # 发送间隔（秒），避免请求过快
    SEND_INTERVAL = 0.5
    
    # Zep recommends keeping an episode below 10,000 characters. Leave room
    # for future source formatting changes.
    MAX_EPISODE_CHARS = 9_500
    
    def __init__(
        self,
        graph_id: str,
        api_key: Optional[str] = None,
        simulation_id: Optional[str] = None,
        locale: Optional[str] = None,
    ):
        """
        初始化更新器

        Args:
            graph_id: Zep图谱ID
            api_key: Zep API Key（可选，默认从配置读取）
            simulation_id: the simulation whose activity this updater sends
            locale: language of the episode text ('zh' keeps the Chinese
                templates, anything else is English). Defaults to the
                creating thread's locale, i.e. the request that starts the run.
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id or "unknown"
        # Captured once so every line of this run uses the run's language:
        # the worker thread sends full batches, but stop() flushes the tail on
        # whichever thread calls it (monitor, stop request, shutdown).
        self.locale = locale or get_locale()
        self.api_key = api_key or Config.ZEP_API_KEY
        
        if not self.api_key and Config.memory_backend(self.api_key) == "zep":
            raise ValueError("ZEP_API_KEY未配置")
        
        self.client = get_zep_client(self.api_key)
        
        # 活动队列
        self._activity_queue: Queue = Queue()
        
        # 按平台分组的活动缓冲区（每个平台各自累积到BATCH_SIZE后批量发送）
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()
        self._acceptance_lock = threading.Lock()
        
        # 控制标志
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # 统计
        self._total_activities = 0  # 实际添加到队列的活动数
        self._total_sent = 0        # 成功发送到Zep的批次数
        self._total_items_sent = 0  # 成功发送到Zep的活动条数
        self._failed_count = 0      # 发送失败的批次数
        self._skipped_count = 0     # 被过滤跳过的活动数（DO_NOTHING）
        self._failed_batches: List[Dict[str, Any]] = []
        self._pending_episode_uuids: List[str] = []
        
        logger.info(f"ZepGraphMemoryUpdater 初始化完成: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")
    
    def _get_platform_display_name(self, platform: str) -> str:
        """获取平台的显示名称"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)
    
    def start(self):
        """启动后台工作线程"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(self.locale,),
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater 已启动: graph_id={self.graph_id}")
    
    def stop(self):
        """Drain the worker, flush tail events, and wait for Cloud ingestion."""
        deadline = time.time() + client_ingestion_timeout(self.client, ZEP_INGESTION_WAIT_TIMEOUT_SECONDS)
        # Serialize the accepting->closed transition with add_activity's
        # check+enqueue operation. This closes the small race where a producer
        # could enqueue after both the worker and final flush had exited.
        with self._acceptance_lock:
            self._running = False

        if self._worker_thread and self._worker_thread.is_alive():
            join_timeout = max(0.0, deadline - time.time())
            self._worker_thread.join(timeout=join_timeout)
            if self._worker_thread.is_alive():
                raise TimeoutError(
                    f"Zep updater worker did not stop within {join_timeout:.0f}s"
                )

        # The worker has drained the queue. Only now is it safe to flush
        # buffers; doing this before join loses an item already dequeued by the
        # worker but not yet buffered.
        self._flush_remaining(deadline=deadline)

        if self._failed_batches:
            raise RuntimeError(
                f"{len(self._failed_batches)} Zep activity batch(es) failed; "
                "simulation graph ingestion is incomplete"
            )

        self._wait_for_pending_episodes(deadline=deadline)
        
        logger.info(f"ZepGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")
    
    def add_activity(self, activity: AgentActivity):
        """
        添加一个agent活动到队列
        
        所有有意义的行为都会被添加到队列，包括：
        - CREATE_POST（发帖）
        - CREATE_COMMENT（评论）
        - QUOTE_POST（引用帖子）
        - SEARCH_POSTS（搜索帖子）
        - SEARCH_USER（搜索用户）
        - LIKE_POST/DISLIKE_POST（点赞/踩帖子）
        - REPOST（转发）
        - FOLLOW（关注）
        - MUTE（屏蔽）
        - LIKE_COMMENT/DISLIKE_COMMENT（点赞/踩评论）
        
        action_args中会包含完整的上下文信息（如帖子原文、用户名等）。
        
        Args:
            activity: Agent活动记录
        """
        # 跳过DO_NOTHING类型的活动
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        with self._acceptance_lock:
            if not self._running:
                raise RuntimeError("Zep graph updater is not running")
            self._activity_queue.put(activity)
            self._total_activities += 1
        logger.debug(f"添加活动到Zep队列: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        从字典数据添加活动
        
        Args:
            data: 从actions.jsonl解析的字典数据
            platform: 平台名称 (twitter/reddit)
        """
        # 跳过事件类型的条目
        if "event_type" in data:
            return
        if data.get("success") is False:
            self._skipped_count += 1
            return
        
        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        
        self.add_activity(activity)
    
    def _worker_loop(self, locale: str = 'zh'):
        """后台工作循环 - 按平台批量发送活动到Zep"""
        set_locale(locale)
        while self._running or not self._activity_queue.empty():
            try:
                # 尝试从队列获取活动（超时1秒）
                try:
                    activity = self._activity_queue.get(timeout=1)
                    
                    # 将活动添加到对应平台的缓冲区
                    platform = activity.platform.lower()
                    batch = None
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        
                        # 检查该平台是否达到批量大小
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]

                    # Never hold the buffer lock across network I/O or sleep.
                    if batch:
                        self._send_batch_activities(batch, platform)
                        time.sleep(self.SEND_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)
    
    def _build_episode_payloads(
        self,
        activities: List[AgentActivity],
    ) -> List[tuple[List[AgentActivity], str]]:
        payloads: List[tuple[List[AgentActivity], str]] = []
        current_activities: List[AgentActivity] = []
        current_lines: List[str] = []
        current_length = 0

        for activity in activities:
            text = activity.to_episode_text(self.locale)
            if len(text) > self.MAX_EPISODE_CHARS:
                marker = "... [truncated by MiroFish]"
                text = text[: self.MAX_EPISODE_CHARS - len(marker)] + marker
            projected_length = current_length + (1 if current_lines else 0) + len(text)
            if current_lines and projected_length > self.MAX_EPISODE_CHARS:
                payloads.append((current_activities, "\n".join(current_lines)))
                current_activities = []
                current_lines = []
                current_length = 0
            current_activities.append(activity)
            current_lines.append(text)
            current_length += (1 if len(current_lines) > 1 else 0) + len(text)

        if current_lines:
            payloads.append((current_activities, "\n".join(current_lines)))
        return payloads

    def _send_batch_activities(
        self,
        activities: List[AgentActivity],
        platform: str,
        *,
        deadline: float | None = None,
    ) -> int:
        """
        批量发送活动到Zep图谱（合并为一条文本）
        
        Args:
            activities: Agent活动列表
            platform: 平台名称
        """
        if not activities:
            return 0

        processed_count = 0
        for payload_activities, combined_text in self._build_episode_payloads(activities):
            if deadline is not None and time.time() >= deadline:
                raise _DrainDeadlineExceeded(processed_count)
            try:
                episode = self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text,
                    created_at=self._to_rfc3339(payload_activities[-1].timestamp),
                    source_description="MiroFish simulation activity batch",
                    metadata={
                        "source": "mirofish_simulation",
                        "simulation_id": self.simulation_id,
                        "platform": platform,
                        "activity_count": len(payload_activities),
                        "first_round": min(a.round_num for a in payload_activities),
                        "last_round": max(a.round_num for a in payload_activities),
                        "agent_ids": ",".join(
                            str(value)
                            for value in sorted({a.agent_id for a in payload_activities})
                        ),
                        "action_types": ",".join(
                            value
                            for value in sorted({a.action_type for a in payload_activities})
                            if value
                        ) or "unknown",
                    },
                )

                episode_uuid = (
                    getattr(episode, "uuid_", None)
                    or getattr(episode, "uuid", None)
                )
                if not episode_uuid:
                    raise RuntimeError("Zep graph.add returned no episode UUID")
                self._pending_episode_uuids.append(str(episode_uuid))
                self._total_sent += 1
                self._total_items_sent += len(payload_activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"成功批量发送 {len(payload_activities)} 条{display_name}活动到图谱 {self.graph_id}")
                logger.debug(f"批量内容预览: {combined_text[:200]}...")

            except Exception as e:
                # graph.add has no idempotency key. Replaying an ambiguous
                # response can duplicate extracted facts, so fail closed and
                # surface the incomplete batch to SimulationRunner.
                logger.error(f"批量发送到Zep失败，未自动重放非幂等写入: {e}")
                self._failed_count += 1
                self._failed_batches.append({
                    "platform": platform,
                    "activities": payload_activities,
                    "error": str(e),
                })
            finally:
                # Successes have a confirmed episode UUID; failures are kept
                # durably in _failed_batches and must never be replayed. Either
                # way this payload is accounted for before moving on.
                processed_count += len(payload_activities)
        return processed_count

    @staticmethod
    def _to_rfc3339(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return parsed.isoformat()
        except (AttributeError, TypeError, ValueError):
            return datetime.now().astimezone().isoformat()

    def _flush_remaining(self, *, deadline: float | None = None):
        """发送队列和缓冲区中剩余的活动"""
        # 首先处理队列中剩余的活动，添加到缓冲区
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break
        
        for platform in list(self._platform_buffers):
            with self._buffer_lock:
                buffer = list(self._platform_buffers.get(platform, []))
            if not buffer:
                continue
            display_name = self._get_platform_display_name(platform)
            logger.info(f"发送{display_name}平台剩余的 {len(buffer)} 条活动")
            if deadline is not None and time.time() >= deadline:
                raise TimeoutError(
                    "Zep updater drain deadline elapsed before flushing all activities"
                )
            try:
                processed_count = self._send_batch_activities(
                    buffer,
                    platform,
                    deadline=deadline,
                )
            except _DrainDeadlineExceeded as error:
                with self._buffer_lock:
                    del self._platform_buffers[platform][:error.processed_count]
                raise TimeoutError(str(error)) from error
            else:
                with self._buffer_lock:
                    del self._platform_buffers[platform][:processed_count]

    def _wait_for_pending_episodes(self, *, deadline: float | None = None) -> None:
        pending = set(self._pending_episode_uuids)
        if not pending:
            return

        if deadline is None:
            deadline = time.time() + client_ingestion_timeout(self.client, ZEP_INGESTION_WAIT_TIMEOUT_SECONDS)
        while pending:
            if time.time() >= deadline:
                raise TimeoutError(
                    f"Zep simulation ingestion timed out with {len(pending)} "
                    "episode(s) pending"
                )
            for episode_uuid in list(pending):
                episode = call_zep_read_with_retry(
                    lambda: self.client.graph.episode.get(uuid_=episode_uuid),
                    operation_name=f"poll simulation episode {episode_uuid}",
                )
                if getattr(episode, "processed", False):
                    pending.remove(episode_uuid)
            if pending:
                time.sleep(3)
        self._pending_episode_uuids = []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # 添加到队列的活动总数
            "batches_sent": self._total_sent,            # 成功发送的批次数
            "items_sent": self._total_items_sent,        # 成功发送的活动条数
            "failed_count": self._failed_count,          # 发送失败的批次数
            "pending_episode_count": len(self._pending_episode_uuids),
            "skipped_count": self._skipped_count,        # 被过滤跳过的活动数（DO_NOTHING）
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # 各平台缓冲区大小
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    管理多个模拟的Zep图谱记忆更新器
    
    每个模拟可以有自己的更新器实例
    """
    
    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """
        为模拟创建图谱记忆更新器
        
        Args:
            simulation_id: 模拟ID
            graph_id: Zep图谱ID
            
        Returns:
            ZepGraphMemoryUpdater实例
        """
        with cls._lock:
            # 如果已存在，先停止旧的
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            
            updater = ZepGraphMemoryUpdater(
                graph_id,
                simulation_id=simulation_id,
            )
            updater.start()
            cls._updaters[simulation_id] = updater
            cls._stop_all_done = False
            
            logger.info(f"创建图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """获取模拟的更新器"""
        with cls._lock:
            return cls._updaters.get(simulation_id)

    @classmethod
    def get_simulation_ids_for_graph(cls, graph_id: str) -> List[str]:
        """Return simulations whose updater still owns or drains this graph."""

        with cls._lock:
            return sorted(
                simulation_id
                for simulation_id, updater in cls._updaters.items()
                if updater.graph_id == graph_id
            )

    @classmethod
    def get_simulation_ids(cls) -> List[str]:
        """Return every simulation with a retained updater."""

        with cls._lock:
            return sorted(cls._updaters)

    @classmethod
    def discard_inactive_updater(cls, simulation_id: str) -> bool:
        """Discard a failed, fully stopped updater during graph destruction."""

        with cls._lock:
            updater = cls._updaters.get(simulation_id)
            if updater is None:
                return False
            worker_alive = bool(
                updater._worker_thread and updater._worker_thread.is_alive()
            )
            if updater._running or worker_alive:
                raise RuntimeError(
                    f"Zep updater for {simulation_id} is still active"
                )
            cls._updaters.pop(simulation_id, None)
        logger.warning(
            "Discarded incomplete Zep updater during explicit graph deletion: "
            "simulation_id=%s, graph_id=%s",
            simulation_id,
            updater.graph_id,
        )
        return True
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """停止并移除模拟的更新器"""
        with cls._lock:
            updater = cls._updaters.get(simulation_id)
        if updater is None:
            return

        # Do not hold the manager lock through up to several minutes of Cloud
        # polling. Crucially, only remove the updater after a successful drain;
        # on failure it remains visible to report/deletion barriers and can be
        # stopped again.
        updater.stop()
        with cls._lock:
            if cls._updaters.get(simulation_id) is updater:
                cls._updaters.pop(simulation_id, None)
        logger.info(f"已停止图谱记忆更新器: simulation_id={simulation_id}")
    
    # 防止 stop_all 重复调用的标志
    _stop_all_done = False
    
    @classmethod
    def stop_all(cls):
        """停止所有更新器"""
        # 防止重复调用
        if cls._stop_all_done:
            return

        with cls._lock:
            simulation_ids = list(cls._updaters)

        errors = []
        for simulation_id in simulation_ids:
            try:
                cls.stop_updater(simulation_id)
            except Exception as error:
                # Keep a failed updater registered so the caller can retry and
                # lifecycle/report guards still see the incomplete ingestion.
                logger.error(
                    "停止更新器失败: simulation_id=%s, error=%s",
                    simulation_id,
                    error,
                )
                errors.append((simulation_id, error))

        with cls._lock:
            cls._stop_all_done = not cls._updaters

        if errors:
            details = "; ".join(
                f"{simulation_id}: {error}"
                for simulation_id, error in errors
            )
            raise RuntimeError(f"部分图谱更新器未完整停止: {details}")
        logger.info("已停止所有图谱记忆更新器")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有更新器的统计信息"""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
