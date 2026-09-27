"""\n配置管理\n统一从项目根目录的 .env 文件加载配置\n"""

import logging
import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


_config_logger = logging.getLogger('mirofish.config')


def _env_str(name: str, default: str) -> str:
    """Read a string setting; blank values fall back to the default."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    """Read an int setting; invalid or out-of-range values log a warning and use the default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        _config_logger.warning("%s is not an integer; using the default %s", name, default)
        return default
    if minimum is not None and value < minimum:
        _config_logger.warning("%s must be at least %s; using the default %s", name, minimum, default)
        return default
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    """Read a float setting; invalid or out-of-range values log a warning and use the default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        _config_logger.warning("%s is not a number; using the default %s", name, default)
        return default
    if value != value or value in (float('inf'), float('-inf')):
        _config_logger.warning("%s must be finite; using the default %s", name, default)
        return default
    if minimum is not None and value < minimum:
        _config_logger.warning("%s must be at least %s; using the default %s", name, minimum, default)
        return default
    return value


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    # PARTHENON_DATA_DIR (the public deployment's persistent disk, e.g. /data)
    # moves everything the city keeps to <data dir>/uploads: projects,
    # simulations, reports, voices and the local memory database. Unset, the
    # paths are the ones the owner's machine has always used.
    DATA_DIR = _env_str('PARTHENON_DATA_DIR', '')
    UPLOAD_FOLDER = (
        os.path.join(os.path.abspath(DATA_DIR), 'uploads') if DATA_DIR
        else os.path.join(os.path.dirname(__file__), '../uploads')
    )
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = (
        os.path.join(UPLOAD_FOLDER, 'simulations') if DATA_DIR
        else os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    )
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    # Memory backend: 'auto' (local unless a usable ZEP_API_KEY is set),
    # 'local' (SQLite store in this process) or 'zep' (Zep Cloud).
    MEMORY_BACKEND = _env_str('MEMORY_BACKEND', 'auto').lower()

    # Local memory backend (app/memory). Defaults match the local-memory spec.
    LOCAL_MEMORY_DB_PATH = _env_str(
        'LOCAL_MEMORY_DB_PATH',
        os.path.normpath(os.path.join(UPLOAD_FOLDER, 'memory', 'local_memory.sqlite3')),
    )
    LOCAL_MEMORY_LLM_MODEL = _env_str('LOCAL_MEMORY_LLM_MODEL', '')
    LOCAL_MEMORY_LLM_CONCURRENCY = _env_int('LOCAL_MEMORY_LLM_CONCURRENCY', 2, minimum=1)
    LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS = _env_float(
        'LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS', 0.0, minimum=0.0
    )
    LOCAL_MEMORY_LLM_MAX_ATTEMPTS = _env_int('LOCAL_MEMORY_LLM_MAX_ATTEMPTS', 3, minimum=1)
    LOCAL_MEMORY_LLM_MAX_TOKENS = _env_int('LOCAL_MEMORY_LLM_MAX_TOKENS', 4096, minimum=1)
    LOCAL_MEMORY_WINDOW_CHARS = _env_int('LOCAL_MEMORY_WINDOW_CHARS', 4000, minimum=1)
    LOCAL_MEMORY_MAX_ENTITIES_PER_WINDOW = _env_int(
        'LOCAL_MEMORY_MAX_ENTITIES_PER_WINDOW', 30, minimum=1
    )
    LOCAL_MEMORY_MAX_RELATIONS_PER_WINDOW = _env_int(
        'LOCAL_MEMORY_MAX_RELATIONS_PER_WINDOW', 50, minimum=1
    )
    LOCAL_MEMORY_PROMPT_KNOWN_ENTITIES = _env_int('LOCAL_MEMORY_PROMPT_KNOWN_ENTITIES', 60, minimum=0)
    LOCAL_MEMORY_PROMPT_EXISTING_FACTS = _env_int('LOCAL_MEMORY_PROMPT_EXISTING_FACTS', 30, minimum=0)
    LOCAL_MEMORY_MAX_FAILED_FRACTION = _env_float(
        'LOCAL_MEMORY_MAX_FAILED_FRACTION', 0.5, minimum=0.0
    )
    LOCAL_MEMORY_DEDUP_PASS = _env_str('LOCAL_MEMORY_DEDUP_PASS', 'llm').lower()
    LOCAL_MEMORY_INGESTION_TIMEOUT_SECONDS = _env_float(
        'LOCAL_MEMORY_INGESTION_TIMEOUT_SECONDS', 1800.0, minimum=1.0
    )
    LOCAL_MEMORY_LEASE_SECONDS = _env_float('LOCAL_MEMORY_LEASE_SECONDS', 180.0, minimum=1.0)
    LOCAL_MEMORY_ACTIVITY_MODE = _env_str('LOCAL_MEMORY_ACTIVITY_MODE', 'rules').lower()
    LOCAL_MEMORY_ACTIVITY_GROUP_SIZE = _env_int('LOCAL_MEMORY_ACTIVITY_GROUP_SIZE', 8, minimum=1)
    LOCAL_MEMORY_ACTIVITY_GROUP_CHARS = _env_int('LOCAL_MEMORY_ACTIVITY_GROUP_CHARS', 12000, minimum=1)
    LOCAL_MEMORY_ACTIVITY_GROUP_WAIT_SECONDS = _env_float(
        'LOCAL_MEMORY_ACTIVITY_GROUP_WAIT_SECONDS', 15.0, minimum=0.0
    )
    LOCAL_MEMORY_ACTIVITY_MAX_PENDING_SECONDS = _env_float(
        'LOCAL_MEMORY_ACTIVITY_MAX_PENDING_SECONDS', 300.0, minimum=0.0
    )
    LOCAL_MEMORY_ACTIVITY_MAX_LLM_CALLS = _env_int('LOCAL_MEMORY_ACTIVITY_MAX_LLM_CALLS', 60, minimum=0)
    LOCAL_MEMORY_SUMMARY_MAX_CHARS = _env_int('LOCAL_MEMORY_SUMMARY_MAX_CHARS', 800, minimum=1)
    LOCAL_MEMORY_SEARCH_INVALID_PENALTY = _env_float(
        'LOCAL_MEMORY_SEARCH_INVALID_PENALTY', 0.7, minimum=0.0
    )

    PLACEHOLDER_MARKERS = ('PASTE_YOUR', 'your_api_key', 'your_zep_api_key')

    @classmethod
    def is_placeholder(cls, value) -> bool:
        """True for unset values and the example placeholders shipped in .env."""
        return not value or any(marker.lower() in value.lower() for marker in cls.PLACEHOLDER_MARKERS)

    @classmethod
    def memory_backend(cls, api_key: str | None = None) -> str:
        """Return 'local' or 'zep'.

        Reads the class attributes at call time, so tests can monkeypatch them.
        In 'auto' mode an explicit usable ``api_key`` selects Zep Cloud.
        """
        mode = (cls.MEMORY_BACKEND or 'auto').strip().lower()
        if mode in ('local', 'zep'):
            return mode
        if mode != 'auto':
            raise ValueError('MEMORY_BACKEND must be auto, local or zep')
        key = (api_key or cls.ZEP_API_KEY or '').strip()
        return 'zep' if key and not cls.is_placeholder(key) else 'local'

    @classmethod
    def memory_backend_mode(cls) -> str:
        """The configured MEMORY_BACKEND value, normalized (may be invalid)."""
        return (cls.MEMORY_BACKEND or 'auto').strip().lower()

    @classmethod
    def warnings(cls) -> list[str]:
        """Settings that let the server start but will make runs fail later."""
        found: list[str] = []
        mode = cls.memory_backend_mode()
        if mode == 'zep' and cls.is_placeholder(cls.ZEP_API_KEY):
            found.append(
                "ZEP_API_KEY is still a placeholder: graph builds will fail until you add "
                "a key from https://app.getzep.com to .env and restart."
            )
        elif mode == 'auto' and cls.memory_backend() == 'local':
            found.append(
                f"No usable ZEP_API_KEY: using the local memory backend ({cls.LOCAL_MEMORY_DB_PATH}). "
                "Set MEMORY_BACKEND=zep to require Zep Cloud."
            )
        if cls.is_placeholder(cls.LLM_API_KEY):
            found.append("LLM_API_KEY is still a placeholder: LLM calls will fail.")
        return found

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        mode = cls.memory_backend_mode()
        if mode not in ('auto', 'local', 'zep'):
            errors.append("MEMORY_BACKEND must be auto, local or zep")
        else:
            if mode == 'zep' and not cls.ZEP_API_KEY:
                errors.append("ZEP_API_KEY 未配置")
            if os.environ.get("ZEP_API_URL") and cls.memory_backend() == 'zep':
                errors.append("ZEP_API_URL 不受支持；MiroFish 仅连接 Zep Cloud")
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        return errors
