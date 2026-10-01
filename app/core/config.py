import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping

# 根目录由 app.core.paths 统一解析，不由本文件的位置推断。
# 本文件因此放在任何位置，解析结果都不变。
from app.core.paths import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT


# 「活动 env 文件」——读与写必须是同一个，由 _load_dotenv() 在导入期确定。
# 有覆盖层 `.env.<APP_ENV>` 时是覆盖层，否则是基础层 `.env`。
# `_write_env_updates()` 与配置快照都依赖它：运行期的研究配置持久化会**就地改写
# 这个文件**（server.py 的 /api/research-runtime 配置接口），读写分家就会写错文件。
ACTIVE_ENV_FILE: "Path | None" = None


def _read_env_file(path: Path) -> list[tuple[str, str]]:
    """读一个 env 文件，返回 `[(键, 值)]`。

    文件不存在或读不动时返回空列表，**不抛异常**——调用方靠"这一层是空的"来判断
    该层是否存在（覆盖层不存在时继续走基础层，这是正常情形而非错误）。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    pairs: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs.append((key.strip(), value.strip().strip('"').strip("'")))
    return pairs


def _apply_env_file(path: Path, environ: MutableMapping[str, str]) -> int:
    """把文件里的键按 `setdefault` 语义写进 `environ`，返回本次新写入的条数。

    **已存在的环境变量一律优先**——这是本仓库既有语义，本步特意不动它：
    根目录 `conftest.py` 的测试隔离闸门正是靠这条，先显式赋值 `DB_*` /
    `DATABASE_URL` 再导入 config，从而挡住生产库。改成"文件覆盖环境变量"
    会让那道闸门失效。
    """
    added = 0
    for key, value in _read_env_file(path):
        if key not in environ:
            environ[key] = value
            added += 1
    return added


def _resolve_app_env(environ: Mapping[str, str], base_env_path: Path) -> str:
    """确定 `APP_ENV`：进程环境 > 基础 `.env` 里的 `APP_ENV=` > `dev`。

    只查**基础层**，不查覆盖层：覆盖层正是由这个值选出来的，
    让覆盖层再定义它自己就是循环定义。
    """
    from_process = (environ.get("APP_ENV") or "").strip()
    if from_process:
        return from_process

    for key, value in _read_env_file(base_env_path):
        if key == "APP_ENV" and value.strip():
            return value.strip()
    return "dev"


def _overlay_path(root: Path, app_env: str) -> Path:
    """覆盖层路径 `.env.<APP_ENV>`（不保证存在）。"""
    return root / f".env.{app_env}"


def _load_dotenv(
    root: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """加载分环境配置，返回**活动 env 文件**；一个都没有时返回 None。

    优先级（高 → 低）：进程环境变量 > `.env.<APP_ENV>` > `.env`

    覆盖层先写、基础层后写，两次都是 setdefault，**先写的赢**——所以覆盖层里
    出现过的键不会被基础层改回去，而基础层独有的键仍然保留。

    没有覆盖层文件时，本函数与改造前逐键等价（有测试钉住这一条）：
    本仓库当前只有一个 `.env` 且指向生产库，这个"零变化"是硬要求。
    """
    root = BASE_DIR if root is None else root
    environ = os.environ if environ is None else environ

    base = root / ".env"
    overlay = _overlay_path(root, _resolve_app_env(environ, base))

    active: Path | None = None
    if overlay.is_file():
        _apply_env_file(overlay, environ)
        active = overlay
    if base.is_file():
        _apply_env_file(base, environ)
        active = active or base
    return active


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _get_bool(name: str, default: bool = False) -> bool:
    value = _get_env(name, "")
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = _get_env(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = _get_env(name, "")
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


ACTIVE_ENV_FILE = _load_dotenv()


@dataclass(frozen=True)
class AppSettings:
    env: str
    host: str
    port: int
    log_level: str


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    fallback_enabled: bool
    fallback_provider: str
    fallback_model: str
    fallback_base_url: str
    fallback_api_key: str


@dataclass(frozen=True)
class DatabaseSettings:
    url: str


@dataclass(frozen=True)
class ASRSettings:
    access_key_id: str
    access_key_secret: str
    app_key: str


@dataclass(frozen=True)
class OSSSettings:
    access_key_id: str
    access_key_secret: str
    bucket_name: str
    endpoint: str
    domain: str
    video_prefix: str
    snapshot_prefix: str


@dataclass(frozen=True)
class ResearchSettings:
    deployment_profile: str
    enabled: bool
    runtime_mode: str
    model_root: str
    gallery_root: str
    cache_root: str
    model_source: str
    auto_download_allowed: bool
    hf_token: str
    enhanced_python: str
    pyannote_model_id: str
    wespeaker_model_name: str
    clip_model_id: str
    bge_model_id: str
    wespeaker_repo_url: str
    talknet_repo_url: str


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    llm: LLMSettings
    db: DatabaseSettings
    asr: ASRSettings
    oss: OSSSettings
    research: ResearchSettings


def _build_settings() -> Settings:
    llm_provider = _get_env("LLM_PROVIDER", "deepseek").lower()
    default_model = "gemma4:e4b" if llm_provider == "ollama" else "deepseek-chat"
    default_base_url = "http://127.0.0.1:11434/v1" if llm_provider == "ollama" else "https://api.deepseek.com"
    llm_api_key = _get_env("LLM_API_KEY", "ollama" if llm_provider == "ollama" else "")
    research_profile = _get_env("RESEARCH_DEPLOYMENT_PROFILE", "standard").lower()
    default_research_enabled = research_profile == "enhanced"
    default_research_runtime_mode = "enhanced_strict" if research_profile == "enhanced" else "documented_only"
    default_research_model_root = str(BASE_DIR / "storage" / "research_models")
    default_research_gallery_root = str(BASE_DIR / "storage" / "research_gallery")
    default_research_cache_root = str(BASE_DIR / "storage" / "research_runtime_cache")

    oss_bucket = _get_env("OSS_BUCKET_NAME", "")
    oss_endpoint = _get_env("OSS_ENDPOINT", "")
    oss_domain = _get_env("OSS_DOMAIN", "")
    if not oss_domain and oss_bucket and oss_endpoint:
        oss_domain = f"https://{oss_bucket}.{oss_endpoint}"

    return Settings(
        app=AppSettings(
            env=_get_env("APP_ENV", "dev"),
            host=_get_env("APP_HOST", "0.0.0.0"),
            port=_get_int("APP_PORT", 8000),
            log_level=_get_env("LOG_LEVEL", "INFO"),
        ),
        llm=LLMSettings(
            provider=llm_provider,
            model=_get_env("LLM_MODEL", default_model),
            base_url=_get_env("LLM_BASE_URL", default_base_url),
            api_key=llm_api_key,
            timeout_seconds=_get_float("LLM_TIMEOUT_SECONDS", 60.0),
            max_retries=_get_int("LLM_MAX_RETRIES", 2),
            fallback_enabled=_get_bool("LLM_FALLBACK_ENABLED", llm_provider != "deepseek"),
            fallback_provider=_get_env("LLM_FALLBACK_PROVIDER", "deepseek"),
            fallback_model=_get_env("LLM_FALLBACK_MODEL", "deepseek-chat"),
            fallback_base_url=_get_env("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com"),
            fallback_api_key=_get_env("LLM_FALLBACK_API_KEY", ""),
        ),
        db=DatabaseSettings(
            url=_get_env("DATABASE_URL", "sqlite:///./storage/app.db"),
        ),
        asr=ASRSettings(
            access_key_id=_get_env("ALIYUN_ACCESS_KEY_ID", ""),
            access_key_secret=_get_env("ALIYUN_ACCESS_KEY_SECRET", ""),
            app_key=_get_env("ALIYUN_APP_KEY", ""),
        ),
        oss=OSSSettings(
            access_key_id=_get_env("OSS_ACCESS_KEY_ID", ""),
            access_key_secret=_get_env("OSS_ACCESS_KEY_SECRET", ""),
            bucket_name=oss_bucket,
            endpoint=oss_endpoint,
            domain=oss_domain,
            video_prefix=_get_env("OSS_VIDEO_PREFIX", "video_chunks/"),
            snapshot_prefix=_get_env("OSS_SNAPSHOT_PREFIX", "snapshots/"),
        ),
        research=ResearchSettings(
            deployment_profile=research_profile,
            enabled=_get_bool("RESEARCH_MODULES_ENABLED", default_research_enabled),
            runtime_mode=_get_env("RESEARCH_RUNTIME_MODE", default_research_runtime_mode),
            model_root=_get_env("RESEARCH_MODEL_ROOT", default_research_model_root),
            gallery_root=_get_env("RESEARCH_GALLERY_ROOT", default_research_gallery_root),
            cache_root=_get_env("RESEARCH_CACHE_ROOT", default_research_cache_root),
            model_source=_get_env("RESEARCH_MODEL_SOURCE", "manual_local"),
            auto_download_allowed=_get_bool("RESEARCH_AUTO_DOWNLOAD_MODELS", False),
            hf_token=_get_env("RESEARCH_HF_TOKEN", ""),
            enhanced_python=_get_env("RESEARCH_ENHANCED_PYTHON", sys.executable),
            pyannote_model_id=_get_env("RESEARCH_PYANNOTE_MODEL_ID", "pyannote/speaker-diarization-3.1"),
            wespeaker_model_name=_get_env("RESEARCH_WESPEAKER_MODEL_NAME", "chinese"),
            clip_model_id=_get_env("RESEARCH_CLIP_MODEL_ID", "openai/clip-vit-base-patch16"),
            bge_model_id=_get_env("RESEARCH_BGE_MODEL_ID", "BAAI/bge-m3"),
            wespeaker_repo_url=_get_env("RESEARCH_WESPEAKER_REPO_URL", "https://github.com/wenet-e2e/wespeaker.git"),
            talknet_repo_url=_get_env("RESEARCH_TALKNET_REPO_URL", "https://github.com/TaoRuijie/TalkNet-ASD.git"),
        ),
    )


settings = _build_settings()


def _normalize_research_profile(value: str) -> str:
    profile = (value or "").strip().lower()
    return profile if profile in {"standard", "enhanced"} else "standard"


def _normalize_research_runtime_mode(profile: str, runtime_mode: str = "") -> str:
    raw_mode = (runtime_mode or "").strip().lower()
    if raw_mode:
        return raw_mode
    return "enhanced_strict" if profile == "enhanced" else "documented_only"


def _write_env_updates(updates: dict, env_path: Path | None = None) -> str:
    """就地改写 env 文件。**默认写活动文件**（有覆盖层时即覆盖层）。

    参数 `env_path` 供测试注入；生产路径走默认值，因此读写始终指向同一份。
    """
    env_path = env_path or ACTIVE_ENV_FILE or (BASE_DIR / ".env")
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    found = set()
    rewritten = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rewritten.append(raw_line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in updates:
            rewritten.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            rewritten.append(raw_line)

    for key, value in updates.items():
        if key not in found:
            rewritten.append(f"{key}={value}")

    env_path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")
    return str(env_path)


def ensure_research_directories() -> dict:
    paths = {
        "model_root": Path(settings.research.model_root),
        "gallery_root": Path(settings.research.gallery_root),
        "cache_root": Path(settings.research.cache_root),
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    slot_names = [
        "pyannote",
        "wespeaker",
        "talknet_asd",
        "insightface",
        "clip_vit_b16",
        "bge_m3",
    ]
    model_root = paths["model_root"]
    for slot_name in slot_names:
        slot_dir = model_root / slot_name
        slot_dir.mkdir(parents=True, exist_ok=True)
        placeholder = slot_dir / "PLACE_MODEL_FILES_HERE.txt"
        if not placeholder.exists():
            placeholder.write_text(
                f"Put the local files for {slot_name} in this directory.\n",
                encoding="utf-8",
            )

    return {key: str(path) for key, path in paths.items()}


def get_research_runtime_settings_snapshot() -> dict:
    return {
        "deployment_profile": settings.research.deployment_profile,
        "enabled": settings.research.enabled,
        "runtime_mode": settings.research.runtime_mode,
        "model_root": settings.research.model_root,
        "gallery_root": settings.research.gallery_root,
        "cache_root": settings.research.cache_root,
        "env_file": str(ACTIVE_ENV_FILE or (BASE_DIR / ".env")),
    }


def apply_research_runtime_config(
    deployment_profile: str,
    enabled: bool,
    runtime_mode: str = "",
) -> dict:
    profile = _normalize_research_profile(deployment_profile)
    normalized_mode = _normalize_research_runtime_mode(profile, runtime_mode)

    object.__setattr__(settings.research, "deployment_profile", profile)
    object.__setattr__(settings.research, "enabled", bool(enabled))
    object.__setattr__(settings.research, "runtime_mode", normalized_mode)
    ensure_research_directories()
    return get_research_runtime_settings_snapshot()


def persist_research_runtime_config(
    deployment_profile: str,
    enabled: bool,
    runtime_mode: str = "",
) -> dict:
    profile = _normalize_research_profile(deployment_profile)
    normalized_mode = _normalize_research_runtime_mode(profile, runtime_mode)
    env_file = _write_env_updates(
        {
            "RESEARCH_DEPLOYMENT_PROFILE": profile,
            "RESEARCH_MODULES_ENABLED": "true" if enabled else "false",
            "RESEARCH_RUNTIME_MODE": normalized_mode,
        }
    )
    snapshot = apply_research_runtime_config(profile, enabled, normalized_mode)
    snapshot["env_file"] = env_file
    return snapshot


ensure_research_directories()
