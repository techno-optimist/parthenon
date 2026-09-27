"""
模拟相关API路由
Step2: Zep实体读取与过滤、OASIS模拟准备与运行（全程自动化）
"""

import os
import traceback
from contextlib import nullcontext
from flask import request, jsonify, send_file

from . import simulation_bp
from ..config import Config
from .. import public
from ..services.zep_entity_reader import ZepEntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import SimulationManager, SimulationStatus, live_preparation_task
from ..services.simulation_runner import (
    SimulationRunner,
    RunnerStatus,
    SimulationStopPending,
)
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..services import citizen_portraits, symposium_memory
from ..utils.logger import get_logger
from ..utils.json_files import write_json_atomic
from ..utils.locale import t, get_locale, set_locale, normalize_lang, language_instruction_for
from ..services.language_guard import ensure_language_many, foreign_script, record_language
from ..services.graph_builder import graph_record_language
from ..utils.zep_lifecycle import get_graph_readers, graph_lifecycle_lock
from ..models.project import ProjectManager

logger = get_logger('mirofish.api.simulation')


def _get_default_platform(simulation_id: str) -> str:
    """
    根据模拟配置返回默认平台

    读取 SimulationState 中的 enable_twitter / enable_reddit 设置，
    返回该模拟实际使用的平台，而非硬编码 'reddit'。

    Args:
        simulation_id: 模拟ID

    Returns:
        'twitter' 或 'reddit'
    """
    try:
        manager = SimulationManager()
        state = manager._load_simulation_state(simulation_id)
        if state:
            return state.get_default_platform()
    except Exception:
        pass
    return "reddit"


# Interview prompt 优化前缀
# 添加此前缀可以避免Agent调用工具，直接用文本回复. A live answer is for the
# visitor asking, so the prefix is in their language (the page's "lang", else
# the request's Accept-Language), and asks for that language whatever the
# persona, memories and question are written in: the guard can put a stray
# answer into English, but nothing puts one into Chinese. symposium_memory
# keeps copies of these to strip from a page's history; tests pin them equal.
INTERVIEW_PROMPT_PREFIX = (
    "Drawing on your persona and all your past memories and actions, answer me directly in plain text, "
    "without calling any tools. Answer in English, even if the question is in another language. "
    + language_instruction_for('en') + "\n\n"
)
INTERVIEW_PROMPT_PREFIX_ZH = (
    "结合你的人设、所有的过往记忆与行动，不调用任何工具直接用文本回复我。"
    "无论问题、人设或记忆使用何种语言，请始终用简体中文回答。"
    + language_instruction_for('zh') + "\n\n"
)
# The upstream prefix, which older prompts (and the square's trace) still carry.
INTERVIEW_PROMPT_PREFIX_ZH_UPSTREAM = "结合你的人设、所有的过往记忆与行动，不调用任何工具直接用文本回复我："
INTERVIEW_PROMPT_PREFIXES = {'en': INTERVIEW_PROMPT_PREFIX, 'zh': INTERVIEW_PROMPT_PREFIX_ZH}
# Every prefix a prompt may already carry, the longest first.
KNOWN_INTERVIEW_PROMPT_PREFIXES = tuple(sorted(
    {INTERVIEW_PROMPT_PREFIX, INTERVIEW_PROMPT_PREFIX_ZH, INTERVIEW_PROMPT_PREFIX_ZH_UPSTREAM},
    key=len, reverse=True,
))


def interview_prompt_prefix(lang) -> str:
    """The live interview's prefix in a reading language (anything but Chinese reads English)."""

    return INTERVIEW_PROMPT_PREFIXES[normalize_lang(lang)]


def optimize_interview_prompt(prompt: str, lang=None) -> str:
    """
    优化Interview提问，添加前缀避免Agent调用工具
    
    Args:
        prompt: 原始提问
        lang: the visitor's reading language ('en' when None)
        
    Returns:
        优化后的提问
    """
    if not prompt:
        return prompt
    # 避免重复添加前缀: a prefix already there, in any language, gives way to the visitor's.
    for known in KNOWN_INTERVIEW_PROMPT_PREFIXES:
        if prompt.startswith(known):
            prompt = prompt[len(known):]
            break
    return f"{interview_prompt_prefix(lang)}{prompt}"


def _viewer_lang(data) -> str:
    """The visitor's reading language: the page's "lang", else the request's Accept-Language."""

    lang = data.get('lang') if isinstance(data, dict) else None
    return normalize_lang(lang, default=None) or get_locale()


def _live_answers_in(result, lang: str):
    """A live run's result with every answer in the visitor's language (language_guard, one call at most).

    The runner's shapes: result.response (one platform), result.platforms.*.response
    (both) and result.results.*.response (a batch). Nothing else is touched.
    """

    found = []

    def collect(node, depth=0):
        if depth > 4 or not isinstance(node, dict):
            return
        if isinstance(node.get('response'), str) and node['response']:
            found.append(node)
        for key in ('result', 'platforms', 'results'):
            child = node.get(key)
            if isinstance(child, dict):
                if key == 'result':
                    collect(child, depth + 1)
                else:
                    for item in child.values():
                        collect(item, depth + 1)

    if isinstance(result, dict):
        collect(result.get('result'))
    answers = [node['response'] for node in found]
    if any(foreign_script(answer, lang) for answer in answers):
        guarded = ensure_language_many(answers, lang, context='answers a visitor asked for at the Symposium')
        for node, answer in zip(found, guarded):
            node['response'] = answer
    return result


def _live_error(error, lang: str) -> str:
    """A live interview's refusal in words the visitor can read (the runner may still speak Chinese)."""

    text = str(error)
    return t('api.envNotRunningShort', locale=lang) if foreign_script(text, lang) else text


def _history_in(history, lang: str):
    """The square's interview trace for a visitor: every prompt and answer in their language.

    The trace keeps what was asked and said as it was (older gatherings asked
    in Chinese, and the mend leaves the square's databases alone), so a reader
    who is not Chinese gets its foreign lines through the language guard, in
    one call at most. Nothing else in a row is touched.
    """

    if lang == 'zh' or not isinstance(history, list):
        return history
    slots = [
        (row, key) for row in history if isinstance(row, dict)
        for key in ('prompt', 'response')
        if isinstance(row.get(key), str) and foreign_script(row[key], lang)
    ]
    if slots:
        guarded = ensure_language_many(
            [row[key] for row, key in slots], lang, context='what citizens were asked in the square and answered',
        )
        for (row, key), text in zip(slots, guarded):
            row[key] = text
    return history


def _live_timeout(key: str, data, default_seconds, error) -> str:
    """A live interview that ran out of time, in the visitor's words; the square's own message stays in the log."""

    logger.warning(f"A live interview ran out of time: {error}")
    seconds = data.get('timeout', default_seconds) if isinstance(data, dict) else default_seconds
    try:
        seconds = float(seconds)
        if not 0 < seconds < 10 ** 6:
            raise ValueError(seconds)
        seconds = int(seconds) if seconds.is_integer() else round(seconds, 1)
    except (TypeError, ValueError, OverflowError):
        seconds = default_seconds
    return t(key, locale=_viewer_lang(data), error=f'{seconds}s')


def _crowd_language(simulation, requirement=None, memo=None) -> str:
    """A crowd's record language for its row in a list ('en' or 'zh'), so the page need not guess.

    record_language of its project (else of the simulation), guessed from
    ``requirement`` for a gathering older than the stored language. ``memo``
    keeps one answer per gathering for the rest of a response.
    """

    project_id = getattr(simulation, 'project_id', None)
    simulation_id = getattr(simulation, 'simulation_id', None)
    requirement = requirement if isinstance(requirement, str) and requirement.strip() else None
    key = (str(project_id or f'sim:{simulation_id}'), requirement)
    if memo is not None and key in memo:
        return memo[key]
    lang = record_language(project_id=project_id, simulation_id=simulation_id, requirement=requirement)
    if memo is not None:
        memo[key] = lang
    return lang


def _profiles_language(data, graph_id) -> str:
    """The record language profiles written from a graph are in: never the thread's or the visitor's.

    The simulation or project the body names, else the project that references
    the graph, else PARTHENON_RECORD_LANGUAGE or English.
    """

    simulation_id = data.get('simulation_id') if isinstance(data, dict) else None
    project_id = data.get('project_id') if isinstance(data, dict) else None
    if simulation_id or project_id:
        return record_language(project_id=project_id, simulation_id=simulation_id)
    return graph_record_language(graph_id) or record_language()


# ============== 实体读取接口 ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    获取图谱中的所有实体（已过滤）
    
    只返回符合预定义实体类型的节点（Labels不只是Entity的节点）
    
    Query参数：
        entity_types: 逗号分隔的实体类型列表（可选，用于进一步过滤）
        enrich: 是否获取相关边信息（默认true）
    """
    try:
        if Config.memory_backend() == "zep" and not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        logger.info(f"获取图谱实体: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")
        
        reader = ZepEntityReader()
        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取图谱实体失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """获取单个实体的详细信息"""
    try:
        if Config.memory_backend() == "zep" and not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        reader = ZepEntityReader()
        entity = reader.get_entity_with_context(graph_id, entity_uuid)
        
        if not entity:
            return jsonify({
                "success": False,
                "error": t('api.entityNotFound', id=entity_uuid)
            }), 404
        
        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取实体详情失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """获取指定类型的所有实体"""
    try:
        if Config.memory_backend() == "zep" and not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": t('api.zepApiKeyMissing')
            }), 500
        
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        reader = ZepEntityReader()
        entities = reader.get_entities_by_type(
            graph_id=graph_id,
            entity_type=entity_type,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": {
                "entity_type": entity_type,
                "count": len(entities),
                "entities": [e.to_dict() for e in entities]
            }
        })
        
    except Exception as e:
        logger.error(f"获取实体失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 模拟管理接口 ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    创建新的模拟
    
    注意：max_rounds等参数由LLM智能生成，无需手动设置
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",      // 必填
            "graph_id": "mirofish_xxxx",    // 可选，如不提供则从project获取
            "enable_twitter": true,          // 可选，默认true
            "enable_reddit": true            // 可选，默认true
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "mirofish_xxxx",
                "status": "created",
                "enable_twitter": true,
                "enable_reddit": true,
                "created_at": "2025-12-01T10:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400
        
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404
        
        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.graphNotBuilt')
            }), 400
        
        manager = SimulationManager()
        state = manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=data.get('enable_twitter', True),
            enable_reddit=data.get('enable_reddit', True),
        )
        
        return jsonify({
            "success": True,
            "data": state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"创建模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    检查模拟是否已经准备完成
    
    检查条件：
    1. state.json 存在且 status 为 "ready"
    2. 必要文件存在：reddit_profiles.json, twitter_profiles.csv, simulation_config.json
    
    注意：运行脚本(run_*.py)保留在 backend/scripts/ 目录，不再复制到模拟目录
    
    Args:
        simulation_id: 模拟ID
        
    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config
    
    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    
    # 检查目录是否存在
    if not os.path.exists(simulation_dir):
        return False, {"reason": "The simulation's folder does not exist"}
    
    # 必要文件列表（不包括脚本，脚本位于 backend/scripts/）
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
        "twitter_profiles.csv"
    ]
    
    # 检查文件是否存在
    existing_files = []
    missing_files = []
    for f in required_files:
        file_path = os.path.join(simulation_dir, f)
        if os.path.exists(file_path):
            existing_files.append(f)
        else:
            missing_files.append(f)
    
    if missing_files:
        return False, {
            "reason": "Required files are missing",
            "missing_files": missing_files,
            "existing_files": existing_files
        }
    
    # 检查state.json中的状态
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
        
        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)
        
        # 详细日志
        logger.debug(f"检测模拟准备状态: {simulation_id}, status={status}, config_generated={config_generated}")
        
        # 如果 config_generated=True 且文件存在，认为准备完成
        # 以下状态都说明准备工作已完成：
        # - ready: 准备完成，可以运行
        # - preparing: 如果 config_generated=True 说明已完成
        # - running: 正在运行，说明准备早就完成了
        # - completed: 运行完成，说明准备早就完成了
        # - stopped: 已停止，说明准备早就完成了
        # - failed: 运行失败（但准备是完成的）
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed"]
        if status in prepared_statuses and config_generated:
            # 获取文件统计信息
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")
            
            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0
            
            # 如果状态是preparing但文件已完成，自动更新状态为ready
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    write_json_atomic(state_file, state_data)
                    logger.info(f"自动更新模拟状态: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"自动更新状态失败: {e}")
            
            logger.info(f"模拟 {simulation_id} 检测结果: 已准备完成 (status={status}, config_generated={config_generated})")
            return True, {
                "status": status,
                "entities_count": state_data.get("entities_count", 0),
                "profiles_count": profiles_count,
                "entity_types": state_data.get("entity_types", []),
                "config_generated": config_generated,
                "created_at": state_data.get("created_at"),
                "updated_at": state_data.get("updated_at"),
                "existing_files": existing_files
            }
        else:
            logger.warning(f"模拟 {simulation_id} 检测结果: 未准备完成 (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"Not prepared yet: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }
            
    except Exception as e:
        return False, {"reason": f"Could not read the state file: {type(e).__name__}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    准备模拟环境（异步任务，LLM智能生成所有参数）
    
    这是一个耗时操作，接口会立即返回task_id，
    使用 GET /api/simulation/prepare/status 查询进度
    
    特性：
    - 自动检测已完成的准备工作，避免重复生成
    - 如果已准备完成，直接返回已有结果
    - 支持强制重新生成（force_regenerate=true）
    
    步骤：
    1. 检查是否已有完成的准备工作
    2. 从Zep图谱读取并过滤实体
    3. 为每个实体生成OASIS Agent Profile（带重试机制）
    4. LLM智能生成模拟配置（带重试机制）
    5. 保存配置文件和预设脚本
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",                   // 必填，模拟ID
            "entity_types": ["Student", "PublicFigure"],  // 可选，指定实体类型
            "use_llm_for_profiles": true,                 // 可选，是否用LLM生成人设
            "parallel_profile_count": 5,                  // 可选，并行生成人设数量，默认5
            "force_regenerate": false                     // 可选，强制重新生成，默认false
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // 新任务时返回
                "status": "preparing|ready",
                "message": "准备任务已启动|已有完成的准备工作",
                "already_prepared": true|false    // 是否已准备完成
            }
        }
    """
    import threading
    import os
    from ..models.task import TaskManager, TaskStatus
    from ..config import Config
    
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # 检查是否强制重新生成
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"开始处理 /prepare 请求: simulation_id={simulation_id}, force_regenerate={force_regenerate}")
        
        # 检查是否已经准备完成（避免重复生成）
        if not force_regenerate:
            logger.debug(f"检查模拟 {simulation_id} 是否已准备完成...")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"检查结果: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"模拟 {simulation_id} 已准备完成，跳过重复生成")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": t('api.alreadyPrepared'),
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"模拟 {simulation_id} 未准备完成，将启动准备任务")

            # The public steps: a second summons while the first is still at
            # work (the owner's page reopened) follows the same task instead
            # of calling a second crowd.
            live = live_preparation_task(simulation_id) if public.is_public() else None
            if live:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "task_id": live["task_id"],
                        "status": "preparing",
                        "message": t('api.prepareStarted'),
                        "already_prepared": False,
                        "expected_entities_count": state.entities_count,
                        "entity_types": state.entity_types
                    }
                })
        
        # 从项目获取必要信息
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=state.project_id)
            }), 404
        
        # 获取模拟需求
        simulation_requirement = project.simulation_requirement or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.projectMissingRequirement')
            }), 400
        
        # 获取文档文本
        document_text = ProjectManager.get_extracted_text(state.project_id) or ""
        
        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 5)
        # The public steps cap the crowd (PARTHENON_MAX_CITIZENS); None elsewhere.
        crowd_cap = public.crowd_cap()
        
        # ========== 同步获取实体数量（在后台任务启动前） ==========
        # 这样前端在调用prepare后立即就能获取到预期Agent总数
        try:
            logger.info(f"同步获取实体数量: graph_id={state.graph_id}")
            reader = ZepEntityReader()
            # 快速读取实体（不需要边信息，只统计数量）
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # 不获取边信息，加快速度
            )
            # 保存实体数量到状态（供前端立即获取）
            state.entities_count = filtered_preview.filtered_count
            if crowd_cap is not None:
                state.entities_count = min(state.entities_count, crowd_cap)
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"预期实体数量: {filtered_preview.filtered_count}, 类型: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"同步获取实体数量失败（将在后台任务中重试）: {e}")
            # 失败不影响后续流程，后台任务会重新获取
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )
        
        # 更新模拟状态（包含预先获取的实体数量）
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)
        
        # The profiles and the config are the gathering's record: the worker
        # writes them in the record's language, fixed when the project was made.
        # Its progress lines are for the visitor watching, in their language.
        viewer_locale = get_locale()
        record_locale = record_language(project_id=state.project_id, simulation_id=simulation_id)

        # 定义后台任务
        def run_prepare():
            set_locale(record_locale)
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message=t('progress.startPreparingEnv', locale=viewer_locale)
                )
                
                # 准备模拟（带进度回调）
                # 存储阶段进度详情
                stage_details = {}
                
                def progress_callback(stage, progress, message, **kwargs):
                    # 计算总进度
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }
                    
                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)
                    
                    # 构建详细进度信息
                    stage_names = {
                        "reading": t('progress.readingGraphEntities', locale=viewer_locale),
                        "generating_profiles": t('progress.generatingProfiles', locale=viewer_locale),
                        "generating_config": t('progress.generatingSimConfig', locale=viewer_locale),
                        "copying_scripts": t('progress.preparingScripts', locale=viewer_locale)
                    }
                    
                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)
                    
                    # 更新阶段详情
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }
                    
                    # 构建详细进度信息
                    detail = stage_details[stage]
                    progress_detail_data = {
                        "current_stage": stage,
                        "current_stage_name": stage_names.get(stage, stage),
                        "stage_index": stage_index,
                        "total_stages": total_stages,
                        "stage_progress": progress,
                        "current_item": detail["current"],
                        "total_items": detail["total"],
                        "item_description": message
                    }
                    
                    # 构建简洁消息
                    if detail["total"] > 0:
                        detailed_message = (
                            f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: "
                            f"{detail['current']}/{detail['total']} - {message}"
                        )
                    else:
                        detailed_message = f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: {message}"
                    
                    task_manager.update_task(
                        task_id,
                        progress=current_progress,
                        message=detailed_message,
                        progress_detail=progress_detail_data
                    )
                
                result_state = manager.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    defined_entity_types=entity_types_list,
                    use_llm_for_profiles=use_llm_for_profiles,
                    progress_callback=progress_callback,
                    parallel_profile_count=parallel_profile_count,
                    **({'max_entities': crowd_cap} if crowd_cap is not None else {})
                )

                if result_state.status == SimulationStatus.FAILED:
                    task_manager.fail_task(
                        task_id,
                        result_state.error
                        or t('log.prepareFailed', locale=viewer_locale, error=simulation_id)
                    )
                else:
                    task_manager.complete_task(
                        task_id,
                        result=result_state.to_simple_dict()
                    )
                
            except Exception as e:
                logger.error(f"准备模拟失败: {str(e)}")
                task_manager.fail_task(task_id, str(e))
                
                # 更新模拟状态为失败
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)
        
        # 启动后台线程
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": t('api.prepareStarted'),
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # 预期的Agent总数
                "entity_types": state.entity_types  # 实体类型列表
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"启动准备任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    查询准备任务进度
    
    支持两种查询方式：
    1. 通过task_id查询正在进行的任务进度
    2. 通过simulation_id检查是否已有完成的准备工作
    
    请求（JSON）：
        {
            "task_id": "task_xxxx",          // 可选，prepare返回的task_id
            "simulation_id": "sim_xxxx"      // 可选，模拟ID（用于检查已完成的准备）
        }
    
    返回：
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,  // 是否已有完成的准备
                "prepare_info": {...}            // 已准备完成时的详细信息
            }
        }
    """
    from ..models.task import TaskManager
    
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # 如果提供了simulation_id，先检查是否已准备完成
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": t('api.alreadyPrepared'),
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
        
        # 如果没有task_id，返回错误
        if not task_id:
            # The public steps: a guest knows only the gathering; show them the
            # preparation at work rather than "not called yet".
            live = live_preparation_task(simulation_id) if simulation_id and public.is_public() else None
            if live:
                return jsonify({
                    "success": True,
                    "data": {**live, "simulation_id": simulation_id, "already_prepared": False}
                })
            if simulation_id:
                # 有simulation_id但未准备完成
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": t('api.notStartedPrepare'),
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": t('api.requireTaskOrSimId')
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            # 任务不存在，但如果有simulation_id，检查是否已准备完成
            if simulation_id:
                is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
                if is_prepared:
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "task_id": task_id,
                            "status": "ready",
                            "progress": 100,
                            "message": t('api.taskCompletedPrepared'),
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })
            
            return jsonify({
                "success": False,
                "error": t('api.taskNotFound', id=task_id)
            }), 404
        
        task_dict = task.to_dict()
        task_dict["already_prepared"] = False
        
        return jsonify({
            "success": True,
            "data": task_dict
        })
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """获取模拟状态"""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        result = state.to_dict()
        # The gathering's record language: the page shows its record in it.
        result["language"] = _crowd_language(state)

        # 如果模拟已准备好，附加运行说明
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取模拟状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    列出所有模拟
    
    Query参数：
        project_id: 按项目ID过滤（可选）
    """
    try:
        project_id = request.args.get('project_id')
        
        manager = SimulationManager()
        simulations = manager.list_simulations(project_id=project_id)
        visible = public.shelf_ids() if not project_id else None
        if visible is not None:
            # The public shelf (a gathering's own crowds are open to its link).
            simulations = [
                s for s in simulations
                if public.simulation_on_shelf(visible, s.simulation_id, s.project_id)
            ]

        # Each row carries its gathering's record language, so the page need not guess it.
        languages = {}
        rows = []
        for s in simulations:
            row = s.to_dict()
            row["language"] = _crowd_language(s, memo=languages)
            rows.append(row)

        return jsonify({
            "success": True,
            "data": rows,
            "count": len(simulations)
        })
        
    except Exception as e:
        logger.error(f"列出模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """
    获取 simulation 对应的最新 report_id
    
    遍历 reports 目录，找出 simulation_id 匹配的 report，
    如果有多个则返回最新的（按 created_at 排序）
    
    Args:
        simulation_id: 模拟ID
        
    Returns:
        report_id 或 None
    """
    import json
    from datetime import datetime
    
    # reports 目录路径：backend/uploads/reports
    # __file__ 是 app/api/simulation.py，需要向上两级到 backend/
    reports_dir = (
        os.path.join(Config.UPLOAD_FOLDER, 'reports') if Config.DATA_DIR
        else os.path.join(os.path.dirname(__file__), '../../uploads/reports')
    )
    if not os.path.exists(reports_dir):
        return None
    
    matching_reports = []
    
    try:
        for report_folder in os.listdir(reports_dir):
            report_path = os.path.join(reports_dir, report_folder)
            if not os.path.isdir(report_path):
                continue
            
            meta_file = os.path.join(report_path, "meta.json")
            if not os.path.exists(meta_file):
                continue
            
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                if meta.get("simulation_id") == simulation_id:
                    matching_reports.append({
                        "report_id": meta.get("report_id"),
                        "created_at": meta.get("created_at", ""),
                        "status": meta.get("status", "")
                    })
            except Exception:
                continue
        
        if not matching_reports:
            return None
        
        # 按创建时间倒序排序，返回最新的
        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")
        
    except Exception as e:
        logger.warning(f"查找 simulation {simulation_id} 的 report 失败: {e}")
        return None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    获取历史模拟列表（带项目详情）
    
    用于首页历史项目展示，返回包含项目名称、描述等丰富信息的模拟列表
    
    Query参数：
        limit: 返回数量限制（默认20）
    
    返回：
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "武大舆情分析",
                    "simulation_requirement": "如果武汉大学发布...",
                    "status": "completed",
                    "entities_count": 68,
                    "profiles_count": 68,
                    "entity_types": ["Student", "Professor", ...],
                    "created_at": "2024-12-10",
                    "updated_at": "2024-12-10",
                    "total_rounds": 120,
                    "current_round": 120,
                    "report_id": "report_xxxx",
                    "question": "如果武汉大学发布...",
                    "report_title": "The Marble Question",
                    "report_status": "completed",
                    "film": {
                        "status": "completed",
                        "poster_url": "/api/parthenon/chronicle/report_xxxx/film/poster.jpg?v=1758800000"
                    },
                    "language": "en",
                    "version": "v1.0.2"
                },
                ...
            ],
            "count": 7
        }

    The Chronicles shelf reads question (the simulation_requirement), report_title
    and report_status (the newest Chronicle of the run, when there is one), film
    (the Chronicle's film: its status, and a poster_url only once the film is
    complete) and language (the gathering's record language, 'en' or 'zh').
    Every field that existed before the shelf is still returned.
    """
    # The film url builder lives in the parthenon API, which api/__init__.py
    # registers after this module, so it is imported here rather than at the top.
    import json
    from ..services import chronicle_film
    from ..services.report_agent import ReportManager
    from .parthenon import _film_file_url

    def chronicle_title(report_id, report):
        """The Chronicle's title from its meta, else from the outline saved while planning."""
        if report is not None and report.outline is not None and report.outline.title:
            return report.outline.title
        try:
            with open(ReportManager._get_outline_path(report_id), 'r', encoding='utf-8') as f:
                outline = json.load(f)
        except (OSError, ValueError):
            return None
        title = outline.get("title") if isinstance(outline, dict) else None
        return title or None

    def film_for_shelf(report_id):
        """{status, poster_url}: what the film endpoint would answer, without writing anything."""
        try:
            manifest = chronicle_film.read_manifest(report_id)
        except chronicle_film.FilmValidationError:
            manifest = None
        status = manifest["status"] if manifest else "none"
        if status == "running" and not chronicle_film.is_filming(report_id):
            # The film died with a restart; the film endpoint records that when next asked.
            status = "failed"
        poster_url = None
        if status == "completed":
            poster_url = _film_file_url(report_id, chronicle_film.POSTER_NAME)
        return {"status": status, "poster_url": poster_url}

    def chronicle_for_shelf(report_id):
        """report_title, report_status and film for the run's newest Chronicle, if any."""
        if not report_id:
            return {
                "report_title": None,
                "report_status": None,
                "film": {"status": "none", "poster_url": None},
            }
        try:
            report = ReportManager.get_report(report_id)
        except Exception as error:
            logger.warning(f"Chronicle {report_id} could not be read for the shelf: {error}")
            report = None
        return {
            "report_title": chronicle_title(report_id, report),
            "report_status": report.status.value if report else None,
            "film": film_for_shelf(report_id),
        }

    try:
        limit = request.args.get('limit', 20, type=int)

        manager = SimulationManager()
        simulations = manager.list_simulations()
        visible = public.shelf_ids()
        if visible is not None:
            # The public shelf: featured gatherings and the ones this visitor names.
            simulations = [
                s for s in simulations
                if public.simulation_on_shelf(visible, s.simulation_id, s.project_id)
            ]
        simulations = simulations[:limit]

        # 增强模拟数据，只从 Simulation 文件读取
        enriched_simulations = []
        languages = {}
        for sim in simulations:
            sim_dict = sim.to_dict()
            
            # 获取模拟配置信息（从 simulation_config.json 读取 simulation_requirement）
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # 推荐轮数（后备值）
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 / 
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0
            
            # 获取运行状态（从 run_state.json 读取用户设置的实际轮数）
            run_state = SimulationRunner.get_run_state(sim.simulation_id)
            if run_state:
                sim_dict["current_round"] = run_state.current_round
                sim_dict["runner_status"] = run_state.runner_status.value
                # 使用用户设置的 total_rounds，若无则使用推荐轮数
                sim_dict["total_rounds"] = run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds
            
            # 获取关联项目的文件列表（最多3个）
            project = ProjectManager.get_project(sim.project_id)
            if project and hasattr(project, 'files') and project.files:
                sim_dict["files"] = [
                    {"filename": f.get("filename") or t('history.unknownFile')}
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []
            
            # 获取关联的 report_id（查找该 simulation 最新的 report）
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)

            # The Chronicles shelf: the question that was asked, the Chronicle's
            # title and status, and its film (a poster only once the film is done).
            sim_dict["question"] = sim_dict["simulation_requirement"]
            sim_dict.update(chronicle_for_shelf(sim_dict["report_id"]))
            # The gathering's record language: the shelf shows the row in it rather than guessing.
            sim_dict["language"] = _crowd_language(
                sim, requirement=sim_dict["simulation_requirement"], memo=languages
            )

            # 添加版本号
            sim_dict["version"] = "v1.0.2"
            
            # 格式化日期
            try:
                created_date = sim_dict.get("created_at", "")[:10]
                sim_dict["created_date"] = created_date
            except:
                sim_dict["created_date"] = ""
            
            enriched_simulations.append(sim_dict)
        
        return jsonify({
            "success": True,
            "data": enriched_simulations,
            "count": len(enriched_simulations)
        })
        
    except Exception as e:
        logger.error(f"获取历史模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    获取模拟的Agent Profile
    
    Query参数：
        platform: 平台类型（reddit/twitter，默认reddit）
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)

        manager = SimulationManager()
        profiles = manager.get_profiles(simulation_id, platform=platform)
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(profiles),
                "profiles": profiles
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"获取Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    实时获取模拟的Agent Profile（用于在生成过程中实时查看进度）
    
    与 /profiles 接口的区别：
    - 直接读取文件，不经过 SimulationManager
    - 适用于生成过程中的实时查看
    - 返回额外的元数据（如文件修改时间、是否正在生成等）
    
    Query参数：
        platform: 平台类型（reddit/twitter，默认reddit）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // 预期总数（如果有）
                "is_generating": true,  // 是否正在生成
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "profiles": [...]
            }
        }
    """
    import json
    import csv
    from datetime import datetime
    
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)

        # 获取模拟目录
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # 确定文件路径
        if platform == "reddit":
            profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        else:
            profiles_file = os.path.join(sim_dir, "twitter_profiles.csv")
        
        # 检查文件是否存在
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None
        
        if file_exists:
            # 获取文件修改时间
            file_stat = os.stat(profiles_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                if platform == "reddit":
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        profiles = json.load(f)
                else:
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        profiles = list(reader)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"读取 profiles 文件失败（可能正在写入中）: {e}")
                profiles = []
        
        # 检查是否正在生成（通过 state.json 判断）
        is_generating = False
        total_expected = None
        status = None
        error = None
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
                    error = state_data.get("error")
            except Exception:
                pass
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "platform": platform,
                "count": len(profiles),
                "total_expected": total_expected,
                "is_generating": is_generating,
                "status": status,
                "error": error,
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })
        
    except Exception as e:
        logger.error(f"实时获取Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    实时获取模拟配置（用于在生成过程中实时查看进度）
    
    与 /config 接口的区别：
    - 直接读取文件，不经过 SimulationManager
    - 适用于生成过程中的实时查看
    - 返回额外的元数据（如文件修改时间、是否正在生成等）
    - 即使配置还没生成完也能返回部分信息
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,  // 是否正在生成
                "generation_stage": "generating_config",  // 当前生成阶段
                "config": {...}  // 配置内容（如果存在）
            }
        }
    """
    import json
    from datetime import datetime
    
    try:
        # 获取模拟目录
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404
        
        # 配置文件路径
        config_file = os.path.join(sim_dir, "simulation_config.json")
        
        # 检查文件是否存在
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None
        
        if file_exists:
            # 获取文件修改时间
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"读取 config 文件失败（可能正在写入中）: {e}")
                config = None
        
        # 检查是否正在生成（通过 state.json 判断）
        is_generating = False
        generation_stage = None
        status = None
        error = None
        profiles_generated = False
        config_generated = False
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    error = state_data.get("error")
                    is_generating = status == "preparing"
                    profiles_generated = state_data.get("profiles_generated", False)
                    config_generated = state_data.get("config_generated", False)
                    
                    # 判断当前阶段
                    if is_generating:
                        if profiles_generated:
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
                    elif status == "failed":
                        generation_stage = "failed"
            except Exception:
                pass
        
        # 构建返回数据
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "status": status,
            "error": error,
            "generation_stage": generation_stage,
            "profiles_generated": profiles_generated,
            "config_generated": config_generated,
            "config": config
        }
        
        # 如果配置存在，提取一些关键统计信息
        if config:
            response_data["summary"] = {
                "total_agents": len(config.get("agent_configs", [])),
                "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
                "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
                "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
                "has_twitter_config": "twitter_config" in config,
                "has_reddit_config": "reddit_config" in config,
                "generated_at": config.get("generated_at"),
                "llm_model": config.get("llm_model")
            }
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"实时获取Config失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    获取模拟配置（LLM智能生成的完整配置）
    
    返回包含：
        - time_config: 时间配置（模拟时长、轮次、高峰/低谷时段）
        - agent_configs: 每个Agent的活动配置（活跃度、发言频率、立场等）
        - event_config: 事件配置（初始帖子、热点话题）
        - platform_configs: 平台配置
        - generation_reasoning: LLM的配置推理说明
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)
        
        if not config:
            return jsonify({
                "success": False,
                "error": t('api.configNotFound')
            }), 404
        
        return jsonify({
            "success": True,
            "data": config
        })
        
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """下载模拟配置文件"""
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": t('api.configFileNotFound')
            }), 404
        
        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )
        
    except Exception as e:
        logger.error(f"下载配置失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    下载模拟运行脚本文件（通用脚本，位于 backend/scripts/）
    
    script_name可选值：
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # 脚本位于 backend/scripts/ 目录
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        # 验证脚本名称
        allowed_scripts = [
            "run_twitter_simulation.py",
            "run_reddit_simulation.py", 
            "run_parallel_simulation.py",
            "action_logger.py"
        ]
        
        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": t('api.unknownScript', name=script_name, allowed=allowed_scripts)
            }), 400
        
        script_path = os.path.join(scripts_dir, script_name)
        
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": t('api.scriptFileNotFound', name=script_name)
            }), 404
        
        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )
        
    except Exception as e:
        logger.error(f"下载脚本失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Profile生成接口（独立使用） ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    直接从图谱生成OASIS Agent Profile（不创建模拟）
    
    请求（JSON）：
        {
            "graph_id": "mirofish_xxxx",     // 必填
            "entity_types": ["Student"],      // 可选
            "use_llm": true,                  // 可选
            "platform": "reddit",             // 可选
            "simulation_id": "sim_xxxx",      // optional: whose record language the profiles are in
            "project_id": "proj_xxxx"         // optional, the same
        }

    The profiles are written in the record language of the gathering named,
    else of the project that references the graph (_profiles_language).
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphId')
            }), 400
        
        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')
        
        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )
        
        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": t('api.noMatchingEntities')
            }), 400
        
        # The profiles are the record: in its language, not the thread's or the visitor's.
        generator = OasisProfileGenerator(language=_profiles_language(data, graph_id))
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm
        )
        
        if platform == "reddit":
            profiles_data = [p.to_reddit_format() for p in profiles]
        elif platform == "twitter":
            profiles_data = [p.to_twitter_format() for p in profiles]
        else:
            profiles_data = [p.to_dict() for p in profiles]
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "entity_types": list(filtered.entity_types),
                "count": len(profiles_data),
                "profiles": profiles_data
            }
        })
        
    except Exception as e:
        logger.error(f"生成Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 模拟运行控制接口 ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    开始运行模拟

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",          // 必填，模拟ID
            "platform": "parallel",                // 可选: twitter / reddit / parallel (默认)
            "max_rounds": 100,                     // 可选: 最大模拟轮数，用于截断过长的模拟
            "enable_graph_memory_update": false,   // 可选: 是否将Agent活动动态更新到Zep图谱记忆
            "force": false                         // 可选: 强制重新开始（会停止运行中的模拟并清理日志）
        }

    关于 force 参数：
        - 启用后，如果模拟正在运行或已完成，会先停止并清理运行日志
        - 清理的内容包括：run_state.json, actions.jsonl, simulation.log 等
        - 不会清理配置文件（simulation_config.json）和 profile 文件
        - 适用于需要重新运行模拟的场景
        - Applies whatever state.json says, READY included.

    A run whose process is gone (e.g. the backend restarted mid-run) is first
    marked stopped, with a note, so it no longer blocks a start. Refused at
    once, force or not: a run this server is starting, stopping or finalizing
    (the request never waits for a graph memory drain), and a simulator left
    running by a previous backend. With force, a running run is stopped and a
    finished run's interview environment is closed before the logs are
    cleared; without force both are refused.

    关于 enable_graph_memory_update：
        - 启用后，模拟中所有Agent的活动（发帖、评论、点赞等）都会实时更新到Zep图谱
        - 这可以让图谱"记住"模拟过程，用于后续分析或AI对话
        - 需要模拟关联的项目有有效的 graph_id
        - 采用批量更新机制，减少API调用次数

    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,  // 是否启用了图谱记忆更新
                "force_restarted": true               // 是否是强制重新开始
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # 可选：最大模拟轮数
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # 可选：是否启用图谱记忆更新
        force = data.get('force', False)  # 可选：强制重新开始
        if not isinstance(enable_graph_memory_update, bool):
            return jsonify({
                "success": False,
                "error": "enable_graph_memory_update must be a JSON boolean",
            }), 400
        if not isinstance(force, bool):
            return jsonify({
                "success": False,
                "error": "force must be a JSON boolean",
            }), 400

        # 验证 max_rounds 参数
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": t('api.maxRoundsPositive')
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": t('api.maxRoundsInvalid')
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": t('api.invalidPlatform', platform=platform)
            }), 400

        # 检查模拟是否已准备好
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        force_restarted = False

        # A run left active by a backend that has since restarted has no
        # process, monitor or updater to finish it. Mark it stopped first so
        # it cannot block this start, whatever state.json says (READY, or a
        # STOPPING that the prepared check below would reject), and find out
        # what still owns the run. This never waits on the runner's
        # finalization lock: its holder is launching, stopping or draining
        # this very run (a graph memory drain takes minutes), and a forced
        # start that waited it out would then wipe the run that just ended.
        run_state, owner = SimulationRunner.reconcile_and_find_owner(simulation_id)
        # The reconcile may have synced state.json; this manager caches the
        # old one.
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id) or state

        if owner in {"busy", "starting", "stopping"}:
            # This server is launching, stopping or finalizing the run now.
            return jsonify({
                "success": False,
                "error": t('api.simAlreadyActive', id=simulation_id)
            }), 400
        if owner == "orphan_process":
            # A simulator from a previous backend still runs in this
            # directory; neither a stop nor force can end it from here.
            return jsonify({
                "success": False,
                "error": SimulationRunner.active_run_message(
                    simulation_id, run_state, owner
                ),
            }), 409

        # 智能处理状态：如果准备工作已完成，允许重新启动
        if state.status != SimulationStatus.READY:
            # 检查准备工作是否已完成
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if not is_prepared:
                return jsonify({
                    "success": False,
                    "error": (
                        # e.g. state.json says "stopping" because the run is
                        # still finishing here: say that, not "call /prepare".
                        SimulationRunner.active_run_message(
                            simulation_id, run_state, owner
                        )
                        if owner is not None
                        else t('api.simNotReady', status=state.status.value)
                    ),
                }), 400

        if run_state and run_state.runner_status == RunnerStatus.STARTING:
            # Still STARTING after reconciliation: another request in this
            # server is launching it. Neither stop it nor wipe its logs.
            return jsonify({
                "success": False,
                "error": t('api.simAlreadyActive', id=simulation_id)
            }), 400
        updater = ZepGraphMemoryManager.get_updater(simulation_id)
        needs_finalization = bool(
            run_state
            and run_state.runner_status in {
                RunnerStatus.RUNNING,
                RunnerStatus.PAUSED,
                RunnerStatus.STOPPING,
                RunnerStatus.FAILED,
            }
            and (
                run_state.runner_status
                in {
                    RunnerStatus.RUNNING,
                    RunnerStatus.PAUSED,
                    RunnerStatus.STOPPING,
                }
                or updater is not None
            )
        )
        # A finished run whose simulator this server still keeps open for
        # interviews (its monitor keeps reading the action logs meanwhile).
        env_open = not needs_finalization and owner == "process"
        if owner is not None and not (needs_finalization or env_open):
            # Something here still owns a run that neither a stop nor closing
            # its environment would end (a monitor finishing up, a graph
            # memory drain). Refuse before force wipes anything.
            return jsonify({
                "success": False,
                "error": SimulationRunner.active_run_message(
                    simulation_id, run_state, owner
                ),
            }), 400
        if needs_finalization or env_open:
            if not force:
                return jsonify({
                    "success": False,
                    "error": (
                        t('api.simRunningForceHint')
                        if needs_finalization
                        else SimulationRunner.active_run_message(
                            simulation_id, run_state, owner
                        )
                    ),
                }), 400
            try:
                if needs_finalization:
                    logger.info(f"强制模式：先完成旧模拟终止 {simulation_id}")
                    stopped = SimulationRunner.stop_simulation(simulation_id)
                    if stopped.runner_status != RunnerStatus.STOPPED:
                        return jsonify({
                            "success": False,
                            "error": t('api.simPreviousNotStopped'),
                        }), 409
                else:
                    logger.info(f"强制模式：先结束已完成模拟的采访环境 {simulation_id}")
                    SimulationRunner.close_finished_run(simulation_id)
            except SimulationStopPending as error:
                return jsonify({
                    "success": False,
                    "pending": True,
                    "error": str(error),
                }), 409
            except Exception as error:
                return jsonify({
                    "success": False,
                    "error": t('api.simRestartBlocked', error=str(error)),
                }), 409

        # 如果是强制模式，清理运行日志
        if force:
            logger.info(f"强制模式：清理模拟日志 {simulation_id}")
            cleanup_result = SimulationRunner.cleanup_simulation_logs(simulation_id)
            if not cleanup_result.get("success"):
                return jsonify({
                    "success": False,
                    "error": t(
                        'api.simCleanupFailed',
                        errors="; ".join(cleanup_result.get("errors") or []),
                    ),
                }), 500
            # Report a restart only when a previous run left something to
            # clear; a simulation that never ran has nothing.
            force_restarted = bool(cleanup_result.get("cleaned_files"))

        if state.status != SimulationStatus.READY:
            # 进程不存在或已结束，重置状态为 ready
            logger.info(f"模拟 {simulation_id} 准备工作已完成，重置状态为 ready（原状态: {state.status.value}）")
            state.status = SimulationStatus.READY
            manager._save_simulation_state(state)

        # 获取图谱ID（用于图谱记忆更新）
        graph_id = None
        if enable_graph_memory_update:
            # The project is authoritative. A graph ID copied into an older
            # simulation can outlive a project reset/rebuild and must not be
            # used to resurrect writes to a deleted graph.
            project = ProjectManager.get_project(state.project_id)
            graph_id = project.graph_id if project else None
            if not graph_id:
                return jsonify({
                    "success": False,
                    "error": t('api.graphIdRequiredForMemory')
                }), 400

        graph_guard = (
            graph_lifecycle_lock(graph_id)
            if enable_graph_memory_update
            else nullcontext()
        )
        with graph_guard:
            if enable_graph_memory_update:
                # Re-read both references under the same per-graph lock used
                # by reset/delete. Keep the lock through updater creation in
                # start_simulation so check -> claim is atomic.
                refreshed_state = manager.get_simulation(simulation_id)
                refreshed_project = (
                    ProjectManager.get_project(refreshed_state.project_id)
                    if refreshed_state
                    else None
                )
                current_graph_id = (
                    refreshed_project.graph_id if refreshed_project else None
                )
                if current_graph_id != graph_id:
                    return jsonify({
                        "success": False,
                        "error": (
                            "The project graph changed while the simulation "
                            "was starting; retry after refreshing the project"
                        ),
                    }), 409
                if (
                    refreshed_state.graph_id
                    and refreshed_state.graph_id != current_graph_id
                ):
                    return jsonify({
                        "success": False,
                        "error": (
                            "The simulation references an older graph; "
                            "prepare it again before enabling graph memory"
                        ),
                    }), 409
                active_reports = get_graph_readers(graph_id)
                if active_reports:
                    return jsonify({
                        "success": False,
                        "error": (
                            "A report is currently reading this graph; wait "
                            "for report generation to finish before enabling "
                            "graph memory updates"
                        ),
                        "active_reports": active_reports,
                    }), 409
                state = refreshed_state
                logger.info(
                    "启用图谱记忆更新: simulation_id=%s, graph_id=%s",
                    simulation_id,
                    graph_id,
                )

            # 启动模拟。启用图谱写入时仍持有 graph_guard，直到 updater
            # claim 与进程资源全部发布完成。
            run_state = SimulationRunner.start_simulation(
                simulation_id=simulation_id,
                platform=platform,
                max_rounds=max_rounds,
                enable_graph_memory_update=enable_graph_memory_update,
                graph_id=graph_id
            )
        
        response_data = run_state.to_dict()
        if max_rounds:
            response_data['max_rounds_applied'] = max_rounds
        response_data['graph_memory_update_enabled'] = enable_graph_memory_update
        response_data['force_restarted'] = force_restarted
        if enable_graph_memory_update:
            response_data['graph_id'] = graph_id
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"启动模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    停止模拟
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx"  // 必填，模拟ID
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "stopped",
                "completed_at": "2025-12-01T12:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        run_state = SimulationRunner.stop_simulation(simulation_id)
        
        # 更新模拟状态
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.STOPPED
            state.error = None
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })

    except SimulationStopPending as e:
        return jsonify({
            "success": False,
            "pending": True,
            "error": str(e),
        }), 202

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"停止模拟失败: {str(e)}")
        simulation_id = (request.get_json(silent=True) or {}).get('simulation_id')
        if simulation_id:
            manager = SimulationManager()
            state = manager.get_simulation(simulation_id)
            if state:
                state.status = SimulationStatus.FAILED
                state.error = str(e)
                manager._save_simulation_state(state)
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 实时状态监控接口 ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    获取模拟运行实时状态（用于前端轮询）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                "total_rounds": 144,
                "progress_percent": 3.5,
                "simulated_hours": 2,
                "total_simulation_hours": 72,
                "twitter_running": true,
                "reddit_running": true,
                "twitter_actions_count": 150,
                "reddit_actions_count": 200,
                "total_actions_count": 350,
                "started_at": "2025-12-01T10:00:00",
                "updated_at": "2025-12-01T10:30:00"
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "current_round": 0,
                    "total_rounds": 0,
                    "progress_percent": 0,
                    "twitter_actions_count": 0,
                    "reddit_actions_count": 0,
                    "total_actions_count": 0,
                }
            })
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取运行状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    获取模拟运行详细状态（包含所有动作）
    
    用于前端展示实时动态
    
    Query参数：
        platform: 过滤平台（twitter/reddit，可选）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                ...
                "all_actions": [
                    {
                        "round_num": 5,
                        "timestamp": "2025-12-01T10:30:00",
                        "platform": "twitter",
                        "agent_id": 3,
                        "agent_name": "Agent Name",
                        "action_type": "CREATE_POST",
                        "action_args": {"content": "..."},
                        "result": null,
                        "success": true
                    },
                    ...
                ],
                "twitter_actions": [...],  # Twitter 平台的所有动作
                "reddit_actions": [...]    # Reddit 平台的所有动作
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        platform_filter = request.args.get('platform')
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "all_actions": [],
                    "twitter_actions": [],
                    "reddit_actions": []
                }
            })
        
        # 获取完整的动作列表
        all_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter
        )
        
        # 分平台获取动作
        twitter_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="twitter"
        ) if not platform_filter or platform_filter == "twitter" else []
        
        reddit_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform="reddit"
        ) if not platform_filter or platform_filter == "reddit" else []
        
        # 获取当前轮次的动作（recent_actions 只展示最新一轮）
        current_round = run_state.current_round
        recent_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter,
            round_num=current_round
        ) if current_round > 0 else []
        
        # 获取基础状态信息
        result = run_state.to_dict()
        result["all_actions"] = [a.to_dict() for a in all_actions]
        result["twitter_actions"] = [a.to_dict() for a in twitter_actions]
        result["reddit_actions"] = [a.to_dict() for a in reddit_actions]
        result["rounds_count"] = len(run_state.rounds)
        # recent_actions 只展示当前最新一轮两个平台的内容
        result["recent_actions"] = [a.to_dict() for a in recent_actions]
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取详细状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    获取模拟中的Agent动作历史
    
    Query参数：
        limit: 返回数量（默认100）
        offset: 偏移量（默认0）
        platform: 过滤平台（twitter/reddit）
        agent_id: 过滤Agent ID
        round_num: 过滤轮次
    
    返回：
        {
            "success": true,
            "data": {
                "count": 100,
                "actions": [...]
            }
        }
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id', type=int)
        round_num = request.args.get('round_num', type=int)
        
        actions = SimulationRunner.get_actions(
            simulation_id=simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(actions),
                "actions": [a.to_dict() for a in actions]
            }
        })
        
    except Exception as e:
        logger.error(f"获取动作历史失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    获取模拟时间线（按轮次汇总）
    
    用于前端展示进度条和时间线视图
    
    Query参数：
        start_round: 起始轮次（默认0）
        end_round: 结束轮次（默认全部）
    
    返回每轮的汇总信息
    """
    try:
        start_round = request.args.get('start_round', 0, type=int)
        end_round = request.args.get('end_round', type=int)
        
        timeline = SimulationRunner.get_timeline(
            simulation_id=simulation_id,
            start_round=start_round,
            end_round=end_round
        )
        
        return jsonify({
            "success": True,
            "data": {
                "rounds_count": len(timeline),
                "timeline": timeline
            }
        })
        
    except Exception as e:
        logger.error(f"获取时间线失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    获取每个Agent的统计信息
    
    用于前端展示Agent活跃度排行、动作分布等
    """
    try:
        stats = SimulationRunner.get_agent_stats(simulation_id)
        
        return jsonify({
            "success": True,
            "data": {
                "agents_count": len(stats),
                "stats": stats
            }
        })
        
    except Exception as e:
        logger.error(f"获取Agent统计失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 数据库查询接口 ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    获取模拟中的帖子
    
    Query参数：
        platform: 平台类型（twitter/reddit）
        limit: 返回数量（默认50）
        offset: 偏移量
    
    返回帖子列表（从SQLite数据库读取）
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = (
            os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id) if Config.DATA_DIR
            else os.path.join(
                os.path.dirname(__file__),
                f'../../uploads/simulations/{simulation_id}'
            )
        )

        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "posts": [],
                    "message": t('api.dbNotExist')
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM post 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            posts = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT COUNT(*) FROM post")
            total = cursor.fetchone()[0]
            
        except sqlite3.OperationalError:
            posts = []
            total = 0
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "total": total,
                "count": len(posts),
                "posts": posts
            }
        })
        
    except Exception as e:
        logger.error(f"获取帖子失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    获取模拟中的评论

    Query参数：
        platform: 平台类型（twitter/reddit，根据模拟配置自动选择）
        post_id: 过滤帖子ID（可选）
        limit: 返回数量
        offset: 偏移量
    """
    try:
        platform = request.args.get('platform') or _get_default_platform(simulation_id)
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        sim_dir = (
            os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id) if Config.DATA_DIR
            else os.path.join(
                os.path.dirname(__file__),
                f'../../uploads/simulations/{simulation_id}'
            )
        )
        
        db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "count": 0,
                    "comments": []
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if post_id:
                cursor.execute("""
                    SELECT * FROM comment 
                    WHERE post_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (post_id, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM comment 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            comments = [dict(row) for row in cursor.fetchall()]
            
        except sqlite3.OperationalError:
            comments = []
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(comments),
                "comments": comments
            }
        })
        
    except Exception as e:
        logger.error(f"获取评论失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interview 采访接口 ==============
#
# Live answers need the run's environment (check_env_alive). Once the square
# has closed, the three interview routes answer from each citizen's record
# instead (services/symposium_memory.py): the same JSON shape, marked
# from_memory, with every error body in the city's words and marked too.


def _memory_error(key, status, **kwargs):
    return jsonify(symposium_memory.error_body(t(key, **kwargs))), status


def _memory_request(data):
    """(lang, report_id) of a memory answer: used only when they are non-empty text."""

    lang = data.get('lang') if isinstance(data.get('lang'), str) and data.get('lang').strip() else None
    report_id = data.get('report_id')
    report_id = report_id if isinstance(report_id, str) and report_id.strip() else None
    return lang, report_id


def _memory_ask(item):
    """(agent_id, question, history) of one ask, or (None, error response)."""

    agent_id = citizen_portraits._agent_id(item.get('agent_id')) if isinstance(item, dict) else None
    if agent_id is None:
        return None, _memory_error('api.memory.needCitizen', 400)
    prompt = item.get('prompt')
    if prompt is None:
        prompt = ''
    if not isinstance(prompt, str):
        return None, _memory_error('api.memory.needQuestion', 400)
    if len(prompt) > symposium_memory.MAX_PROMPT_INPUT:
        return None, _memory_error('api.memory.tooLong', 400)
    question = item.get('question')
    if question is not None:
        if not isinstance(question, str) or not question.strip():
            return None, _memory_error('api.memory.needQuestion', 400)
        if len(question) > symposium_memory.MAX_QUESTION_INPUT:
            return None, _memory_error('api.memory.tooLong', 400)
    try:
        history = symposium_memory.clean_history(item.get('history'))
    except ValueError:
        return None, _memory_error('api.memory.badHistory', 400)
    asked, told = symposium_memory.split_conversation(prompt)
    question = question.strip() if question is not None else asked
    if not question:
        return None, _memory_error('api.memory.needQuestion', 400)
    if not history:
        history = told
    return (agent_id, question, history), None


def _memory_failed(route, error):
    logger.error('Answering from memory (%s) failed: type=%s', route, type(error).__name__)
    return _memory_error('api.memory.failed', 500)


def _answer_from_memory_single(data, simulation_id, platform):
    """/interview once the square has closed: one citizen answers from the record."""

    try:
        ask, failure = _memory_ask(data)
        if failure:
            return failure
        if citizen_portraits.find_simulation(simulation_id) is None:
            return _memory_error('api.memory.notFound', 404)
        lang, report_id = _memory_request(data)
        outcome = symposium_memory.answer_citizens(
            simulation_id, [ask], kind='single', lang=lang, platform=platform,
            deadline_seconds=symposium_memory.deadline(data.get('timeout'), 'single'), report_id=report_id,
        )
        body, status = symposium_memory.single_payload(outcome, data.get('prompt'), platform)
        return jsonify(body), status
    except symposium_memory.GatheringNotFound:
        return _memory_error('api.memory.notFound', 404)
    except Exception as error:  # noqa: BLE001 - never str(e) or a traceback
        return _memory_failed('single', error)


def _answer_from_memory_batch(data, simulation_id, interviews, platform):
    """/interview/batch once the square has closed: each citizen answers from the record."""

    try:
        asks = []
        item_platforms = {}
        for item in interviews:
            ask, failure = _memory_ask(item)
            if failure:
                return failure
            asks.append(ask)
            if item.get('platform'):
                item_platforms.setdefault(ask[0], item.get('platform'))
        distinct = len({ask[0] for ask in asks})
        if distinct > symposium_memory.MAX_MEMORY_CROWD:
            return _memory_error('api.memory.tooMany', 400, n=symposium_memory.MAX_MEMORY_CROWD)
        if citizen_portraits.find_simulation(simulation_id) is None:
            return _memory_error('api.memory.notFound', 404)
        lang, report_id = _memory_request(data)
        # The page asks one citizen at their couch through this route: that is one answer's wait.
        wait_kind = 'single' if distinct == 1 else 'batch'
        outcome = symposium_memory.answer_citizens(
            simulation_id, asks, kind='batch', lang=lang, platform=platform,
            deadline_seconds=symposium_memory.deadline(data.get('timeout'), wait_kind), report_id=report_id,
        )
        body, status = symposium_memory.batch_payload(
            outcome, distinct, symposium_memory.message, item_platforms,
        )
        return jsonify(body), status
    except symposium_memory.GatheringNotFound:
        return _memory_error('api.memory.notFound', 404)
    except Exception as error:  # noqa: BLE001 - never str(e) or a traceback
        return _memory_failed('batch', error)


def _answer_from_memory_all(data, simulation_id, prompt, platform):
    """/interview/all once the square has closed: every citizen answers the one question."""

    try:
        if not isinstance(prompt, str):
            return _memory_error('api.memory.needQuestion', 400)
        if len(prompt) > symposium_memory.MAX_PROMPT_INPUT:
            return _memory_error('api.memory.tooLong', 400)
        question, history = symposium_memory.split_conversation(prompt)
        if not question:
            return _memory_error('api.memory.needQuestion', 400)
        if citizen_portraits.find_simulation(simulation_id) is None:
            return _memory_error('api.memory.notFound', 404)
        ids = symposium_memory.citizen_ids(simulation_id)
        lang, report_id = _memory_request(data)
        outcome = symposium_memory.answer_citizens(
            simulation_id, [(agent_id, question, history) for agent_id in ids], kind='all', lang=lang,
            platform=platform, deadline_seconds=symposium_memory.deadline(data.get('timeout'), 'all'),
            report_id=report_id,
        )
        body, status = symposium_memory.batch_payload(outcome, len(ids), symposium_memory.message)
        return jsonify(body), status
    except symposium_memory.GatheringNotFound:
        return _memory_error('api.memory.notFound', 404)
    except Exception as error:  # noqa: BLE001 - never str(e) or a traceback
        return _memory_failed('all', error)


@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    采访单个Agent

    注意：此功能需要模拟环境处于运行状态（完成模拟循环后进入等待命令模式）
    Once the environment has closed, the citizen answers from the record
    (services/symposium_memory.py): the same shape plus from_memory: true.
    Memory-only fields: "question" (the bare question), "history" ([{role,
    content}]), "lang" and "report_id"; the live run never sees them. Every
    memory error body is {success: false, error, from_memory: true}.

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",       // 必填，模拟ID
            "agent_id": 0,                     // 必填，Agent ID
            "prompt": "你对这件事有什么看法？",  // 必填，采访问题
            "platform": "twitter",             // 可选，指定平台（twitter/reddit）
                                               // 不指定时：双平台模拟同时采访两个平台
            "timeout": 60                      // 可选，超时时间（秒），默认60
        }

    返回（不指定platform，双平台模式）：
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "你对这件事有什么看法？",
                "result": {
                    "agent_id": 0,
                    "prompt": "...",
                    "platforms": {
                        "twitter": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit": {"agent_id": 0, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }

    返回（指定platform）：
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "你对这件事有什么看法？",
                "result": {
                    "agent_id": 0,
                    "response": "我认为...",
                    "platform": "twitter",
                    "timestamp": "2025-12-08T10:00:00"
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        agent_id = data.get('agent_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 60)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        if agent_id is None:
            return jsonify({
                "success": False,
                "error": t('api.requireAgentId')
            }), 400
        
        if not prompt:
            return jsonify({
                "success": False,
                "error": t('api.requirePrompt')
            }), 400
        
        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400
        
        # Ids that can never be gatherings (this also closes the path join below).
        if not citizen_portraits.valid_simulation_id(simulation_id):
            return _memory_error('api.memory.notFound', 404)

        # 检查环境状态: once the square has closed, the citizen answers from the record.
        if not SimulationRunner.check_env_alive(simulation_id):
            return _answer_from_memory_single(data, simulation_id, platform)
        
        # 优化prompt，添加前缀避免Agent调用工具 (in the visitor's language)
        lang = _viewer_lang(data)
        optimized_prompt = optimize_interview_prompt(prompt, lang)
        
        result = SimulationRunner.interview_agent(
            simulation_id=simulation_id,
            agent_id=agent_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": _live_answers_in(result, lang)
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": _live_error(e, _viewer_lang(data))
        }), 400
        
    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": _live_timeout('api.interviewTimeout', data, 60, e)
        }), 504
        
    except Exception as e:
        logger.error(f"Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    批量采访多个Agent

    注意：此功能需要模拟环境处于运行状态
    Once the environment has closed, each citizen answers from the record:
    results["<platform>_<id>"] = {agent_id, response, platform, from_memory:
    true, timestamp, error?}, plus result.unanswered (the ids without an
    answer). Items may carry "question" and "history"; the top level may carry
    "lang" and "report_id". The live run receives neither question nor history.

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",       // 必填，模拟ID
            "interviews": [                    // 必填，采访列表
                {
                    "agent_id": 0,
                    "prompt": "你对A有什么看法？",
                    "platform": "twitter"      // 可选，指定该Agent的采访平台
                },
                {
                    "agent_id": 1,
                    "prompt": "你对B有什么看法？"  // 不指定platform则使用默认值
                }
            ],
            "platform": "reddit",              // 可选，默认平台（被每项的platform覆盖）
                                               // 不指定时：双平台模拟每个Agent同时采访两个平台
            "timeout": 120                     // 可选，超时时间（秒），默认120
        }

    返回：
        {
            "success": true,
            "data": {
                "interviews_count": 2,
                "result": {
                    "interviews_count": 4,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        "twitter_1": {"agent_id": 1, "response": "...", "platform": "twitter"},
                        "reddit_1": {"agent_id": 1, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        interviews = data.get('interviews')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": t('api.requireInterviews')
            }), 400

        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400

        # 验证每个采访项
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListMissingAgentId', index=i+1)
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListMissingPrompt', index=i+1)
                }), 400
            # 验证每项的platform（如果有）
            item_platform = interview.get('platform')
            if item_platform and item_platform not in ("twitter", "reddit"):
                return jsonify({
                    "success": False,
                    "error": t('api.interviewListInvalidPlatform', index=i+1)
                }), 400

        # Ids that can never be gatherings (this also closes the path join below).
        if not citizen_portraits.valid_simulation_id(simulation_id):
            return _memory_error('api.memory.notFound', 404)

        # 检查环境状态: once the square has closed, the citizens answer from the record.
        if not SimulationRunner.check_env_alive(simulation_id):
            return _answer_from_memory_batch(data, simulation_id, interviews, platform)

        # 优化每个采访项的prompt，添加前缀避免Agent调用工具 (in the visitor's language)
        # (question and history are for memory answers only: the live run never sees them)
        lang = _viewer_lang(data)
        optimized_interviews = []
        for interview in interviews:
            optimized_interview = {
                key: value for key, value in interview.items()
                if key not in symposium_memory.MEMORY_ONLY_KEYS
            }
            optimized_interview['prompt'] = optimize_interview_prompt(interview.get('prompt', ''), lang)
            optimized_interviews.append(optimized_interview)

        result = SimulationRunner.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=optimized_interviews,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": _live_answers_in(result, lang)
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": _live_error(e, _viewer_lang(data))
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": _live_timeout('api.batchInterviewTimeout', data, 120, e)
        }), 504

    except Exception as e:
        logger.error(f"批量Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    全局采访 - 使用相同问题采访所有Agent

    注意：此功能需要模拟环境处于运行状态
    Once the environment has closed, every citizen (at most 60) answers from
    the record, in the batch route's memory shape.

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",            // 必填，模拟ID
            "prompt": "你对这件事整体有什么看法？",  // 必填，采访问题（所有Agent使用相同问题）
            "platform": "reddit",                   // 可选，指定平台（twitter/reddit）
                                                    // 不指定时：双平台模拟每个Agent同时采访两个平台
            "timeout": 180                          // 可选，超时时间（秒），默认180
        }

    返回：
        {
            "success": true,
            "data": {
                "interviews_count": 50,
                "result": {
                    "interviews_count": 100,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        ...
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 180)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": t('api.requirePrompt')
            }), 400

        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": t('api.invalidInterviewPlatform')
            }), 400

        # Ids that can never be gatherings (this also closes the path join below).
        if not citizen_portraits.valid_simulation_id(simulation_id):
            return _memory_error('api.memory.notFound', 404)

        # 检查环境状态: once the square has closed, every citizen answers from the record.
        if not SimulationRunner.check_env_alive(simulation_id):
            return _answer_from_memory_all(data, simulation_id, prompt, platform)

        # 优化prompt，添加前缀避免Agent调用工具 (in the visitor's language)
        lang = _viewer_lang(data)
        optimized_prompt = optimize_interview_prompt(prompt, lang)

        result = SimulationRunner.interview_all_agents(
            simulation_id=simulation_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": _live_answers_in(result, lang)
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": _live_error(e, _viewer_lang(data))
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": _live_timeout('api.globalInterviewTimeout', data, 180, e)
        }), 504

    except Exception as e:
        logger.error(f"全局Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    获取Interview历史记录

    从模拟数据库中读取所有Interview记录

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",  // 必填，模拟ID
            "platform": "reddit",          // 可选，平台类型（reddit/twitter）
                                           // 不指定则返回两个平台的所有历史
            "agent_id": 0,                 // 可选，只获取该Agent的采访历史
            "limit": 100                   // 可选，返回数量，默认100
        }

    返回：
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "我认为...",
                        "prompt": "你对这件事有什么看法？",
                        "timestamp": "2025-12-08T10:00:00",
                        "platform": "reddit"
                    },
                    ...
                ]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        platform = data.get('platform')  # 不指定则返回两个平台的历史
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        history = SimulationRunner.get_interview_history(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            "data": {
                "count": len(history),
                "history": _history_in(history, _viewer_lang(data))
            }
        })

    except Exception as e:
        logger.error(f"获取Interview历史失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    获取模拟环境状态

    检查模拟环境是否存活（可以接收Interview命令）

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx"  // 必填，模拟ID
        }

    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "环境正在运行，可以接收Interview命令",
                "answers_from_memory": true   // the citizens can answer from the record when it is closed
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        env_alive = SimulationRunner.check_env_alive(simulation_id)
        
        # 获取更详细的状态信息
        env_status = SimulationRunner.get_env_status_detail(simulation_id)

        if env_alive:
            message = t('api.envRunning')
        else:
            message = t('api.envNotRunningShort')

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "env_alive": env_alive,
                "twitter_available": env_status.get("twitter_available", False),
                "reddit_available": env_status.get("reddit_available", False),
                "message": message,
                # The citizens can answer from the record once the square has closed.
                "answers_from_memory": bool(Config.LLM_API_KEY),
            }
        })

    except Exception as e:
        logger.error(f"获取环境状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    关闭模拟环境
    
    向模拟发送关闭环境命令，使其优雅退出等待命令模式。
    
    注意：这不同于 /stop 接口，/stop 会强制终止进程，
    而此接口会让模拟优雅地关闭环境并退出。
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",  // 必填，模拟ID
            "timeout": 30                  // 可选，超时时间（秒），默认30
        }
    
    返回：
        {
            "success": true,
            "data": {
                "message": "环境关闭命令已发送",
                "result": {...},
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        timeout = data.get('timeout', 30)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400
        
        result = SimulationRunner.close_simulation_env(
            simulation_id=simulation_id,
            timeout=timeout
        )
        
        # 更新模拟状态
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.COMPLETED
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": result.get("success", False),
            "data": result
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"关闭环境失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
