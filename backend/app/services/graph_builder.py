"""
图谱构建服务
接口2：使用Zep API构建Standalone Graph
"""

import hashlib
import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from zep_cloud import BatchAddItem, EntityEdgeSourceTarget, NotFoundError

from ..config import Config
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.ontology import (
    MAX_ONTOLOGY_TYPES,
    RESERVED_ONTOLOGY_ATTRIBUTE_NAMES,
    normalize_ontology_attributes,
    normalize_ontology_source_targets,
)
from ..utils.zep import (
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
    call_zep_read_with_retry,
    client_ingestion_timeout,
    get_zep_client,
    is_retryable_zep_error,
)
from .language_guard import configured_record_language, record_language
from .text_processor import TextProcessor
from ..utils.locale import t, get_locale, normalize_lang, set_locale
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph_builder')

BATCH_POLL_INTERVAL_SECONDS = 3
BATCH_TERMINAL_STATES = frozenset({"succeeded", "partial", "failed", "invalid", "canceled"})
# The local backend's worker drains one FIFO queue across all graphs with a
# small LLM concurrency, so a build's total wait grows with its own size and
# with the work queued ahead of it. Local waits therefore time out only when
# nothing moves for the client's ingestion timeout; this cap is a backstop
# against a wait that never converges, never a budget for normal progress.
LOCAL_BATCH_WAIT_MIN_HARD_CAP_SECONDS = 6 * 60 * 60
# Per outstanding item (default chunk: 500 chars). The slowest documented
# local rate (spec §4.10) is about 6 s per such chunk, so 30 s leaves ample room.
LOCAL_BATCH_WAIT_SECONDS_PER_ITEM = 30
_LOCAL_ACTIVE_BATCH_STATUSES = ("queued", "processing")


class BatchWaitTimeoutError(TimeoutError):
    """``_wait_for_batch`` stopped waiting before the batch reached a terminal state.

    Giving up does not cancel the batch. ``resumable`` is true when the local
    backend last reported it ``queued`` or ``processing``: its durable queue
    keeps extracting, so a caller can keep the persisted batch identity and
    wait again (the ``graph.py`` resume path) instead of deleting the graph.
    """

    def __init__(
        self,
        message: str,
        *,
        batch_id: str,
        status: Optional[str],
        resumable: bool,
    ) -> None:
        super().__init__(message)
        self.batch_id = batch_id
        self.status = status
        self.resumable = resumable


def _batch_progress_marks(progress: Any) -> tuple[int, int]:
    """``(finished, started)`` item counts of a ``BatchProgress``.

    ``started`` also counts in-flight items, so a claimed window registers as
    movement before its extraction commits.
    """

    def count(name: str) -> int:
        return int(getattr(progress, name, 0) or 0)

    finished = (
        count("succeeded_items")
        + count("failed_items")
        + count("skipped_items")
        + count("canceled_items")
    )
    return finished, finished + count("processing_items")


class _LocalQueueProgress:
    """Detects forward movement of the local ingestion queue between polls.

    Only increases of per-batch high-water marks count, plus batches leaving
    the active set (they reached a terminal state). Lease recovery can move
    items from ``processing`` back to ``queued``; that is not progress, so it
    neither resets the idle timer nor hides a stall. A newly queued batch
    starts at zero and does not count until the worker claims it.
    """

    def __init__(self) -> None:
        self._marks: Dict[str, tuple[int, int]] = {}
        self._active_others: Optional[frozenset[str]] = None

    def observe(self, batch_id: str, progress: Any) -> bool:
        finished, started = _batch_progress_marks(progress)
        old_finished, old_started = self._marks.get(batch_id, (0, 0))
        if finished <= old_finished and started <= old_started:
            return False
        self._marks[batch_id] = (max(finished, old_finished), max(started, old_started))
        return True

    def observe_others(self, summaries: Dict[str, Any]) -> bool:
        advanced = False
        for batch_id, summary in summaries.items():
            if self.observe(batch_id, getattr(summary, "progress", None)):
                advanced = True
        current = frozenset(summaries)
        if self._active_others is not None and self._active_others - current:
            advanced = True
        for batch_id in (self._active_others or frozenset()) - current:
            self._marks.pop(batch_id, None)
        self._active_others = current
        return advanced


def graph_record_language(
    graph_id: Optional[str],
    *,
    project_id: Optional[str] = None,
) -> Optional[str]:
    """The record language ('en' or 'zh') of the gathering a graph is built for, or None.

    PARTHENON_RECORD_LANGUAGE when it names one. Otherwise record_language()
    of the project given, else of the project that references the graph
    (graph.py saves project.graph_id before it sends the scroll). A graph no
    project claims, or one shared by projects that disagree, gives None: its
    memory is then written in the language of the text, as before. Never raises.
    """

    configured = configured_record_language()
    if configured:
        return configured
    if project_id:
        return record_language(project_id=project_id)
    if not graph_id:
        return None
    try:
        # Listing projects makes their folder when it is missing: only look when it is there.
        if not os.path.isdir(ProjectManager.PROJECTS_DIR):
            return None
        projects = ProjectManager.find_projects_by_graph_id(graph_id)
    except Exception as error:  # noqa: BLE001 - an unreadable shelf reads as unknown
        logger.warning(
            "Could not find the project of graph %s: %s", graph_id, type(error).__name__
        )
        return None
    languages = {record_language(project_id=project.project_id) for project in projects}
    return languages.pop() if len(languages) == 1 else None


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


@dataclass(frozen=True)
class BatchSubmission:
    """Durable identity for one Zep Batch API ingestion operation."""

    batch_id: str
    operation_id: str
    episode_uuids: List[str]
    item_count: int


class GraphBuilderService:
    """
    图谱构建服务
    负责调用Zep API构建知识图谱
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key and Config.memory_backend(self.api_key) == "zep":
            raise ValueError(t('api.zepApiKeyMissing'))
        
        self.client = get_zep_client(self.api_key)
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 350,
        *,
        project_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        """
        异步构建图谱
        
        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量
            project_id: the gathering the graph is built for (its record language)
            language: the record language, when the caller already knows it
            
        Returns:
            任务ID
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # Capture locale before spawning background thread
        current_locale = get_locale()

        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size, current_locale),
            kwargs={"project_id": project_id, "language": language},
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        locale: str = 'en',
        *,
        project_id: Optional[str] = None,
        language: Optional[str] = None,
    ):
        """图谱构建工作线程

        ``locale`` is the watcher's (the progress lines); the memory itself is
        written in the gathering's record language (``language``, else found
        from ``project_id`` or the graph, see add_text_batches).
        """
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )
            
            # Validate the complete ingestion payload before the first Cloud
            # mutation, including this legacy service entry point.
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            self.validate_batch_chunks(chunks, batch_size=batch_size)
            total_chunks = len(chunks)

            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )
            
            # 2. 设置本体
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )
            
            # 3. 文本分块已在 Cloud mutation 前完成并验证
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )
            
            # 4. 分批发送数据
            submission = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                ),
                language=language,
                project_id=project_id,
            )
            
            # 5. 等待Zep处理完成
            self.task_manager.update_task(
                task_id,
                progress=60,
                message=t('progress.waitingZepProcess')
            )
            
            self._wait_for_batch(
                submission,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg
                )
            )
            
            # 6. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)
    
    def create_graph(
        self,
        name: str,
        *,
        graph_id: str | None = None,
        graph_id_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Create a graph with a caller-durable ID and reconcile lost replies."""

        graph_id = graph_id or f"mirofish_{uuid.uuid4().hex[:16]}"
        # Persist the client-generated ID before the non-idempotent POST so a
        # later reset can clean up a graph whose successful response was lost.
        if graph_id_callback:
            graph_id_callback(graph_id)

        try:
            self.client.graph.create(
                graph_id=graph_id,
                name=name,
                description="MiroFish Social Simulation Graph"
            )
        except Exception as error:
            if not is_retryable_zep_error(error):
                raise
            reconciliation_error = None
            for attempt in range(3):
                try:
                    call_zep_read_with_retry(
                        lambda: self.client.graph.get(graph_id),
                        operation_name=f"reconcile graph create {graph_id}",
                    )
                    reconciliation_error = None
                    break
                except NotFoundError as not_found:
                    reconciliation_error = not_found
                    if attempt < 2:
                        time.sleep(attempt + 1)
                except Exception as read_error:
                    reconciliation_error = read_error
                    break
            if reconciliation_error is not None:
                raise error from reconciliation_error

        return graph_id

    @staticmethod
    def build_operation_id(graph_id: str, chunks: List[str]) -> str:
        payload_hash = hashlib.sha256("\0".join(chunks).encode("utf-8")).hexdigest()
        return hashlib.sha256(
            f"{graph_id}:{payload_hash}".encode("utf-8")
        ).hexdigest()

    def _find_batch_by_operation_id(
        self,
        graph_id: str,
        operation_id: str,
        *,
        max_attempts: int = 3,
    ) -> Any | None:
        """Find one server-created batch after an ambiguous create reply."""

        for attempt in range(1, max_attempts + 1):
            matches: List[Any] = []
            cursor: int | None = None
            seen_cursors: set[int] = set()
            while True:
                page = call_zep_read_with_retry(
                    lambda: self.client.batch.list(limit=100, cursor=cursor),
                    operation_name=f"reconcile batch create {operation_id}",
                )
                for batch in getattr(page, "batches", None) or []:
                    metadata = getattr(batch, "metadata", None) or {}
                    if (
                        metadata.get("mirofish_operation_id") == operation_id
                        and metadata.get("graph_id") == graph_id
                    ):
                        matches.append(batch)
                next_cursor = getattr(page, "next_cursor", None)
                if next_cursor is None:
                    break
                if next_cursor == cursor or next_cursor in seen_cursors:
                    raise RuntimeError("Zep batch list cursor did not advance")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple Zep batches match operation {operation_id}; refusing ambiguity"
                )
            if matches:
                return matches[0]
            if attempt < max_attempts:
                time.sleep(attempt)
        return None
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # 抑制 Pydantic v2 关于 Field(default=None) 的警告
        # 这是 Zep SDK 要求的用法，警告来自动态类创建，可以安全忽略
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        def safe_attr_name(attr_name: str) -> str:
            """将保留名称转换为安全名称"""
            if attr_name.lower() in RESERVED_ONTOLOGY_ATTRIBUTE_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # 动态创建实体类型
        entity_types = {}
        for entity_def in ontology.get("entity_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            
            # 创建属性字典和类型注解（Pydantic v2 需要）
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                entity_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])  # 使用安全名称
                attr_desc = normalized["description"]
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # 类型注解
            
            attrs["__annotations__"] = annotations
            
            # 动态创建类
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class
        
        # 动态创建边类型
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", [])[:MAX_ONTOLOGY_TYPES]:
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            
            # 创建属性字典和类型注解
            attrs = {"__doc__": description}
            annotations = {}
            
            for normalized in normalize_ontology_attributes(
                edge_def.get("attributes", [])
            ):
                attr_name = safe_attr_name(normalized["name"])  # 使用安全名称
                attr_desc = normalized["description"]
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # 边属性用str类型
            
            attrs["__annotations__"] = annotations
            
            # 动态创建类
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            
            # 构建source_targets
            source_targets = []
            for st in normalize_ontology_source_targets(
                edge_def.get("source_targets", [])
            ):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity")
                    )
                )
            
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)
        
        # 调用Zep API设置本体
        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                # Zep iterates entities.items(), so edge-only ontologies must
                # pass an empty dictionary rather than None.
                entities=entity_types,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 350,
        progress_callback: Optional[Callable] = None,
        batch_created_callback: Optional[Callable[[str | None, str], None]] = None,
        *,
        language: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> BatchSubmission:
        """Submit document chunks through Zep's current Batch API.

        Mutating calls are deliberately not retried: create/add are not
        documented as idempotent, and an ambiguous replay can duplicate graph
        episodes. The returned batch identity allows callers to persist and
        reconcile the operation instead.

        Each chunk's metadata states the gathering's record language
        ("language": ``language``, else graph_record_language() of the project
        or the graph), so the local extraction writes the memory in it: an
        English gathering built from a Chinese scroll names Socrates in
        English, with the scroll's own form as an alias. When no language is
        known the key is left out and the memory follows the text.
        """

        if not graph_id:
            raise ValueError("graph_id is required")
        self.validate_batch_chunks(chunks, batch_size=batch_size)

        record_lang = (
            normalize_lang(language, default=None)
            or graph_record_language(graph_id, project_id=project_id)
        )
        language_metadata = {"language": record_lang} if record_lang else {}

        total_chunks = len(chunks)
        operation_id = self.build_operation_id(graph_id, chunks)
        if batch_created_callback:
            # Journal the deterministic operation before the server-generated
            # batch ID POST. This leaves enough identity for later diagnosis
            # even if both the response and immediate list reconciliation fail.
            batch_created_callback(None, operation_id)

        try:
            batch = self.client.batch.create(
                metadata={
                    "mirofish_operation_id": operation_id,
                    "graph_id": graph_id,
                    "chunk_count": total_chunks,
                }
            )
        except Exception as error:
            if not is_retryable_zep_error(error):
                raise
            batch = self._find_batch_by_operation_id(graph_id, operation_id)
            if batch is None:
                raise RuntimeError(
                    "Zep batch creation is unconfirmed and no matching operation was found"
                ) from error
        batch_id = getattr(batch, "batch_id", None)
        if not batch_id:
            raise RuntimeError("Zep Batch API returned no batch_id")
        if batch_created_callback:
            batch_created_callback(batch_id, operation_id)

        episode_uuids: List[str] = []
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    t('progress.sendingBatch', current=batch_num, total=total_batches, chunks=len(batch_chunks)),
                    progress
                )
            
            items = [
                BatchAddItem(
                    type="graph_episode",
                    graph_id=graph_id,
                    data=chunk,
                    data_type="text",
                    source_description="MiroFish source document chunk",
                    metadata={
                        "mirofish_operation_id": operation_id,
                        "chunk_index": i + offset,
                        "chunk_sha256": hashlib.sha256(
                            chunk.encode("utf-8")
                        ).hexdigest(),
                        **language_metadata,
                    },
                )
                for offset, chunk in enumerate(batch_chunks)
            ]

            expected_item_count = i + len(items)
            try:
                item_details = self.client.batch.add(
                    batch_id=batch_id,
                    items=items,
                )
            except Exception as e:
                if progress_callback:
                    progress_callback(t('progress.batchFailed', batch=batch_num, error=str(e)), 0)
                if is_retryable_zep_error(e):
                    recovered_items = self._reconcile_batch_item_count(
                        batch_id,
                        expected_item_count,
                    )
                    recovered_indexes = {
                        getattr(item, "sequence_index", None)
                        for item in recovered_items
                    }
                    if (
                        len(recovered_items) == expected_item_count
                        and recovered_indexes == set(range(expected_item_count))
                    ):
                        item_details = recovered_items[i:expected_item_count]
                    else:
                        raise RuntimeError(
                            f"Zep batch {batch_id} item submission is unconfirmed; "
                            "the draft was not processed or replayed"
                        ) from e
                else:
                    raise RuntimeError(
                        f"Zep batch {batch_id} item submission failed"
                    ) from e

            if len(item_details or []) != len(items):
                recovered_items = self._reconcile_batch_item_count(
                    batch_id,
                    expected_item_count,
                )
                recovered_indexes = {
                    getattr(item, "sequence_index", None)
                    for item in recovered_items
                }
                if (
                    len(recovered_items) == expected_item_count
                    and recovered_indexes == set(range(expected_item_count))
                ):
                    item_details = recovered_items[i:expected_item_count]
                else:
                    raise RuntimeError(
                        f"Zep batch {batch_id} acknowledged {len(item_details or [])} "
                        f"of {len(items)} items"
                    )
            for item in item_details:
                episode_uuid = getattr(item, "episode_uuid", None)
                if episode_uuid:
                    episode_uuids.append(episode_uuid)

        try:
            self.client.batch.process(batch_id=batch_id)
        except Exception as error:
            # A process response can be lost after the server accepted it.
            # Reconcile with a safe GET instead of issuing a second POST.
            summary = call_zep_read_with_retry(
                lambda: self.client.batch.get(batch_id=batch_id),
                operation_name=f"reconcile batch {batch_id}",
            )
            if getattr(summary, "status", None) in {None, "draft"}:
                raise RuntimeError(
                    f"Zep batch {batch_id} processing is unconfirmed"
                ) from error

        return BatchSubmission(
            batch_id=batch_id,
            operation_id=operation_id,
            episode_uuids=episode_uuids,
            item_count=total_chunks,
        )

    @staticmethod
    def validate_batch_chunks(chunks: List[str], *, batch_size: int = 350) -> None:
        """Validate every Batch API limit before the first Cloud mutation."""

        if not chunks:
            raise ValueError("At least one text chunk is required")
        if not 1 <= batch_size <= 350:
            raise ValueError("batch_size must be between 1 and 350")
        if len(chunks) > 50_000:
            raise ValueError("A Zep batch cannot contain more than 50,000 items")
        oversized = [index for index, chunk in enumerate(chunks) if len(chunk) > 10_000]
        if oversized:
            raise ValueError(
                f"Zep batch item exceeds 10,000 characters at chunk {oversized[0]}"
            )

    def _list_batch_items(self, batch_id: str) -> List[Any]:
        items: List[Any] = []
        cursor: int | None = None
        seen_cursors: set[int] = set()
        while True:
            page = call_zep_read_with_retry(
                lambda: self.client.batch.list_items(
                    batch_id=batch_id,
                    limit=100,
                    cursor=cursor,
                ),
                operation_name=f"list batch items {batch_id}",
            )
            items.extend(getattr(page, "items", None) or [])
            next_cursor = getattr(page, "next_cursor", None)
            if next_cursor is None:
                break
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise RuntimeError(f"Zep batch {batch_id} item cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return items

    def _reconcile_batch_item_count(
        self,
        batch_id: str,
        expected_item_count: int,
        *,
        max_attempts: int = 3,
    ) -> List[Any]:
        """Allow a short propagation window after an ambiguous add reply."""

        items: List[Any] = []
        for attempt in range(1, max_attempts + 1):
            items = self._list_batch_items(batch_id)
            if len(items) >= expected_item_count:
                return items
            if attempt < max_attempts:
                time.sleep(attempt)
        return items

    def get_batch_summary(self, batch_id: str) -> Any:
        """Read a persisted batch identity for restart reconciliation."""

        return call_zep_read_with_retry(
            lambda: self.client.batch.get(batch_id=batch_id),
            operation_name=f"get batch {batch_id}",
        )

    def _uses_local_backend(self) -> bool:
        """True for the SQLite ``LocalZep`` client (the SDK client and test fakes lack ``backend``)."""

        return getattr(self.client, "backend", None) == "local"

    def _read_batch_summary(self, batch_id: str) -> Any:
        return call_zep_read_with_retry(
            lambda: self.client.batch.get(batch_id=batch_id),
            operation_name=f"poll batch {batch_id}",
        )

    @staticmethod
    def _report_batch_wait(
        progress_callback: Optional[Callable],
        submission: BatchSubmission,
        progress: Any,
        elapsed: float,
    ) -> None:
        if not progress_callback:
            return
        percent = float(getattr(progress, "percent_complete", 0) or 0) / 100
        completed = int(getattr(progress, "succeeded_items", 0) or 0)
        progress_callback(
            t(
                'progress.zepProcessing',
                completed=completed,
                total=submission.item_count,
                pending=max(submission.item_count - completed, 0),
                elapsed=int(elapsed),
            ),
            min(max(percent, 0.0), 1.0),
        )

    def _wait_for_batch(
        self,
        submission: BatchSubmission,
        progress_callback: Optional[Callable] = None,
        timeout: int | None = None,
    ) -> List[str]:
        """Wait for a Batch API terminal state and validate every item.

        Zep Cloud: ``timeout`` (default ``ZEP_INGESTION_WAIT_TIMEOUT_SECONDS``)
        bounds the total wait. Local backend: ``timeout`` (default the client's
        ``ingestion_wait_timeout_seconds``) is how long the wait tolerates no
        progress at all, see ``_poll_local_batch``. Either way a give-up raises
        ``BatchWaitTimeoutError`` (a ``TimeoutError``).
        """

        if self._uses_local_backend():
            summary = self._poll_local_batch(
                submission,
                progress_callback,
                idle_timeout=float(
                    timeout
                    or client_ingestion_timeout(self.client, ZEP_INGESTION_WAIT_TIMEOUT_SECONDS)
                ),
            )
        else:
            summary = self._poll_cloud_batch(
                submission,
                progress_callback,
                timeout=timeout
                or client_ingestion_timeout(self.client, ZEP_INGESTION_WAIT_TIMEOUT_SECONDS),
            )
        return self._validate_finished_batch(
            submission,
            getattr(summary, "status", None),
            progress_callback,
        )

    def _poll_cloud_batch(
        self,
        submission: BatchSubmission,
        progress_callback: Optional[Callable],
        *,
        timeout: float,
    ) -> Any:
        """Poll a Zep Cloud batch until it is terminal, within a fixed total deadline."""

        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise BatchWaitTimeoutError(
                    f"Zep batch {submission.batch_id} did not finish within {timeout}s",
                    batch_id=submission.batch_id,
                    status=None,
                    resumable=False,
                )

            summary = self._read_batch_summary(submission.batch_id)
            self._report_batch_wait(
                progress_callback,
                submission,
                getattr(summary, "progress", None),
                time.time() - start_time,
            )
            if getattr(summary, "status", None) in BATCH_TERMINAL_STATES:
                return summary
            time.sleep(BATCH_POLL_INTERVAL_SECONDS)

    def _poll_local_batch(
        self,
        submission: BatchSubmission,
        progress_callback: Optional[Callable],
        *,
        idle_timeout: float,
    ) -> Any:
        """Poll a local-backend batch until it is terminal; time out on a stall only.

        The local worker extracts at ``LOCAL_MEMORY_LLM_CONCURRENCY`` and
        drains one FIFO queue across all graphs, so a large document, or one
        queued behind another project's batch, legitimately takes longer than
        any fixed deadline. The idle timer restarts whenever this batch or a
        batch in the queue with it moves forward (see ``_LocalQueueProgress``).
        A hard cap scaled to the outstanding work bounds the wait anyway.

        Uses the monotonic clock, so time the machine spends asleep (when the
        worker cannot run either) does not count as a stall.
        """

        start = time.monotonic()
        last_progress_at = start
        tracker = _LocalQueueProgress()
        hard_cap: float | None = None

        while True:
            summary = self._read_batch_summary(submission.batch_id)
            status = getattr(summary, "status", None)
            progress = getattr(summary, "progress", None)
            now = time.monotonic()
            self._report_batch_wait(progress_callback, submission, progress, now - start)
            if status in BATCH_TERMINAL_STATES:
                return summary

            others = self._list_other_active_local_batches(submission.batch_id)
            if hard_cap is None:
                hard_cap = self._local_batch_hard_cap(submission, idle_timeout, others)
            advanced = tracker.observe(submission.batch_id, progress)
            if others is not None and tracker.observe_others(others):
                advanced = True
            if advanced:
                last_progress_at = now

            finished, _started = _batch_progress_marks(progress)
            state = (
                f"status {status}, {finished}/{submission.item_count} items finished, "
                f"waited {int(now - start)}s"
            )
            if now - last_progress_at > idle_timeout:
                raise BatchWaitTimeoutError(
                    f"Local memory batch {submission.batch_id} made no progress for "
                    f"{int(idle_timeout)}s ({state}). Check the LLM settings, or raise "
                    "LOCAL_MEMORY_INGESTION_TIMEOUT_SECONDS for a slow LLM.",
                    batch_id=submission.batch_id,
                    status=status,
                    resumable=status in _LOCAL_ACTIVE_BATCH_STATUSES,
                )
            if now - start > hard_cap:
                raise BatchWaitTimeoutError(
                    f"Local memory batch {submission.batch_id} did not finish within "
                    f"{int(hard_cap)}s ({state}).",
                    batch_id=submission.batch_id,
                    status=status,
                    resumable=status in _LOCAL_ACTIVE_BATCH_STATUSES,
                )
            time.sleep(BATCH_POLL_INTERVAL_SECONDS)

    def _list_other_active_local_batches(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Queued/processing local batches other than ``batch_id``, by batch ID.

        They share the worker's FIFO queue with ``batch_id``. Returns ``None``
        when the listing fails: queue liveness is advisory, so a failed probe
        must not fail the build (the batch poll itself still has to succeed).
        """

        active: Dict[str, Any] = {}
        try:
            for status in _LOCAL_ACTIVE_BATCH_STATUSES:
                # One page is enough: far fewer than 100 builds run at once.
                page = call_zep_read_with_retry(
                    lambda status=status: self.client.batch.list(limit=100, status=status),
                    operation_name=f"list {status} batches",
                )
                for batch in getattr(page, "batches", None) or []:
                    other_id = getattr(batch, "batch_id", None)
                    if other_id and other_id != batch_id:
                        active[other_id] = batch
        except Exception as error:
            logger.debug(
                "Local batch queue probe failed while waiting for %s: %s",
                batch_id,
                type(error).__name__,
            )
            return None
        return active

    @staticmethod
    def _local_batch_hard_cap(
        submission: BatchSubmission,
        idle_timeout: float,
        others: Optional[Dict[str, Any]],
    ) -> float:
        """Backstop for a local wait: several hours, more for large or queued-behind builds."""

        outstanding = submission.item_count
        for summary in (others or {}).values():
            progress = getattr(summary, "progress", None)
            total = int(
                getattr(progress, "total_items", 0)
                or getattr(summary, "item_count", 0)
                or 0
            )
            finished, _started = _batch_progress_marks(progress)
            outstanding += max(total - finished, 0)
        return float(max(
            LOCAL_BATCH_WAIT_MIN_HARD_CAP_SECONDS,
            idle_timeout,
            LOCAL_BATCH_WAIT_SECONDS_PER_ITEM * outstanding,
        ))

    def _validate_finished_batch(
        self,
        submission: BatchSubmission,
        status: Optional[str],
        progress_callback: Optional[Callable],
    ) -> List[str]:
        """Check a terminal batch's items and return their episode UUIDs in order."""

        items = self._list_batch_items(submission.batch_id)
        if status != "succeeded":
            failed_items = [
                item for item in items
                if getattr(item, "status", None) not in {"succeeded", "skipped"}
            ]
            first_error = getattr(failed_items[0], "error", None) if failed_items else None
            raise RuntimeError(
                f"Zep batch {submission.batch_id} ended as {status}; "
                f"failed_items={len(failed_items)}; first_error={first_error}"
            )
        if len(items) != submission.item_count:
            raise RuntimeError(
                f"Zep batch {submission.batch_id} contains {len(items)} items, "
                f"expected {submission.item_count}"
            )

        ordered_items = sorted(
            items,
            key=lambda item: getattr(item, "sequence_index", 0) or 0,
        )
        episode_uuids: List[str] = []
        for item in ordered_items:
            item_status = getattr(item, "status", None)
            episode_uuid = getattr(item, "episode_uuid", None)
            source_uuid = getattr(item, "source_uuid", None)
            if item_status != "succeeded" or not episode_uuid:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} returned an incomplete item"
                )
            if source_uuid and source_uuid != episode_uuid:
                raise RuntimeError(
                    f"Zep batch {submission.batch_id} returned mismatched episode UUIDs"
                )
            episode_uuids.append(episode_uuid)

        if progress_callback:
            progress_callback(
                t(
                    'progress.processingComplete',
                    completed=len(episode_uuids),
                    total=submission.item_count,
                ),
                1.0,
            )
        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
    ):
        """等待所有 episode 处理完成（通过查询每个 episode 的 processed 状态）"""
        if not episode_uuids:
            if progress_callback:
                progress_callback(t('progress.noEpisodesWait'), 1.0)
            return
        
        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        
        if progress_callback:
            progress_callback(t('progress.waitingEpisodes', count=total_episodes), 0)
        
        while pending_episodes:
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        t('progress.episodesTimeout', completed=completed_count, total=total_episodes),
                        completed_count / total_episodes
                    )
                raise TimeoutError(
                    f"Zep episode processing timed out with "
                    f"{len(pending_episodes)} episode(s) still pending"
                )
            
            # 检查每个 episode 的处理状态
            for ep_uuid in list(pending_episodes):
                episode = call_zep_read_with_retry(
                    lambda: self.client.graph.episode.get(uuid_=ep_uuid),
                    operation_name=f"poll episode {ep_uuid}",
                )
                is_processed = getattr(episode, 'processed', False)

                if is_processed:
                    pending_episodes.remove(ep_uuid)
                    completed_count += 1
            
            elapsed = int(time.time() - start_time)
            if progress_callback:
                progress_callback(
                    t('progress.zepProcessing', completed=completed_count, total=total_episodes, pending=len(pending_episodes), elapsed=elapsed),
                    completed_count / total_episodes if total_episodes > 0 else 0
                )
            
            if pending_episodes:
                time.sleep(3)  # 每3秒检查一次
        
        if progress_callback:
            progress_callback(t('progress.processingComplete', completed=completed_count, total=total_episodes), 1.0)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = fetch_all_nodes(self.client, graph_id)

        # 获取边（分页）
        edges = fetch_all_edges(self.client, graph_id)

        # 统计实体类型
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        获取完整图谱数据（包含详细信息）
        
        Args:
            graph_id: 图谱ID
            
        Returns:
            包含nodes和edges的字典，包括时间信息、属性等详细数据
        """
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""
        
        nodes_data = []
        for node in nodes:
            # 获取创建时间
            created_at = getattr(node, 'created_at', None)
            if created_at:
                created_at = str(created_at)
            
            nodes_data.append({
                "uuid": node.uuid_,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": created_at,
            })
        
        edges_data = []
        for edge in edges:
            # 获取时间信息
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)
            
            # 获取 episodes
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]
            
            # 获取 fact_type
            fact_type = getattr(edge, 'fact_type', None) or edge.name or ""
            
            edges_data.append({
                "uuid": edge.uuid_,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes or [],
            })
        
        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
    
    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.graph.delete(graph_id=graph_id)
