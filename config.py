import os
import sys
from dataclasses import dataclass
from pathlib import Path

# 根目录由 app.core.paths 统一解析，不再由本文件的位置推断。
#
# 这一行是阶段 3 的关键：设计文档 §4.1 要把本文件迁到 app/core/config.py。
# 若此处仍用 `Path(__file__).resolve().parent`，迁移后它立刻变成 `<root>/app/core`，
# `.env` 随之找不到——而下方 `_load_dotenv()` 是**静默 return**（§3.10），
# 配置会无声退化为默认值，应用照常启动、照常跑，只在连库时才暴露。
# 改走 paths 后，本文件搬到任何位置解析结果都不变。
from app.core.paths import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


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


_load_dotenv()


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


def _write_env_updates(updates: dict) -> str:
    env_path = BASE_DIR / ".env"
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
        "env_file": str(BASE_DIR / ".env"),
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
