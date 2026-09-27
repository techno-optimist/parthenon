"""
MiroFish Backend - Flask应用工厂
"""

import os
import re
import warnings
from urllib.parse import urlsplit

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

from .config import Config
from .public import configure as configure_public, load_settings as load_public_settings
from .utils.logger import setup_logger, get_logger


# Browser pages served from this machine (any port, since Vite moves off 3000
# when it is busy) may call /api/*. The backend spends the Grok subscription
# and OpenRouter quota through the bridge, so other web pages must not.
# PARTHENON_CORS_ORIGINS adds comma separated origins, e.g. for a LAN setup;
# "*" turns the origin and Host checks off.
LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}
LOOPBACK_ORIGIN = re.compile(
    r'^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$', re.IGNORECASE
)

# Per-endpoint body caps below the app-wide MAX_CONTENT_LENGTH (sized for
# uploads). A valid Oracle stage is well under 100 KB.
BODY_LIMITS = {
    'parthenon.draft_stage': (256 * 1024, 'The stage is too large.'),
    'parthenon.start_chronicle_film': (16 * 1024, 'The film request is too large.'),
}


def _hostname(value):
    try:
        return (urlsplit('//' + value).hostname or '').lower()
    except ValueError:
        return ''


def _json_error(message, status):
    return jsonify({'success': False, 'error': message}), status


def _resume_local_memory(logger):
    try:
        backend = Config.memory_backend()
    except ValueError:
        return  # Config.validate() reports the invalid MEMORY_BACKEND
    if backend != 'local':
        return
    from .memory import start_local_memory_in_background

    start_local_memory_in_background()
    logger.info("Local memory backend: resuming queued work in the background")


def _reconcile_interrupted_runs(logger, runner):
    try:
        reconciled = runner.reconcile_orphaned_runs()
    except Exception as error:
        logger.error("Could not reconcile interrupted simulation runs: %s", error)
        return
    if reconciled:
        logger.warning(
            "Marked %d interrupted simulation run(s) as stopped: %s",
            len(reconciled),
            ", ".join(reconciled),
        )


def _reconcile_interrupted_preparations(logger):
    # The public steps only: a preparation lives in a thread of the process
    # that began it, so one a stop or a deploy cut short would read
    # 'preparing' forever (the owner's own machine keeps its old behaviour).
    from .services.simulation_manager import SimulationManager, live_preparation_task

    try:
        marked = SimulationManager().reconcile_interrupted_preparations(
            is_live=lambda simulation_id: live_preparation_task(simulation_id) is not None,
        )
    except Exception as error:
        logger.error("Could not reconcile interrupted preparations: %s", error)
        return
    if marked:
        logger.warning(
            "Marked %d interrupted preparation(s) as failed: %s",
            len(marked),
            ", ".join(marked),
        )


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # 启用CORS（仅限本机页面，见 LOOPBACK_ORIGIN）
    extra_origins = [
        origin.strip().rstrip('/')
        for origin in os.environ.get('PARTHENON_CORS_ORIGINS', '').split(',')
        if origin.strip()
    ]
    # The public steps (PARTHENON_PUBLIC=1, see app/public) sit behind the
    # site's edge on a private network: pages from the public origin may call
    # the API, and the Host is whatever the edge asked for.
    public_settings = load_public_settings()
    if public_settings.public:
        extra_origins.extend(
            origin for origin in public_settings.public_origins if origin not in extra_origins
        )
    allow_any_origin = '*' in extra_origins
    allowed_origins = {origin.casefold() for origin in extra_origins}
    allowed_hosts = LOOPBACK_HOSTS | {
        host for host in (
            _hostname(origin.split('://', 1)[-1]) for origin in extra_origins
        ) if host
    }
    check_host = not public_settings.public
    CORS(app, resources={r"/api/*": {
        "origins": "*" if allow_any_origin else [LOOPBACK_ORIGIN, *extra_origins],
    }})

    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")
        # A backend that died before that cleanup ran leaves runs marked
        # active with nothing left to finish them; they would block restarts,
        # reports and graph deletion. Same reloader-safe condition as above.
        _reconcile_interrupted_runs(logger, SimulationRunner)
        if public_settings.public:
            _reconcile_interrupted_preparations(logger)

    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        # Never log bodies: they carry seed documents and Oracle stages.
        logger.debug(
            "请求: %s %s (%s bytes)",
            request.method, request.path, request.content_length or 0,
        )

    @app.before_request
    def guard_request():
        # Browsers always send Origin on cross-site POSTs, so this also stops
        # simple form posts that CORS alone would let through unread. The
        # Host check blocks DNS rebinding, as the bridge does.
        if not allow_any_origin:
            origin = request.headers.get('Origin')
            if origin and not (
                LOOPBACK_ORIGIN.match(origin)
                or origin.rstrip('/').casefold() in allowed_origins
            ):
                return _json_error('Requests from this web page are not accepted.', 403)
            if check_host and _hostname(request.host) not in allowed_hosts:
                return _json_error('This backend only serves localhost.', 403)

        limit, too_large = BODY_LIMITS.get(
            request.endpoint, (None, 'The request body is too large.')
        )
        if limit:
            if (request.content_length or 0) > limit:
                return _json_error(too_large, 413)
            request.max_content_length = limit  # also caps chunked bodies

        if request.is_json:
            try:
                # Parse once here (Flask caches it for the view) so a deeply
                # nested or oversized body gets a JSON error, not an HTML page.
                request.get_json(silent=True)
            except RecursionError:
                return _json_error('The JSON body is nested too deeply.', 400)
            except RequestEntityTooLarge:
                return _json_error(too_large, 413)

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp, parthenon_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(parthenon_bp, url_prefix='/api/parthenon')
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    # Public mode: limits, owner keys and the keepers' routes (app/public).
    if configure_public(app, public_settings) is not None and should_log_startup:
        logger.info("Public mode: the steps are open (PARTHENON_PUBLIC=1)")

    # Local memory backend: open the store now so work interrupted by a
    # restart (queued or leased extraction, unfinished batches) resumes
    # without waiting for a request. Same reloader-safe condition as the
    # startup logs, so the Werkzeug reloader parent never runs a worker.
    if should_log_startup:
        _resume_local_memory(logger)

    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

