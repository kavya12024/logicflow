"""
LogicFlow Core Agent
The main orchestration engine that coordinates RAG, LLM, AST surgical splicing,
sandbox validation, and GitHub operations.
Implements the self-healing CI/CD loop with autonomous error detection and test repair.
"""

import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from openai import OpenAI

from config import LogicFlowConfig, get_config
from tools.faiss_tool import FaissIndexer, ContextTrimmer
from tools.docker_test_tool import DockerSandbox, SandboxResult, TestExecutionResult
from tools.github_tool import GitHubManager, GitHubIssue, PullRequestResult
from tools.ast_tool import ASTExtractor, TracebackInfo

logger = logging.getLogger("LogicFlow.core")


@dataclass
class AgentState:
    """Tracks the current state of the agent's execution."""
    issue: Optional[GitHubIssue] = None
    target_file: Optional[str] = None
    target_function: Optional[str] = None
    original_code: Optional[str] = None
    patched_code: Optional[str] = None
    context_dependencies: Dict[str, str] = field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 2
    last_sandbox_result: Optional[SandboxResult] = None
    llm_response: Optional[Dict[str, Any]] = None
    pr_result: Optional[PullRequestResult] = None
    logs: List[str] = field(default_factory=list)
    status: str = "initialized"  # initialized, analyzing, patching, testing, reviewing, creating_pr, completed, failed
    
    def add_log(self, message: str) -> None:
        """Add a timestamped log entry."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        logger.info(message)


@dataclass
class AgentResult:
    """Final result of agent execution."""
    success: bool
    issue_number: int
    target_file: str
    target_function: Optional[str] = None
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    explanation: str = ""
    security_audit: str = ""
    is_secure: bool = False
    attempts_used: int = 0
    error: Optional[str] = None
    fallback_git_args: Optional[Dict[str, Any]] = None
    logs: List[str] = field(default_factory=list)
    test_passed: bool = False


class LogicFlowAgent:
    """
    The Digital Archeologist - Autonomous AI Coding Agent.
    
    Orchestrates the complete self-healing CI/CD loop:
    1. Autonomous error detection via test suite or GitHub issue context
    2. Surgical AST function slicing for 100+ line codebases
    3. Lightweight local LLM prompt engineering (llama3.2:3b)
    4. Two-tier verification: compilation & test suite execution
    5. OWASP-centric security audit
    6. Pull request creation or direct local patch application
    """
    
    SURGICAL_SYSTEM_PROMPT = """You are LogicFlow, an expert code repair and debugging AI.
Your task is to fix a bug in a specific function.

CRITICAL INSTRUCTIONS:
1. You MUST respond with ONLY a valid JSON object. No conversational text outside JSON.
2. The JSON must follow this EXACT schema:
{
  "fixed_function": "def function_name(...):\\n    complete fixed function code here",
  "explanation": "brief explanation of what was wrong and how you fixed it",
  "security_audit": "OWASP-focused security check of your fix",
  "is_secure": true
}
3. The "fixed_function" must contain ONLY the complete code of the target function, including its 'def' header and correct indentation.
4. Do NOT include surrounding functions or rewrite the rest of the file.
5. Fix the logic or syntax error so that the reported error or failed test assertion passes."""

    SURGICAL_FEEDBACK_PROMPT = """Your previous fix failed verification with this error:

{error_log}

Please analyze the failure and provide a corrected fix for the target function.
Remember:
1. Respond with ONLY valid JSON with 'fixed_function', 'explanation', 'security_audit', 'is_secure'.
2. Focus specifically on fixing the failed assertion or error log above.
3. Keep the function signature identical unless asked otherwise."""

    FULLFILE_SYSTEM_PROMPT = """You are LogicFlow, an expert code repair and debugging AI.
Your job is to fix all syntax errors, indentation errors, and logic bugs in the provided code.

CRITICAL INSTRUCTIONS:
1. Fix all syntax errors, indentation errors, name errors, and logic bugs.
2. Provide the COMPLETE, runnable fixed code enclosed in a ```python ... ``` markdown block (or corresponding language block), or as a valid JSON object.
3. Do NOT omit any code. Do NOT use placeholders. Return the full working file from top to bottom.
4. After the code block, provide:
EXPLANATION:
<bullet points of what errors were fixed>
SECURITY_AUDIT:
<OWASP-focused security notes>
IS_SECURE: True/False"""

    FULLFILE_FEEDBACK_PROMPT = """Your previous fix failed verification with this error:

{error_log}

Please analyze the failure and provide the complete corrected code in a ```python ... ``` block.
Ensure all syntax, indentation, and logic errors are resolved."""

    def __init__(self, config: Optional[LogicFlowConfig] = None):
        self.config = config or get_config()
        self.faiss = FaissIndexer(self.config)
        self.sandbox = DockerSandbox(self.config)
        self.github = GitHubManager(self.config)
        self._llm_client: Optional[OpenAI] = None
        self._state = AgentState()
    
    def _get_llm_client(self) -> OpenAI:
        """Initialize or return the OpenAI client configured for Ollama."""
        if self._llm_client is None:
            self._llm_client = OpenAI(
                base_url=self.config.ollama.base_url,
                api_key=self.config.ollama.api_key,
                http_client=httpx.Client(
                    timeout=httpx.Timeout(
                        timeout=self.config.ollama.request_timeout,
                        connect=self.config.ollama.connect_timeout
                    )
                )
            )
        return self._llm_client
    
    def _sanitize_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Robust JSON parser for local lightweight LLMs (like llama3.2:3b).
        Handles markdown fences, regex extraction, single quote dicts, and raw code blocks.
        """
        if not text:
            return None
        
        logger.debug(f"Raw LLM output ({len(text)} chars)")
        
        # 1. Try standard JSON directly (with strict=False)
        try:
            return json.loads(text.strip(), strict=False)
        except (json.JSONDecodeError, TypeError):
            pass
        
        # 2. Strip markdown fences (e.g. ```json ... ```)
        clean_text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.IGNORECASE)
        clean_text = re.sub(r'\s*```$', '', clean_text)
        try:
            return json.loads(clean_text.strip(), strict=False)
        except (json.JSONDecodeError, TypeError):
            pass
        
        # 3. Fix common 3B model syntax quirks:
        # a) Unclosed "patches" sub-object before top-level keys
        repaired_text = re.sub(
            r'("patches"\s*:\s*\{[^{}]+?)(,\s*"(?:explanation|security_audit|is_secure)")',
            r'\1}\2',
            clean_text
        )
        # b) Trailing commas before closing braces
        repaired_text = re.sub(r',\s*([}\]])', r'\1', repaired_text)
        try:
            return json.loads(repaired_text.strip(), strict=False)
        except (json.JSONDecodeError, TypeError):
            pass

        # 4. Extract via regex match of outermost curly braces
        match = re.search(r'\{.*\}', repaired_text, re.DOTALL)
        if match:
            extracted = match.group(0)
            try:
                return json.loads(extracted, strict=False)
            except (json.JSONDecodeError, TypeError):
                pass
            
            # Replace single quotes with double quotes
            try:
                fixed_quotes = re.sub(r"(?<!\w)'|'(?!\w)", '"', extracted)
                return json.loads(fixed_quotes, strict=False)
            except (json.JSONDecodeError, TypeError):
                pass
            
            # Fallback: Parse as Python literal using ast
            try:
                import ast
                val = ast.literal_eval(extracted)
                if isinstance(val, dict):
                    return val
            except Exception:
                pass
        
        # 5. Regex extraction of "patches" or "fixed_function" if JSON structure is damaged
        fixed_func_match = re.search(r'"fixed_function"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL)
        if fixed_func_match:
            try:
                code_content = fixed_func_match.group(1).encode().decode('unicode_escape')
                return {
                    "fixed_function": code_content,
                    "explanation": "Extracted fixed function from response.",
                    "security_audit": "Automated security pass.",
                    "is_secure": True
                }
            except Exception:
                pass

        patch_match = re.search(r'"patches"\s*:\s*\{\s*"([^"]+)"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL)
        if patch_match:
            try:
                target_f = patch_match.group(1)
                code_content = patch_match.group(2).encode().decode('unicode_escape')
                return {
                    "patches": {target_f: code_content},
                    "explanation": "Extracted patch from response.",
                    "security_audit": "Automated security pass.",
                    "is_secure": True
                }
            except Exception:
                pass

        # 6. Fallback for raw code blocks (when model outputs code directly)
        code_block = re.search(r'```(?:python|javascript|c|cpp|java|go)?\s*\n(.*?)```', text, re.DOTALL)
        if code_block:
            extracted_code = code_block.group(1).strip()
            target = self._state.target_file or "file.py"
            
            expl_match = re.search(r'EXPLANATION:\s*\n(.*?)(?=\nSECURITY_AUDIT:|\nIS_SECURE:|$)', text, re.DOTALL | re.IGNORECASE)
            explanation = expl_match.group(1).strip() if expl_match else "Code extracted directly from markdown block."
            
            sec_match = re.search(r'SECURITY_AUDIT:\s*\n(.*?)(?=\nIS_SECURE:|$)', text, re.DOTALL | re.IGNORECASE)
            security_audit = sec_match.group(1).strip() if sec_match else "Automated security pass."
            
            is_sec_match = re.search(r'IS_SECURE:\s*(True|False)', text, re.IGNORECASE)
            is_secure = (is_sec_match.group(1).lower() == "true") if is_sec_match else True

            if self._state.target_function:
                return {
                    "fixed_function": extracted_code,
                    "explanation": explanation,
                    "security_audit": security_audit,
                    "is_secure": is_secure
                }
            return {
                "patches": {target: extracted_code},
                "explanation": explanation,
                "security_audit": security_audit,
                "is_secure": is_secure
            }

        # 7. Fallback if response is raw code without fences
        if any(kw in text for kw in ["def ", "class ", "import ", "return "]) and not text.strip().startswith("{"):
            lines = text.strip().splitlines()
            code_lines = []
            for line in lines:
                if line.startswith("EXPLANATION:") or line.startswith("SECURITY_AUDIT:"):
                    break
                code_lines.append(line)
            extracted_code = "\n".join(code_lines).strip()
            target = self._state.target_file or "file.py"
            return {
                "patches": {target: extracted_code},
                "explanation": "Code extracted directly from response.",
                "security_audit": "Automated security pass.",
                "is_secure": True
            }

        logger.warning(f"Could not parse valid JSON from LLM output: {text[:200]}...")
        return None

    def _validate_patch(self, patches: Dict[str, str]) -> Optional[str]:
        """Extract and validate target file code from patches dictionary."""
        if not patches:
            return None
        target = self._state.target_file
        if target and target in patches:
            return patches[target]
        if target:
            target_name = Path(target).name
            for k, v in patches.items():
                if Path(k).name == target_name:
                    return v
        return next(iter(patches.values()), None)
    
    def _build_surgical_context(
        self,
        function_name: str,
        function_code: str,
        file_outline: str,
        error_message: str,
        file_path: str,
        dependencies: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build compact context for surgical function repair.
        Optimized specifically for lightweight 3B models to avoid context saturation.
        """
        parts = [
            f"FILE: {file_path}",
            f"TARGET FUNCTION TO FIX: '{function_name}'",
            "",
            "CURRENT FUNCTION IMPLEMENTATION:",
            "```python",
            function_code,
            "```",
        ]
        
        if file_outline:
            parts.extend([
                "",
                "FILE CONTEXT (Other classes & functions in this file for reference):",
                "```python",
                file_outline,
                "```",
            ])
            
        if dependencies:
            parts.append("\nDEPENDENCY SIGNATURES:")
            for dep_path, dep_content in dependencies.items():
                parts.append(f"// {dep_path}:\n{dep_content}")
                
        parts.extend([
            "",
            "ERROR / FAILED ASSERTION DETAILS:",
            error_message if error_message else "Logical failure in test suite.",
            "",
            "TASK: Provide the corrected implementation for the function ONLY."
        ])
        
        return "\n".join(parts)
    
    def _build_fullfile_context(
        self,
        target_content: str,
        dependencies: Dict[str, str],
        error_message: str,
        issue_description: str,
        file_path: str
    ) -> str:
        """Build full-file context message for smaller files or non-Python code."""
        context_parts = [
            f"TARGET FILE: {file_path}",
            "```",
            target_content,
            "```",
        ]
        
        if dependencies:
            context_parts.append("\nDEPENDENCY SIGNATURES:")
            for dep_path, dep_content in dependencies.items():
                context_parts.append(f"\n--- {dep_path} ---\n{dep_content}")
        
        if error_message:
            context_parts.append(f"\nERROR MESSAGE:\n{error_message}")
        
        if issue_description:
            context_parts.append(f"\nISSUE DESCRIPTION:\n{issue_description}")
        
        return "\n".join(context_parts)
    
    def _call_llm(
        self,
        context_message: str,
        is_retry: bool = False,
        is_surgical: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Call the local LLM (Ollama) and parse the response."""
        client = self._get_llm_client()
        
        if is_surgical:
            system_msg = self.SURGICAL_SYSTEM_PROMPT
            if is_retry:
                error_log = self._state.last_sandbox_result.error_message if self._state.last_sandbox_result else "Test assertion failed"
                system_msg += "\n\n" + self.SURGICAL_FEEDBACK_PROMPT.format(error_log=error_log)
        else:
            system_msg = self.FULLFILE_SYSTEM_PROMPT
            if is_retry:
                error_log = self._state.last_sandbox_result.error_message if self._state.last_sandbox_result else "Compilation failed"
                system_msg += "\n\n" + self.FULLFILE_FEEDBACK_PROMPT.format(error_log=error_log)
        
        try:
            self._state.add_log(f"Calling Ollama ({self.config.ollama.model}) [surgical={is_surgical}]...")
            response = client.chat.completions.create(
                model=self.config.ollama.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": context_message}
                ],
                temperature=self.config.ollama.temperature,
                max_tokens=self.config.ollama.max_tokens
            )
            
            raw_response = response.choices[0].message.content
            self._state.add_log(f"LLM response received ({len(raw_response)} chars)")
            parsed = self._sanitize_json_response(raw_response)
            
            if parsed is None:
                self._state.add_log("Failed to parse LLM response into structured JSON")
                return None
            
            return parsed
            
        except Exception as e:
            self._state.add_log(f"LLM call failed: {str(e)}")
            logger.error(f"LLM call error: {e}")
            return None
    
    def _run_sandbox_test(self, code: str, test_file: Optional[str] = None) -> SandboxResult:
        """Run compilation and test suite in sandbox."""
        return self.sandbox.test_compilation_and_execution(
            file_path=self._state.target_file or "unknown.py",
            code_content=code,
            workspace_dir=self.config.workspace.demo_dir,
            test_file=test_file
        )
    
    def _evaluate_security(self, llm_response: Dict[str, Any]) -> Tuple[str, bool]:
        """Evaluate the security audit from LLM response + OWASP pattern checks."""
        security_audit = llm_response.get("security_audit", "Code passed standard review.")
        is_secure = llm_response.get("is_secure", True)
        
        code = self._state.patched_code or ""
        owasp_concerns = []
        
        dangerous_patterns = [
            (r'\beval\s*\(', "Use of eval() - potential code injection"),
            (r'\bexec\s*\(', "Use of exec() - potential code injection"),
            (r'\bos\.system\s*\(', "Use of os.system() - potential command injection"),
            (r'subprocess\.call\s*\(.*shell\s*=\s*True', "Subprocess with shell=True risk"),
            (r'password\s*=\s*[\'"][^\'"]+[\'"]', "Hardcoded password detected"),
            (r'api_key\s*=\s*[\'"][^\'"]+[\'"]', "Hardcoded API key detected"),
            (r'pickle\.loads?\s*\(', "Use of pickle - potential deserialization attack"),
            (r'yaml\.load\s*\([^,]+\)', "Use of yaml.load without safe_loader"),
            (r'innerHTML\s*=', "Direct innerHTML assignment - potential XSS"),
        ]
        
        for pattern, message in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                owasp_concerns.append(f"OWASP: {message}")
                is_secure = False
        
        if owasp_concerns:
            security_audit += "\n\nAdditional OWASP Concerns:\n" + "\n".join(owasp_concerns)
        
        return security_audit, is_secure
    
    def _reset_state(self) -> None:
        """Reset agent state for new run."""
        self._state = AgentState()
    
    def initialize_index(self, directory: Optional[str] = None, force_rebuild: bool = False) -> bool:
        """Initialize or load the FAISS index."""
        if not force_rebuild:
            if self.faiss.load_index():
                self._state.add_log("Loaded existing FAISS index")
                return True
        
        self._state.add_log("Building new FAISS index...")
        chunk_count = self.faiss.build_index(directory)
        
        if chunk_count > 0:
            self._state.add_log(f"Built index with {chunk_count} chunks")
            return True
        
        self._state.add_log("Failed to build index - no valid files found")
        return False

    def process_autonomous_test_and_fix(
        self,
        test_file: Optional[str] = None,
        workspace_dir: Optional[str] = None
    ) -> AgentResult:
        """
        AUTONOMOUS DETECTION & REPAIR LOOP:
        1. Runs test suite in workspace.
        2. If all pass, reports clean status.
        3. If a test fails, parses traceback to find the exact target file & function.
        4. Extracts only the target function via AST (handles 100+ line files safely).
        5. Calls llama3.2:3b for surgical fix.
        6. Splices the fix into the 100+ line file.
        7. Re-runs tests to verify.
        8. Writes changes permanently upon success.
        """
        self._reset_state()
        self._state.status = "analyzing"
        ws_dir = workspace_dir or self.config.workspace.demo_dir
        
        self._state.add_log("Autonomous Runner: Executing workspace test suite to detect errors...")
        initial_test_res = self.sandbox.run_test_suite(workspace_dir=ws_dir, test_file=test_file)
        
        if initial_test_res.success:
            self._state.add_log("All tests are already PASSING! No errors detected.")
            self._state.status = "completed"
            return AgentResult(
                success=True,
                issue_number=0,
                target_file="none",
                explanation="All unit tests passed. Codebase is healthy.",
                is_secure=True,
                test_passed=True,
                logs=self._state.logs
            )
            
        self._state.add_log("Error detected in test suite execution!")
        
        # Identify true source target file and function (avoiding test file modifications)
        target_file_name, target_func_name = ASTExtractor.resolve_target_from_test_failure(
            initial_test_res.output,
            ws_dir
        )
        
        if not target_file_name and initial_test_res.traceback_info:
            tb = initial_test_res.traceback_info
            target_func_name = tb.function_name
            if tb.target_file:
                try:
                    rel = Path(tb.target_file).name
                    for p in Path(ws_dir).rglob(rel):
                        target_file_name = str(p.relative_to(ws_dir)).replace("\\", "/")
                        break
                    if not target_file_name:
                        target_file_name = rel
                except Exception:
                    target_file_name = Path(tb.target_file).name
                    
        if not target_file_name:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=0,
                target_file="unknown",
                error=f"Could not identify target file from test failure: {initial_test_res.error_message}",
                logs=self._state.logs
            )
            
        self._state.target_file = target_file_name
        self._state.target_function = target_func_name
        self._state.add_log(f"Target identified: {target_file_name} (function: {target_func_name or 'file-level'})")
        
        # Read target file content
        target_full_path = Path(ws_dir) / target_file_name
        if not target_full_path.exists():
            return AgentResult(
                success=False,
                issue_number=0,
                target_file=target_file_name,
                error=f"Target file {target_file_name} does not exist in workspace",
                logs=self._state.logs
            )
            
        original_content = target_full_path.read_text(encoding="utf-8", errors="ignore")
        self._state.original_code = original_content
        
        # Perform surgical repair
        return self._execute_repair_loop(
            target_file=target_file_name,
            original_code=original_content,
            error_message=initial_test_res.output,
            target_function=target_func_name,
            test_file=test_file,
            workspace_dir=ws_dir,
            auto_save=True
        )

    def process_local_fix(
        self,
        target_file: str,
        error_message: str,
        test_file: Optional[str] = None,
        workspace_dir: Optional[str] = None
    ) -> AgentResult:
        """
        Direct repair of a local file with an error message or trace (no GitHub issue needed).
        """
        self._reset_state()
        self._state.status = "analyzing"
        ws_dir = workspace_dir or self.config.workspace.demo_dir
        
        target_full_path = Path(ws_dir) / target_file
        if not target_full_path.exists():
            return AgentResult(
                success=False,
                issue_number=0,
                target_file=target_file,
                error=f"File {target_file} not found in workspace",
                logs=self._state.logs
            )
            
        original_content = target_full_path.read_text(encoding="utf-8", errors="ignore")
        self._state.target_file = target_file
        self._state.original_code = original_content
        
        # Parse traceback to see if a specific function is implicated
        tb = ASTExtractor.parse_traceback(error_message)
        target_function = tb.function_name
        
        return self._execute_repair_loop(
            target_file=target_file,
            original_code=original_content,
            error_message=error_message,
            target_function=target_function,
            test_file=test_file,
            workspace_dir=ws_dir,
            auto_save=True
        )

    def process_code_snippet(
        self,
        code_snippet: str,
        error_message: Optional[str] = None,
        filename: str = "uploaded_code.py",
        workspace_dir: Optional[str] = None,
        auto_save: bool = False
    ) -> AgentResult:
        """
        Process and repair an uploaded full code snippet or file.
        1. Auto-detects syntax, indentation, and structure errors (e.g. via Python compile).
        2. Calls local LLM (llama3.2:3b) with full-code context and exact error diagnostics.
        3. Verifies compilation and syntax in sandbox/local environment.
        4. Performs self-healing retries if first attempt fails.
        5. Performs OWASP security audit.
        6. Returns structured AgentResult with patched code, explanations, and diff.
        """
        self._reset_state()
        self._state.status = "analyzing"
        ws_dir = workspace_dir or self.config.workspace.demo_dir
        
        self._state.target_file = filename
        self._state.original_code = code_snippet

        # Auto-detect syntax or indentation errors if no error message provided or to enrich it
        diagnostics = []
        if filename.endswith(".py"):
            try:
                compile(code_snippet, filename, "exec")
                diagnostics.append("Syntax pre-check: Clean. No syntax or indentation errors detected.")
            except SyntaxError as e:
                diagnostics.append(f"SyntaxError at line {e.lineno}: {e.msg}\nOffending code: {e.text.strip() if e.text else ''}")
            except Exception as e:
                diagnostics.append(f"Pre-check error: {e}")

        combined_error = error_message or ""
        if diagnostics and ("SyntaxError" in diagnostics[0] or not combined_error):
            if combined_error:
                combined_error += "\n\nAuto-Detected Diagnostics:\n" + "\n".join(diagnostics)
            else:
                combined_error = "Auto-Detected Diagnostics:\n" + "\n".join(diagnostics)

        self._state.add_log(f"Code Analysis: {len(code_snippet.splitlines())} lines in {filename}")
        if diagnostics:
            self._state.add_log(f"Pre-check: {diagnostics[0][:100]}")

        return self._execute_repair_loop(
            target_file=filename,
            original_code=code_snippet,
            error_message=combined_error,
            target_function=None,
            test_file=None,
            workspace_dir=ws_dir,
            auto_save=auto_save
        )

    def _execute_repair_loop(
        self,
        target_file: str,
        original_code: str,
        error_message: str,
        target_function: Optional[str] = None,
        test_file: Optional[str] = None,
        workspace_dir: Optional[str] = None,
        auto_save: bool = True
    ) -> AgentResult:
        """
        Internal unified repair loop with surgical AST slicing for 100+ line files.
        """
        ws_dir = workspace_dir or self.config.workspace.demo_dir
        
        # Security Guard: Never allow targeting system files or standard library
        FORBIDDEN = ["site-packages", "unittest", "pytest", "importlib", "appdata", "program files", "python3", "lib/"]
        target_path_lower = target_file.lower().replace("\\", "/")
        if any(fb in target_path_lower for fb in FORBIDDEN):
            self._state.status = "failed"
            self._state.add_log(f"SECURITY GUARD: Rejected attempt to modify system/standard library file: {target_file}")
            return AgentResult(
                success=False,
                issue_number=0,
                target_file="blocked_system_file",
                error=f"Security Guard: Target '{target_file}' is in Python standard library or system directories. Refusing to modify.",
                logs=self._state.logs
            )
            
        is_python = target_file.endswith(".py")
        
        # Check if we can isolate the specific function in the file
        target_func_code = None
        if is_python and target_function:
            target_func_code = ASTExtractor.find_target_function(original_code, target_function)
            
        if not target_func_code and is_python:
            # Try to extract function from error
            target_func_code, extracted_name = ASTExtractor.extract_function_from_error(original_code, error_message)
            if extracted_name:
                target_function = extracted_name
                
        is_surgical = bool(is_python and target_func_code and target_function)
        
        if is_surgical:
            self._state.add_log(f"Surgical Mode Active: Isolating function '{target_function}' ({len(target_func_code.splitlines())} lines) in {target_file}")
            file_outline = ASTExtractor.get_file_outline(original_code)
            context_message = self._build_surgical_context(
                function_name=target_function,
                function_code=target_func_code,
                file_outline=file_outline,
                error_message=error_message,
                file_path=target_file
            )
        else:
            self._state.add_log(f"Full-File Mode: Target is non-Python or whole-file ({len(original_code.splitlines())} lines)")
            context_message = self._build_fullfile_context(
                target_content=original_code,
                dependencies={},
                error_message=error_message,
                issue_description="",
                file_path=target_file
            )
            
        # Self-healing loop
        self._state.status = "patching"
        while self._state.attempts < self._state.max_attempts:
            self._state.attempts += 1
            self._state.add_log(f"Attempt {self._state.attempts} of {self._state.max_attempts}")
            
            is_retry = self._state.attempts > 1
            llm_response = self._call_llm(context_message, is_retry=is_retry, is_surgical=is_surgical)
            
            if llm_response is None:
                self._state.add_log("LLM did not return a valid patch response")
                continue
                
            self._state.llm_response = llm_response
            
            # Extract candidate code
            candidate_code = None
            if is_surgical and "fixed_function" in llm_response:
                fixed_func_code = llm_response["fixed_function"]
                spliced = ASTExtractor.replace_function_in_source(original_code, target_function, fixed_func_code)
                if spliced:
                    candidate_code = spliced
                    self._state.add_log(f"Successfully spliced fixed '{target_function}' back into {target_file}")
                else:
                    self._state.add_log("AST splicing failed to integrate fixed function; trying fallback")
                    
            if not candidate_code:
                # Full file or fallback
                candidate_code = self._validate_patch(llm_response.get("patches", {}))
                if not candidate_code and "fixed_function" in llm_response:
                    candidate_code = llm_response["fixed_function"]
                    
            if not candidate_code:
                self._state.add_log("No usable patch extracted from response")
                continue
                
            self._state.patched_code = candidate_code
            
            # Verify in sandbox
            self._state.status = "testing"
            self._state.add_log("Verifying candidate fix in sandbox (compilation & tests)...")
            sandbox_result = self._run_sandbox_test(candidate_code, test_file=test_file)
            self._state.last_sandbox_result = sandbox_result
            
            if sandbox_result.success:
                self._state.add_log("Verification PASSED: Code compiled and all tests passed!")
                break
            else:
                self._state.add_log(f"Verification FAILED: {sandbox_result.error_message[:200]}")
                if self._state.attempts < self._state.max_attempts:
                    self._state.add_log("Feeding back error details to LLM for self-healing attempt...")
                    
        # Check overall outcome
        if not self._state.patched_code or not self._state.last_sandbox_result or not self._state.last_sandbox_result.success:
            self._state.status = "failed"
            security_audit = "Verification failed prior to security review."
            is_secure = True
            if self._state.patched_code:
                security_audit, is_secure = self._evaluate_security(self._state.llm_response or {})
            return AgentResult(
                success=False,
                issue_number=0,
                target_file=target_file,
                target_function=target_function,
                error="Failed to produce a verified fix after all attempts",
                attempts_used=self._state.attempts,
                logs=self._state.logs,
                is_secure=is_secure,
                security_audit=security_audit,
                test_passed=False
            )
            
        # Security review
        self._state.status = "reviewing"
        self._state.add_log("Running OWASP security review...")
        security_audit, is_secure = self._evaluate_security(self._state.llm_response or {})
        
        # Apply permanently if requested
        if auto_save:
            target_path = Path(ws_dir) / target_file
            target_path.write_text(self._state.patched_code, encoding="utf-8")
            self._state.add_log(f"Applied verified fix permanently to {target_path}")
            
        explanation = (self._state.llm_response or {}).get("explanation", "Automated fix by LogicFlow")
        self._state.status = "completed"
        
        return AgentResult(
            success=True,
            issue_number=0,
            target_file=target_file,
            target_function=target_function,
            explanation=explanation,
            security_audit=security_audit,
            is_secure=is_secure,
            attempts_used=self._state.attempts,
            logs=self._state.logs,
            test_passed=True
        )

    def process_issue(
        self,
        issue_number: int,
        target_file_override: Optional[str] = None
    ) -> AgentResult:
        """
        Process a GitHub issue through the complete self-healing loop.
        """
        self._reset_state()
        self._state.status = "analyzing"
        
        self._state.add_log(f"Fetching issue #{issue_number} from GitHub...")
        issue = self.github.fetch_issue_by_number(issue_number)
        
        if issue is None:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file="unknown",
                error=f"Could not fetch issue #{issue_number}",
                logs=self._state.logs
            )
            
        self._state.issue = issue
        self._state.add_log(f"Issue #{issue_number}: {issue.title}")
        
        # Target file
        target_file = target_file_override or self._identify_target_file(issue)
        if not target_file:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file="unknown",
                error="Could not identify target file from issue description",
                logs=self._state.logs
            )
            
        self._state.target_file = target_file
        
        # Read target file content
        target_content = self.faiss.get_full_file_content(target_file)
        if not target_content:
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file=target_file,
                error=f"Could not read target file {target_file}",
                logs=self._state.logs
            )
            
        self._state.original_code = target_content
        error_message = "\n".join(issue.error_messages) if issue.error_messages else issue.body
        
        # Check for function name in issue body or traceback
        tb = ASTExtractor.parse_traceback(error_message)
        target_function = tb.function_name
        
        # Run repair
        result = self._execute_repair_loop(
            target_file=target_file,
            original_code=target_content,
            error_message=error_message,
            target_function=target_function,
            auto_save=False  # GitHub branch will receive the code
        )
        
        if not result.success:
            return result
            
        # Create GitHub PR
        self._state.status = "creating_pr"
        self._state.add_log("Creating GitHub Pull Request with fix...")
        pr_result = self.github.create_pull_request(
            issue_id=issue_number,
            explanation=result.explanation,
            fixed_code=self._state.patched_code,
            file_path=target_file
        )
        
        result.pr_url = pr_result.pr_url
        result.branch_name = pr_result.branch_name
        result.fallback_git_args = pr_result.fallback_git_args
        
        if pr_result.success:
            self._state.add_log(f"PR created successfully: {pr_result.pr_url}")
        else:
            self._state.add_log(f"PR creation fallback: {pr_result.error}")
            
        return result

    def _validate_patch(self, patch: Dict[str, str]) -> Optional[str]:
        """Validate and extract the patched code from dictionary."""
        if not patch:
            return None
        target = self._state.target_file
        if target and target in patch:
            return patch[target]
        for key, val in patch.items():
            if ("." in key or "/" in key) and val:
                return val
        return list(patch.values())[0] if patch else None

    def _identify_target_file(self, issue: GitHubIssue) -> Optional[str]:
        """Identify target file from issue references or RAG index search."""
        indexed_files = self.faiss.get_indexed_files()
        
        if issue.referenced_files:
            for ref in issue.referenced_files:
                if ref in indexed_files:
                    return ref
                ref_name = Path(ref).name
                for indexed in indexed_files:
                    if indexed.endswith(ref_name) or indexed == ref_name:
                        return indexed
                        
        if issue.error_messages:
            query = " ".join(issue.error_messages[:2])
            results = self.faiss.query(query, top_k=1)
            if results:
                return results[0][0].file_path
                
        results = self.faiss.query(issue.title, top_k=1)
        if results:
            return results[0][0].file_path
            
        return None

    def get_state(self) -> AgentState:
        """Get current agent state."""
        return self._state
    
    def get_patched_code(self) -> Optional[str]:
        """Get the patched code from the last run."""
        return self._state.patched_code