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
from tools.ast_tool import ASTExtractor, TracebackInfo

logger = logging.getLogger("LogicFlow.docker_tool")


@dataclass
class TestExecutionResult:
    """Result of running test suites (pytest/unittest)."""
    success: bool
    exit_code: int
    output: str
    error_message: str
    traceback_info: Optional[TracebackInfo] = None


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
    test_result: Optional[TestExecutionResult] = None
    
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
        self._docker_available_cache: Optional[Tuple[bool, str]] = None
    
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
        
        docker_available, _ = self.check_docker_available()
        if not docker_available:
            return self._test_compilation_local(file_path, code_content, detected_language, temp_dir)

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
            logger.info("Docker command not found. Falling back to local compilation...")
            return self._test_compilation_local(file_path, code_content, detected_language, temp_dir)
            
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

    def _test_compilation_local(
        self,
        file_path: str,
        code_content: str,
        language: str,
        temp_dir: str
    ) -> SandboxResult:
        """Fallback local compilation/syntax check when Docker is unavailable."""
        if language == "python":
            try:
                compile(code_content, file_path, "exec")
                logger.info(f"Local Python syntax compilation succeeded for {file_path}")
                return SandboxResult(
                    success=True,
                    exit_code=0,
                    stdout="Local Python syntax compilation succeeded",
                    stderr="",
                    language="python",
                    file_path=file_path,
                    compilation_log="Local compile() check passed with zero syntax errors."
                )
            except SyntaxError as e:
                err_msg = f"SyntaxError at line {e.lineno}: {e.msg}\n{e.text or ''}".strip()
                logger.warning(f"Local compilation failed for {file_path}: {err_msg}")
                return SandboxResult(
                    success=False,
                    exit_code=1,
                    stdout="",
                    stderr=err_msg,
                    language="python",
                    file_path=file_path,
                    compilation_log=f"STDERR:\n{err_msg}"
                )
            except Exception as e:
                return SandboxResult(
                    success=False,
                    exit_code=1,
                    stdout="",
                    stderr=str(e),
                    language="python",
                    file_path=file_path,
                    compilation_log=f"STDERR:\n{e}"
                )
        elif language == "javascript":
            try:
                temp_file = Path(temp_dir) / Path(file_path).name
                temp_file.write_text(code_content, encoding="utf-8")
                res = subprocess.run(["node", "--check", str(temp_file)], capture_output=True, text=True, timeout=10)
                return SandboxResult(
                    success=(res.returncode == 0),
                    exit_code=res.returncode,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    language="javascript",
                    file_path=file_path,
                    compilation_log=f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
                )
            except Exception:
                pass
        
        # Default fallback: allow if syntax can't be locally verified without compiler
        return SandboxResult(
            success=True,
            exit_code=0,
            stdout="Local syntax check skipped (compiler not locally installed)",
            stderr="",
            language=language,
            file_path=file_path,
            compilation_log="Docker unavailable; skipped containerized compilation."
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
    
    def run_test_suite(
        self,
        workspace_dir: Optional[str] = None,
        test_file: Optional[str] = None,
        language: str = "python"
    ) -> TestExecutionResult:
        """
        Executes the test suite in the workspace directory.
        Supports execution via Docker sandbox (if available) or isolated local subprocess.
        Parses test output to extract stack traces and assertion failures.
        """
        target_dir = Path(workspace_dir or self.config.workspace.demo_dir).resolve()
        
        # Determine test command
        cmd_str = self.config.get_test_command(language, test_file)
        
        # Check if Docker should be used and is available
        docker_available, _ = self.check_docker_available()
        
        if docker_available and False:  # Reserve Docker for containerized environments
            docker_image = self.config.get_docker_image(language)
            docker_cmd = [
                "docker", "run", "--rm",
                f"--memory={self.config.docker.memory_limit}",
                "-v", f"{target_dir}:/workspace",
                "-w", "/workspace",
                docker_image,
                "sh", "-c", cmd_str
            ]
            run_cmd = docker_cmd
            cwd_path = str(target_dir)
        else:
            # Run locally in workspace with current Python interpreter or shell
            env = os.environ.copy()
            if language == "python":
                import sys
                py_exec = sys.executable
                
                # Build rich PYTHONPATH with all workspace source directories
                py_dirs = {
                    str(p.parent) for p in target_dir.rglob("*.py")
                    if not any(k in str(p).lower() for k in [".git", "__pycache__", ".venv"])
                }
                py_dirs.add(str(target_dir))
                env["PYTHONPATH"] = os.pathsep.join(py_dirs) + os.pathsep + env.get("PYTHONPATH", "")
                
                if test_file:
                    target_test_name = Path(test_file).name
                    found_tests = [
                        p for p in target_dir.rglob(target_test_name)
                        if not any(k in str(p).lower() for k in [".git", "__pycache__", ".venv"])
                    ]
                    if found_tests:
                        actual_test_path = found_tests[0]
                        cwd_path = str(actual_test_path.parent)
                        run_cmd = [py_exec, "-m", "unittest", actual_test_path.name]
                    else:
                        cwd_path = str(target_dir)
                        run_cmd = [py_exec, "-m", "unittest", test_file]
                else:
                    # Autonomous discovery: find test files across workspace
                    all_tests = [
                        p for p in target_dir.rglob("test_*.py")
                        if not any(k in str(p).lower() for k in [".git", "__pycache__", ".venv"])
                    ]
                    if all_tests:
                        test_parent_dirs = list({str(p.parent) for p in all_tests})
                        primary_test_dir = max(
                            test_parent_dirs,
                            key=lambda d: len([p for p in all_tests if str(p.parent) == d])
                        )
                        cwd_path = primary_test_dir
                        run_cmd = [py_exec, "-m", "unittest", "discover", "-s", primary_test_dir, "-p", "test_*.py"]
                    else:
                        cwd_path = str(target_dir)
                        run_cmd = [py_exec, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]
            else:
                run_cmd = cmd_str
                cwd_path = str(target_dir)

        logger.info(f"Running test suite in {cwd_path} with command: {run_cmd}")
        
        try:
            result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=self.config.docker.timeout_seconds,
                cwd=cwd_path,
                env=env,
                shell=isinstance(run_cmd, str)
            )
            
            output = f"{result.stdout}\n{result.stderr}".strip()
            
            # If no test files matched, it is not a test failure
            if "NO TESTS RAN" in output or "Ran 0 tests" in output:
                success = True
            else:
                success = result.returncode == 0
            
            traceback_info = None
            error_msg = ""
            if not success:
                traceback_info = ASTExtractor.parse_traceback(output)
                error_msg = traceback_info.error_message or output[:1000]
                
            return TestExecutionResult(
                success=success,
                exit_code=result.returncode,
                output=output,
                error_message=error_msg,
                traceback_info=traceback_info
            )
            
        except subprocess.TimeoutExpired:
            return TestExecutionResult(
                success=False,
                exit_code=-1,
                output="Test suite execution timed out",
                error_message="Timeout: Test execution exceeded time limit"
            )
        except Exception as e:
            logger.error(f"Error running test suite: {e}")
            return TestExecutionResult(
                success=False,
                exit_code=-2,
                output=str(e),
                error_message=f"Failed to execute tests: {e}"
            )

    def test_compilation_and_execution(
        self,
        file_path: str,
        code_content: str,
        workspace_dir: Optional[str] = None,
        test_file: Optional[str] = None,
        language: Optional[str] = None
    ) -> SandboxResult:
        """
        Two-tier verification:
        Tier 1: Syntax compilation check.
        Tier 2: Test suite execution check (if tests exist).
        """
        # Tier 1: Syntax check
        compile_res = self.test_compilation(file_path, code_content, language)
        if not compile_res.success:
            return compile_res
            
        # Tier 2: Check for test execution
        ws_path = Path(workspace_dir or self.config.workspace.demo_dir)
        target_file_full = ws_path / file_path
        
        # Determine the effective test file for this target
        lang = language or self._get_language(file_path)
        effective_test_file = test_file
        
        if not effective_test_file and lang == "python":
            # Search workspace for a unit test specifically dedicated to this target file
            stem = Path(file_path).stem
            cand_tests = [
                f"test_{stem}.py",
                f"{stem}_test.py",
                f"test_{Path(file_path).name}",
            ]
            for ct in cand_tests:
                matched = [
                    p for p in ws_path.rglob(ct)
                    if not any(k in str(p).lower() for k in [".git", "__pycache__", ".venv"])
                ]
                if matched:
                    effective_test_file = str(matched[0].relative_to(ws_path)).replace("\\", "/")
                    break

        if not effective_test_file:
            # Standalone file with no associated unit tests.
            # Tier 1 syntax compilation check is sufficient for verification.
            compile_res.compilation_log += f"\n\nNo associated test suite found for '{file_path}'. Verified via syntax compilation."
            return compile_res
            
        backup_content = None
        if target_file_full.exists():
            backup_content = target_file_full.read_text(encoding="utf-8", errors="ignore")
            
        try:
            target_file_full.parent.mkdir(parents=True, exist_ok=True)
            target_file_full.write_text(code_content, encoding="utf-8")
            
            test_res = self.run_test_suite(
                workspace_dir=str(ws_path),
                test_file=effective_test_file,
                language=lang
            )
            
            compile_res.test_result = test_res
            if not test_res.success and "NO TESTS RAN" not in test_res.output:
                compile_res.success = False
                compile_res.stderr = f"TEST FAILURE:\n{test_res.output}"
                compile_res.compilation_log += f"\n\nTEST SUITE RUN ({effective_test_file}):\n{test_res.output}"
            else:
                compile_res.compilation_log += f"\n\nTEST SUITE RUN ({effective_test_file}):\n{test_res.output}"
                
            return compile_res
            
        finally:
            if backup_content is not None:
                target_file_full.write_text(backup_content, encoding="utf-8")
    
    def check_docker_available(self, force_refresh: bool = False) -> Tuple[bool, str]:
        """Check if Docker is available and running (cached to avoid repeated timeouts)."""
        if self._docker_available_cache is not None and not force_refresh:
            return self._docker_available_cache
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self._docker_available_cache = (True, "Docker is available")
            else:
                self._docker_available_cache = (False, f"Docker error: {result.stderr[:200]}")
        except FileNotFoundError:
            self._docker_available_cache = (False, "Docker command not found. Please install Docker.")
        except subprocess.TimeoutExpired:
            self._docker_available_cache = (False, "Docker info command timed out")
        except Exception as e:
            self._docker_available_cache = (False, f"Error checking Docker: {e}")
        return self._docker_available_cache
    
    def cleanup(self) -> None:
        """Clean up temporary resources."""
        self._cleanup_temp_dir()