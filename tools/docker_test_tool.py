"""
LogicFlow Docker Sandbox Tool
Provides isolated compilation and execution testing in Docker containers.
"""

import os
import tempfile
import subprocess
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from config import LogicFlowConfig, get_config

logger = logging.getLogger("LogicFlow.docker_tool")


@dataclass
class SandboxResult:
    """Result of a sandbox execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    language: str
    file_path: str
    compilation_log: str
    
    @property
    def error_message(self) -> str:
        """Extract clean error message from logs."""
        if self.success:
            return ""
        # Combine stderr and stdout for error context
        combined = f"{self.stderr}\n{self.stdout}".strip()
        # Truncate very long errors
        if len(combined) > 2000:
            combined = combined[:2000] + "\n... [truncated]"
        return combined


class DockerSandbox:
    """
    Manages Docker containers for safe code compilation testing.
    Supports multiple languages with appropriate Docker images and commands.
    """
    
    def __init__(self, config: Optional[LogicFlowConfig] = None):
        self.config = config or get_config()
        self._temp_dir: Optional[str] = None
    
    def _ensure_temp_dir(self) -> str:
        """Create and return temporary directory for sandbox files."""
        if self._temp_dir is None:
            temp_base = Path(self.config.workspace.temp_dir)
            temp_base.mkdir(parents=True, exist_ok=True)
            self._temp_dir = tempfile.mkdtemp(dir=temp_base, prefix="sandbox_")
        return self._temp_dir
    
    def _cleanup_temp_dir(self) -> None:
        """Remove temporary directory and contents."""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")
            self._temp_dir = None
    
    def _get_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext = Path(file_path).suffix
        return self.config.get_language_from_extension(ext)
    
    def _prepare_typescript_project(self, temp_dir: str, file_path: str) -> None:
        """Create minimal tsconfig.json for TypeScript compilation."""
        tsconfig = {
            "compilerOptions": {
                "target": "ES2020",
                "module": "commonjs",
                "strict": True,
                "esModuleInterop": True,
                "skipLibCheck": True,
                "forceConsistentCasingInFileNames": True,
                "noEmit": True,
            },
            "include": [file_path]
        }
        import json
        tsconfig_path = Path(temp_dir) / "tsconfig.json"
        tsconfig_path.write_text(json.dumps(tsconfig, indent=2))
    
    def _prepare_go_module(self, temp_dir: str, file_path: str) -> None:
        """Create minimal go.mod for Go compilation."""
        file_name = Path(file_path).stem
        go_mod = f"module {file_name}\n\ngo 1.21\n"
        go_mod_path = Path(temp_dir) / "go.mod"
        go_mod_path.write_text(go_mod)
    
    def _prepare_csharp_project(self, temp_dir: str, file_path: str) -> None:
        """Create minimal .csproj for C# compilation."""
        file_name = Path(file_path).stem
        csproj = f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
"""
        csproj_path = Path(temp_dir) / f"{file_name}.csproj"
        csproj_path.write_text(csproj)
    
    def _prepare_kotlin_project(self, temp_dir: str, file_path: str) -> None:
        """Adjust Kotlin file for standalone compilation."""
        # Kotlin needs proper package declaration handling
        pass
    
    def test_compilation(
        self,
        file_path: str,
        code_content: str,
        language: Optional[str] = None
    ) -> SandboxResult:
        """
        Test code compilation in an isolated Docker container.
        
        Args:
            file_path: Original file path (used for extension and naming)
            code_content: The code to test
            language: Override detected language (optional)
            
        Returns:
            SandboxResult with success status and logs
        """
        temp_dir = self._ensure_temp_dir()
        detected_language = language or self._get_language(file_path)
        
        if detected_language == "unknown":
            logger.warning(f"Unknown language for file: {file_path}")
            return SandboxResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Unsupported file type: {file_path}",
                language="unknown",
                file_path=file_path,
                compilation_log="No compiler configured for this file type"
            )
        
        # Write code to temp file
        temp_file = Path(temp_dir) / Path(file_path).name
        temp_file.write_text(code_content, encoding="utf-8")
        
        # Prepare language-specific project files
        if detected_language == "typescript":
            self._prepare_typescript_project(temp_dir, temp_file.name)
        elif detected_language == "go":
            self._prepare_go_module(temp_dir, temp_file.name)
        elif detected_language == "csharp":
            self._prepare_csharp_project(temp_dir, temp_file.name)
        
        # Get Docker image and compile command
        docker_image = self.config.get_docker_image(detected_language)
        compile_cmd = self.config.get_compile_command(detected_language, temp_file.name)
        
        logger.info(f"Testing {detected_language} compilation in {docker_image}")
        logger.debug(f"Command: {compile_cmd}")
        
        # Build Docker command
        docker_cmd = [
            "docker", "run", "--rm",
            f"--memory={self.config.docker.memory_limit}",
            f"--cpu-period={self.config.docker.cpu_period}",
            f"--cpu-quota={self.config.docker.cpu_quota}",
        ]
        
        if self.config.docker.network_disabled:
            docker_cmd.append("--network=none")
        
        docker_cmd.extend([
            "-v", f"{temp_dir}:/workspace",
            "-w", "/workspace",
            docker_image,
            "sh", "-c", compile_cmd
        ])
        
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.config.docker.timeout_seconds,
                cwd=temp_dir
            )
            
            success = result.returncode == 0
            compilation_log = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            
            if success:
                logger.info(f"Compilation successful for {file_path}")
            else:
                logger.warning(f"Compilation failed for {file_path}: exit code {result.returncode}")
            
            return SandboxResult(
                success=success,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                language=detected_language,
                file_path=file_path,
                compilation_log=compilation_log
            )
            
        except subprocess.TimeoutExpired:
            logger.error(f"Compilation timeout for {file_path}")
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Compilation timed out after {self.config.docker.timeout_seconds} seconds",
                language=detected_language,
                file_path=file_path,
                compilation_log="TIMEOUT: Compilation exceeded time limit"
            )
            
        except FileNotFoundError:
            logger.error("Docker not found. Is Docker installed and running?")
            return SandboxResult(
                success=False,
                exit_code=-2,
                stdout="",
                stderr="Docker command not found. Please ensure Docker is installed and running.",
                language=detected_language,
                file_path=file_path,
                compilation_log="ERROR: Docker not available"
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during compilation: {e}")
            return SandboxResult(
                success=False,
                exit_code=-3,
                stdout="",
                stderr=str(e),
                language=detected_language,
                file_path=file_path,
                compilation_log=f"ERROR: {e}"
            )
    
    def test_multiple_files(
        self,
        files: Dict[str, str],
        primary_file: str
    ) -> SandboxResult:
        """
        Test compilation with multiple files (for projects with dependencies).
        
        Args:
            files: Dict mapping file paths to their content
            primary_file: The main file to compile
            
        Returns:
            SandboxResult from compiling the primary file
        """
        temp_dir = self._ensure_temp_dir()
        
        # Write all files to temp directory
        for file_path, content in files.items():
            temp_file = Path(temp_dir) / Path(file_path).name
            # Create subdirectories if needed
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_text(content, encoding="utf-8")
        
        # Test primary file
        primary_content = files.get(primary_file, "")
        return self.test_compilation(primary_file, primary_content)
    
    def check_docker_available(self) -> Tuple[bool, str]:
        """Check if Docker is available and running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, "Docker is available"
            else:
                return False, f"Docker error: {result.stderr[:200]}"
        except FileNotFoundError:
            return False, "Docker command not found. Please install Docker."
        except subprocess.TimeoutExpired:
            return False, "Docker info command timed out"
        except Exception as e:
            return False, f"Error checking Docker: {e}"
    
    def cleanup(self) -> None:
        """Clean up temporary resources."""
        self._cleanup_temp_dir()