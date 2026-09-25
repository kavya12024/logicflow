"""
LogicFlow Configuration Module
Centralized configuration management for the entire system.
"""

import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv


load_dotenv()


@dataclass
class OllamaConfig:
    """Configuration for local Ollama LLM inference."""
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "llama3.2:3b"
    request_timeout: float = 300.0
    connect_timeout: float = 60.0
    temperature: float = 0.1
    max_tokens: int = 4096


@dataclass
class WorkspaceConfig:
    """Configuration for workspace and file handling."""
    demo_dir: str = "./workspace"
    temp_dir: str = "./workspace/.logicflow_temp"
    max_file_size_bytes: int = 500000
    supported_extensions: List[str] = field(default_factory=lambda: [
        ".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", 
        ".java", ".go", ".rs", ".js", ".jsx", ".ts", ".tsx",
        ".rb", ".php", ".cs", ".swift", ".kt", ".scala"
    ])


@dataclass
class FaissConfig:
    """Configuration for FAISS vector indexing."""
    index_path: str = "./faiss_index"
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k_results: int = 5
    similarity_threshold: float = 0.3


@dataclass
class DockerConfig:
    """Configuration for Docker sandbox execution."""
    timeout_seconds: int = 120
    max_retries: int = 2
    network_disabled: bool = True
    memory_limit: str = "512m"
    cpu_period: int = 100000
    cpu_quota: int = 50000


@dataclass
class GitHubConfig:
    """Configuration for GitHub integration."""
    token: str = ""
    repo: str = ""
    base_branch: str = "main"
    branch_prefix: str = "logicflow/fix"
    pr_title_prefix: str = "[LogicFlow] Fix"


@dataclass
class LogicFlowConfig:
    """Main configuration container aggregating all sub-configs."""
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    faiss: FaissConfig = field(default_factory=FaissConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    
    docker_images: Dict[str, str] = field(default_factory=lambda: {
        "c": "gcc:latest",
        "cpp": "gcc:latest",
        "python": "python:3.11-slim",
        "java": "openjdk:17-slim",
        "go": "golang:1.21-alpine",
        "rust": "rust:1.75-slim",
        "javascript": "node:20-slim",
        "typescript": "node:20-slim",
        "ruby": "ruby:3.2-slim",
        "php": "php:8.2-cli",
        "csharp": "mcr.microsoft.com/dotnet/sdk:8.0",
        "swift": "swift:5.9",
        "kotlin": "openjdk:17-slim",
        "scala": "openjdk:17-slim",
    })
    
    compile_commands: Dict[str, str] = field(default_factory=lambda: {
        "c": "gcc -o /tmp/output /workspace/{file} -Wall -Wextra -Werror -lm 2>&1",
        "cpp": "g++ -o /tmp/output /workspace/{file} -Wall -Wextra -Werror -std=c++17 2>&1",
        "python": "python -m py_compile /workspace/{file} 2>&1",
        "java": "javac -d /tmp /workspace/{file} 2>&1",
        "go": "cd /workspace && go build -o /tmp/output {file} 2>&1",
        "rust": "rustc -o /tmp/output /workspace/{file} 2>&1",
        "javascript": "node --check /workspace/{file} 2>&1",
        "typescript": "cd /workspace && npx tsc --noEmit --strict {file} 2>&1",
        "ruby": "ruby -c /workspace/{file} 2>&1",
        "php": "php -l /workspace/{file} 2>&1",
        "csharp": "dotnet build /workspace/{file} --no-restore 2>&1",
        "swift": "swiftc -o /tmp/output /workspace/{file} 2>&1",
        "kotlin": "kotlinc /workspace/{file} -include-runtime -d /tmp/output.jar 2>&1",
        "scala": "scalac -d /tmp /workspace/{file} 2>&1",
    })
    
    test_commands: Dict[str, str] = field(default_factory=lambda: {
        "python": "python -m unittest discover -s /workspace -p 'test_*.py' 2>&1",
        "javascript": "npm test 2>&1",
        "typescript": "npm test 2>&1",
        "go": "go test ./... 2>&1",
        "rust": "cargo test 2>&1",
    })
    
    language_extensions: Dict[str, List[str]] = field(default_factory=lambda: {
        "c": [".c"],
        "cpp": [".cpp", ".hpp", ".cc", ".cxx"],
        "python": [".py"],
        "java": [".java"],
        "go": [".go"],
        "rust": [".rs"],
        "javascript": [".js", ".jsx", ".mjs"],
        "typescript": [".ts", ".tsx"],
        "ruby": [".rb"],
        "php": [".php"],
        "csharp": [".cs"],
        "swift": [".swift"],
        "kotlin": [".kt", ".kts"],
        "scala": [".scala"],
    })

    @classmethod
    def from_environment(cls) -> "LogicFlowConfig":
        """Create configuration from environment variables."""
        config = cls()
        config.ollama.base_url = os.getenv("OLLAMA_BASE_URL", config.ollama.base_url)
        config.ollama.model = os.getenv("OLLAMA_MODEL", config.ollama.model)
        config.ollama.request_timeout = float(os.getenv("OLLAMA_TIMEOUT", str(config.ollama.request_timeout)))
        config.ollama.connect_timeout = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", str(config.ollama.connect_timeout)))
        config.workspace.demo_dir = os.getenv("LOGICFLOW_WORKSPACE", config.workspace.demo_dir)
        config.faiss.index_path = os.getenv("LOGICFLOW_FAISS_PATH", config.faiss.index_path)
        config.faiss.embedding_model = os.getenv("LOGICFLOW_EMBEDDING_MODEL", config.faiss.embedding_model)
        config.github.token = os.getenv("GITHUB_TOKEN", config.github.token)
        config.github.repo = os.getenv("GITHUB_REPO", config.github.repo)
        config.github.base_branch = os.getenv("GITHUB_BASE_BRANCH", config.github.base_branch)
        return config

    def get_language_from_extension(self, extension: str) -> str:
        """Determine programming language from file extension."""
        ext_lower = extension.lower()
        for lang, extensions in self.language_extensions.items():
            if ext_lower in extensions:
                return lang
        return "unknown"

    def get_docker_image(self, language: str) -> str:
        """Get Docker image for a given language."""
        return self.docker_images.get(language, "ubuntu:latest")

    def get_compile_command(self, language: str, filename: str) -> str:
        """Get compilation command for a given language and filename."""
        template = self.compile_commands.get(language, "")
        if not template:
            return f"echo 'No compiler configured for {language}'"
        return template.format(file=filename)

    def get_test_command(self, language: str, test_file: Optional[str] = None) -> str:
        """Get test command for a given language and optional test file."""
        if test_file and language == "python":
            return f"python -m unittest /workspace/{test_file} 2>&1"
        return self.test_commands.get(language, "echo 'No test command configured'")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "ollama": {
                "base_url": self.ollama.base_url,
                "model": self.ollama.model,
                "timeout": self.ollama.request_timeout,
            },
            "workspace": {
                "demo_dir": self.workspace.demo_dir,
                "temp_dir": self.workspace.temp_dir,
            },
            "faiss": {
                "index_path": self.faiss.index_path,
                "embedding_model": self.faiss.embedding_model,
                "chunk_size": self.faiss.chunk_size,
            },
            "github": {
                "repo": self.github.repo,
                "base_branch": self.github.base_branch,
            },
            "supported_languages": list(self.language_extensions.keys()),
        }


_config: Optional[LogicFlowConfig] = None


def get_config() -> LogicFlowConfig:
    """Get or create global configuration instance."""
    global _config
    if _config is None:
        _config = LogicFlowConfig.from_environment()
    return _config


def reset_config() -> None:
    """Reset global configuration (useful for testing)."""
    global _config
    _config = None