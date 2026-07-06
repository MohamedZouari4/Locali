import os

OLLAMA_URL = "http://localhost:11434"
CHAT_MODEL = "qwen3:4b"
EMBEDDING_MODEL = "nomic-embed-text:latest"

SCAN_DRIVES = ["C:/", "D:/"]
DATA_DIR = os.path.abspath("data")
VECTOR_DIR = os.path.abspath("vector_store")
LOG_FILE = os.path.abspath("logs/actions.log")

ALLOWED_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "AI-Workspace"))

TESSRACT_PATH = r"C:/Program Files/Tesseract-OCR/tesseract.exe"

SYSTEM_EXCLUDE = [
    "C:/Windows",
    "C:/Program Files",
    "C:/Program Files (x86)",
    "C:/ProgramData",
    "C:/$Recycle.Bin",
    "C:/System Volume Information",
]

PRIVACY_EXCLUDE = [
    "AppData/Local/Google/Chrome",
    "AppData/Local/Microsoft/Edge",
    "AppData/Roaming/Mozilla/Firefox",
    "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Credentials",
]

CODE_EXTENSIONS = {
    "py","js","ts","java","c","cpp","h","css","html",
    "json","yaml","yml","xml","md","sh","go","rs","php","rb","txt"
}

IGNORE_DIRS = {
    ".git","node_modules","__pycache__","venv",".venv","dist","build",
    "AppData","Program Files","Program Files (x86)","Windows","ProgramData",
    "$RECYCLE.BIN","System Volume Information","site-packages",
    ".bun",".npm",".cache",".cargo",".nuget",".gradle",".m2",".claude",".codex",
    ".cagent",".chocolatey",".claude-mem",".config",".cookiecutters",".copilot",
    ".docker",".dotnet",".github",".ipython",".junie",".local",".matplotlib",
    ".ms-ad",".ollama",".streamlit",".th-client",".vscode",".vscode-shared",
    ".ssh","Postman","OneDrive - North American Private University",
}

SENSITIVE_FILES = {".claude.json"}

SKIP_EXTENSIONS = {
    "sys","exe","dll","msi","bin","dat","iso","img","vhd","vhdx",
    "so","dylib","lib","obj","class","pyc","node",
    "zip","rar","7z","gz","tar",
    "mp3","mp4","mkv","avi","mov","wav","flac",
    "ttf","otf","woff","woff2",
}
