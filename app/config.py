"""Application settings, grouped into typed dataclasses: models, limits, paths, and privacy/scan scope.
Every setting is documented in the README's Configuration section.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSettings:
    ollama_url: str = "http://localhost:11434"
    chat_model: str = "qwen3:4b"
    embedding_model: str = "nomic-embed-text:latest"
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass(frozen=True)
class LimitSettings:
    rerank_candidates: int = 20  # how wide the hybrid merge fetches
    rerank_top_n: int = 5  # what actually reaches the prompt
    rerank_max_length: int = 512
    rerank_batch_size: int = 16
    rerank_timeout_ms: int = 3000


@dataclass(frozen=True)
class PathSettings:
    data_dir: str = field(default_factory=lambda: os.path.abspath("data"))
    vector_dir: str = field(default_factory=lambda: os.path.abspath("vector_store"))
    log_file: str = field(default_factory=lambda: os.path.abspath("logs/actions.log"))
    # Temporary: replaced by per-project access later.
    allowed_root: str = field(default_factory=lambda: os.path.abspath(os.path.join(os.path.dirname(__file__), "AI-Workspace")))
    tesseract_path: str = r"C:/Program Files/Tesseract-OCR/tesseract.exe"


@dataclass(frozen=True)
class PrivacySettings:
    scan_drives: list[str] = field(default_factory=list)  # empty = scan nothing
    system_exclude: list[str] = field(
        default_factory=lambda: [
            "C:/Windows",
            "C:/Program Files",
            "C:/Program Files (x86)",
            "C:/ProgramData",
            "C:/$Recycle.Bin",
            "C:/System Volume Information",
        ]
    )
    privacy_exclude: list[str] = field(
        default_factory=lambda: [
            "AppData/Local/Google/Chrome",
            "AppData/Local/Microsoft/Edge",
            "AppData/Roaming/Mozilla/Firefox",
            "AppData/Local/Microsoft/Credentials",
            "AppData/Roaming/Microsoft/Credentials",
        ]
    )
    ignore_dirs: set[str] = field(
        default_factory=lambda: {
            ".git",
            "node_modules",
            "__pycache__",
            "venv",
            ".venv",
            "dist",
            "build",
            "AppData",
            "Program Files",
            "Program Files (x86)",
            "Windows",
            "ProgramData",
            "$RECYCLE.BIN",
            "System Volume Information",
            "site-packages",
            ".bun",
            ".npm",
            ".cache",
            ".cargo",
            ".nuget",
            ".gradle",
            ".m2",
            ".claude",
            ".codex",
            ".cagent",
            ".chocolatey",
            ".claude-mem",
            ".config",
            ".cookiecutters",
            ".copilot",
            ".docker",
            ".dotnet",
            ".github",
            ".ipython",
            ".junie",
            ".local",
            ".matplotlib",
            ".ms-ad",
            ".ollama",
            ".streamlit",
            ".th-client",
            ".vscode",
            ".vscode-shared",
            ".ssh",
            "Postman",
            "OneDrive - North American Private University",
        }
    )
    sensitive_files: set[str] = field(default_factory=lambda: {".claude.json"})
    code_extensions: set[str] = field(
        default_factory=lambda: {
            "py",
            "js",
            "ts",
            "java",
            "c",
            "cpp",
            "h",
            "css",
            "html",
            "json",
            "yaml",
            "yml",
            "xml",
            "md",
            "sh",
            "go",
            "rs",
            "php",
            "rb",
            "txt",
        }
    )
    skip_extensions: set[str] = field(
        default_factory=lambda: {
            "sys",
            "exe",
            "dll",
            "msi",
            "bin",
            "dat",
            "iso",
            "img",
            "vhd",
            "vhdx",
            "so",
            "dylib",
            "lib",
            "obj",
            "class",
            "pyc",
            "node",
            "zip",
            "rar",
            "7z",
            "gz",
            "tar",
            "mp3",
            "mp4",
            "mkv",
            "avi",
            "mov",
            "wav",
            "flac",
            "ttf",
            "otf",
            "woff",
            "woff2",
        }
    )


MODELS = ModelSettings()
LIMITS = LimitSettings()
PATHS = PathSettings()
PRIVACY = PrivacySettings()

# Flat aliases: existing `from app.config import X` imports rely on these.
OLLAMA_URL = MODELS.ollama_url
CHAT_MODEL = MODELS.chat_model
EMBEDDING_MODEL = MODELS.embedding_model
RERANK_ENABLED = MODELS.rerank_enabled
RERANK_MODEL = MODELS.rerank_model

RERANK_CANDIDATES = LIMITS.rerank_candidates
RERANK_TOP_N = LIMITS.rerank_top_n
RERANK_MAX_LENGTH = LIMITS.rerank_max_length
RERANK_BATCH_SIZE = LIMITS.rerank_batch_size
RERANK_TIMEOUT_MS = LIMITS.rerank_timeout_ms

DATA_DIR = PATHS.data_dir
VECTOR_DIR = PATHS.vector_dir
LOG_FILE = PATHS.log_file
ALLOWED_ROOT = PATHS.allowed_root
TESSRACT_PATH = PATHS.tesseract_path

SCAN_DRIVES = PRIVACY.scan_drives
SYSTEM_EXCLUDE = PRIVACY.system_exclude
PRIVACY_EXCLUDE = PRIVACY.privacy_exclude
IGNORE_DIRS = PRIVACY.ignore_dirs
SENSITIVE_FILES = PRIVACY.sensitive_files
CODE_EXTENSIONS = PRIVACY.code_extensions
SKIP_EXTENSIONS = PRIVACY.skip_extensions
