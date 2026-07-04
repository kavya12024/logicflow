"""
LogicFlow Core Agent
The main orchestration engine that coordinates RAG, LLM, sandbox, and GitHub operations.
Implements the self-healing CI/CD loop.
"""

import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from openai import OpenAI

from config import LogicFlowConfig, get_config
from tools.faiss_tool import FaissIndexer, ContextTrimmer
from tools.docker_test_tool import DockerSandbox, SandboxResult
from tools.github_tool import GitHubManager, GitHubIssue, PullRequestResult

logger = logging.getLogger("LogicFlow.core")


@dataclass
class AgentState:
    """Tracks the current state of the agent's execution."""
    issue: Optional[GitHubIssue] = None
    target_file: Optional[str] = None
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
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    explanation: str = ""
    security_audit: str = ""
    is_secure: bool = False
    attempts_used: int = 0
    error: Optional[str] = None
    fallback_git_args: Optional[Dict[str, Any]] = None
    logs: List[str] = field(default_factory=list)


class LogicFlowAgent:
    """
    The Digital Archeologist - Autonomous AI Coding Agent.
    
    Orchestrates the complete self-healing CI/CD loop:
    1. Retrieve bug context via RAG
    2. Patch errors using local LLM
    3. Verify compilation in Docker sandbox
    4. Review code via OWASP-centric security audit
    5. Commit working code via GitHub PR
    """
    
    SYSTEM_PROMPT = """You are LogicFlow, an expert code debugging and patching AI. Your task is to analyze bug reports and generate precise code fixes.

CRITICAL INSTRUCTIONS:
1. You MUST respond with ONLY a valid JSON object. No markdown, no explanations outside the JSON.
2. The JSON must follow this EXACT schema:
{
  "patches": {
    "file_path": "complete fixed code here"
  },
  "explanation": "brief explanation of what was wrong and how you fixed it",
  "security_audit": "OWASP-focused security analysis of your fix",
  "is_secure": true
}

3. For "patches", the key must be the file path provided, and the value must be the COMPLETE fixed file content.
4. For "security_audit", analyze for: injection vulnerabilities, authentication issues, data exposure, input validation, and secure coding practices.
5. Set "is_secure" to false if any security concerns remain.

CONTEXT PROVIDED:
- Target file: The file containing the bug (full content)
- Dependencies: Extracted signatures/types from related files
- Error: The compilation or runtime error message
- Issue: The bug report description

Fix the bug while maintaining code quality and security standards."""

    FEEDBACK_PROMPT = """Your previous fix failed compilation with this error:

{error_log}

Please analyze the error and provide a corrected fix. Remember:
1. Respond with ONLY valid JSON (no markdown fences)
2. Use the exact same schema as before
3. Focus on fixing the specific compilation error
4. Do not change working parts of the code"""

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
        Ultimate fallback JSON parser for local LLMs.
        """
        if not text:
            return None
        
        # REMOVE THIS LINE AFTER WE SEE THE OUTPUT:
        print("\n=== RAW LLM START ===\n" + text + "\n=== RAW LLM END ===\n")
        
        # 1. Try standard JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 2. Strip markdown fences
        clean_text = re.sub(r'^```(?:json)?\s*', '', text.strip())
        clean_text = re.sub(r'\s*```$', '', clean_text)
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            pass
        
        # 3. Extract via regex and try JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            extracted = match.group(0)
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
            
            # 4. Replace single quotes with double quotes (Python dict fix)
            try:
                fixed_quotes = extracted.replace("'", '"')
                return json.loads(fixed_quotes)
            except json.JSONDecodeError:
                pass
            
            # 5. Ultimate fallback: Parse as Python object using ast
            try:
                import ast
                return ast.literal_eval(extracted)
            except Exception:
                pass
        
                # ULTIMATE FALLBACK: If model ignores JSON and just writes code, extract it
        code_block = re.search(r'```(?:python|javascript|c|cpp|java|go)?\s*\n(.*?)```', text, re.DOTALL)
        if code_block:
            extracted_code = code_block.group(1).strip()
            target = self._state.target_file or "file.py"
            return {
                "patches": {target: extracted_code},
                "explanation": "Code extracted from conversational response (model ignored JSON format).",
                "security_audit": "Skipped - model did not return structured JSON.",
                "is_secure": False
            }

        logger.error(f"Failed to extract JSON from response: {text[:500]}...")
        return None
    
    def _build_context_message(
        self,
        target_content: str,
        dependencies: Dict[str, str],
        error_message: str,
        issue_description: str,
        file_path: str
    ) -> str:
        """Build the context message for the LLM."""
        context_parts = [
            f"TARGET FILE: {file_path}",
            f"```",
            target_content,
            f"```",
        ]
        
        if dependencies:
            context_parts.append("\nDEPENDENCY SIGNATURES (for type/reference context):")
            for dep_path, dep_content in dependencies.items():
                context_parts.append(f"\n--- {dep_path} ---")
                context_parts.append("```")
                context_parts.append(dep_content)
                context_parts.append("```")
        
        if error_message:
            context_parts.append(f"\nERROR MESSAGE:\n{error_message}")
        
        if issue_description:
            context_parts.append(f"\nISSUE DESCRIPTION:\n{issue_description}")
        
        return "\n".join(context_parts)
    
    def _call_llm(
        self,
        context_message: str,
        is_retry: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Call the local LLM and parse the response."""
        client = self._get_llm_client()
        
        system_msg = self.SYSTEM_PROMPT
        if is_retry:
            # Append feedback about the error to the system message
            error_log = self._state.last_sandbox_result.error_message if self._state.last_sandbox_result else "Unknown error"
            system_msg += "\n\n" + self.FEEDBACK_PROMPT.format(error_log=error_log)
        
        try:
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
            print("\n--- RAW LLM OUTPUT ---\n" + raw_response + "\n--- END RAW OUTPUT ---\n")
            parsed = self._sanitize_json_response(raw_response)
            
            if parsed is None:
                self._state.add_log("Failed to parse LLM response as JSON")
                return None
            
            # Validate required fields
            if "patches" not in parsed or "explanation" not in parsed:
                self._state.add_log("LLM response missing required fields")
                return None
            
            return parsed
            
        except Exception as e:
            self._state.add_log(f"LLM call failed: {str(e)}")
            logger.error(f"LLM call error: {e}")
            return None
    
    def _identify_target_file(self, issue: GitHubIssue) -> Optional[str]:
        """Identify the target file to fix from the issue."""
        # First, check explicitly referenced files
        if issue.referenced_files:
            # Filter to files that exist in our index
            indexed_files = self.faiss.get_indexed_files()
            for ref_file in issue.referenced_files:
                # Try exact match
                if ref_file in indexed_files:
                    return ref_file
                # Try matching just the filename
                ref_name = ref_file.split("/")[-1]
                for indexed in indexed_files:
                    if indexed.endswith(ref_name) or indexed == ref_name:
                        return indexed
        
        # If no explicit reference, try to find relevant file via RAG
        if issue.error_messages:
            query = " ".join(issue.error_messages[:2])
            results = self.faiss.query(query, top_k=1)
            if results:
                return results[0][0].file_path
        
        # Try title-based search
        results = self.faiss.query(issue.title, top_k=1)
        if results:
            return results[0][0].file_path
        
        return None
    
    def _validate_patch(self, patch: Dict[str, str]) -> Optional[str]:
        """Validate and extract the patched code."""
        if not patch:
            return None
        
        # Get the target file path
        target = self._state.target_file
        if not target:
            # Try to find any key that looks like a file path
            for key in patch.keys():
                if "." in key or "/" in key:
                    target = key
                    break
            if not target:
                target = list(patch.keys())[0] if patch else None
        
        if not target:
            return None
        
        return patch.get(target) or patch.get(list(patch.keys())[0])
    
    def _run_sandbox_test(self, code: str) -> SandboxResult:
        """Run compilation test in Docker sandbox."""
        return self.sandbox.test_compilation(
            file_path=self._state.target_file or "unknown.py",
            code_content=code
        )
    
    def _evaluate_security(self, llm_response: Dict[str, Any]) -> Tuple[str, bool]:
        """Evaluate the security audit from LLM response."""
        security_audit = llm_response.get("security_audit", "No security audit provided")
        is_secure = llm_response.get("is_secure", False)
        
        # Additional OWASP checks
        code = self._state.patched_code or ""
        owasp_concerns = []
        
        # Check for common vulnerabilities
        dangerous_patterns = [
            (r'eval\s*\(', "Use of eval() - potential code injection"),
            (r'exec\s*\(', "Use of exec() - potential code injection"),
            (r'system\s*\(', "Use of system() - potential command injection"),
            (r'popen\s*\(', "Use of popen() - potential command injection"),
            (r'sql\s*.*\+\s*[\'"]', "Potential SQL injection via string concatenation"),
            (r'password\s*=\s*[\'"][^\'"]+[\'"]', "Hardcoded password detected"),
            (r'api_key\s*=\s*[\'"][^\'"]+[\'"]', "Hardcoded API key detected"),
            (r'secret\s*=\s*[\'"][^\'"]+[\'"]', "Hardcoded secret detected"),
            (r'pickle\.loads?\s*\(', "Use of pickle - potential deserialization attack"),
            (r'yaml\.load\s*\([^,]+\)', "Use of yaml.load without safe_loader"),
            (r'subprocess\.call\s*\(\s*[\'"]', "Subprocess with shell=True risk"),
            (r'os\.system\s*\(', "Use of os.system() - potential command injection"),
            (r'innerHTML\s*=', "Direct innerHTML assignment - potential XSS"),
            (r'document\.write\s*\(', "Use of document.write - potential XSS"),
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
        """
        Initialize or load the FAISS index.
        
        Args:
            directory: Directory to index (uses config default if None)
            force_rebuild: Force rebuilding the index even if one exists
            
        Returns:
            True if index is ready for use
        """
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
    
    def process_issue(
        self,
        issue_number: int,
        target_file_override: Optional[str] = None
    ) -> AgentResult:
        """
        Process a single GitHub issue through the complete self-healing loop.
        
        Args:
            issue_number: The GitHub issue number to process
            target_file_override: Optional override for target file path
            
        Returns:
            AgentResult with outcome details
        """
        self._reset_state()
        self._state.status = "analyzing"
        
        # Fetch the issue
        self._state.add_log(f"Fetching issue #{issue_number}")
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
        self._state.add_log(f"Issue: {issue.title}")
        
        # Identify target file
        if target_file_override:
            self._state.target_file = target_file_override
        else:
            self._state.target_file = self._identify_target_file(issue)
        
        if not self._state.target_file:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file="unknown",
                error="Could not identify target file to fix",
                logs=self._state.logs
            )
        
        self._state.add_log(f"Target file: {self._state.target_file}")
        
        # Get RAG context
        self._state.add_log("Retrieving codebase context via RAG...")
        error_message = "\n".join(issue.error_messages) if issue.error_messages else "See issue description"
        target_content, dependencies = self.faiss.get_context_for_fix(
            target_file=self._state.target_file,
            error_message=error_message,
            issue_description=issue.body
        )
        
        self._state.original_code = target_content
        self._state.context_dependencies = dependencies
        
        if not target_content:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file=self._state.target_file,
                error="Could not read target file content",
                logs=self._state.logs
            )
        
        self._state.add_log(f"Retrieved {len(dependencies)} dependency contexts")
        
        # Build context for LLM
        context_message = self._build_context_message(
            target_content=target_content,
            dependencies=dependencies,
            error_message=error_message,
            issue_description=issue.body,
            file_path=self._state.target_file
        )
        
        # Self-healing loop
        self._state.status = "patching"
        while self._state.attempts < self._state.max_attempts:
            self._state.attempts += 1
            self._state.add_log(f"Attempt {self._state.attempts} of {self._state.max_attempts}")
            
            # Call LLM
            is_retry = self._state.attempts > 1
            llm_response = self._call_llm(context_message, is_retry=is_retry)
            
            if llm_response is None:
                self._state.add_log("LLM failed to generate valid response")
                continue
            
            self._state.llm_response = llm_response
            
            # Extract patched code
            patched_code = self._validate_patch(llm_response.get("patches", {}))
            
            if not patched_code:
                self._state.add_log("No valid patch in LLM response")
                continue
            
            self._state.patched_code = patched_code
            self._state.add_log(f"Generated patch ({len(patched_code)} chars)")
            
            # Test in sandbox
            self._state.status = "testing"
            self._state.add_log("Running compilation test in Docker sandbox...")
            sandbox_result = self._run_sandbox_test(patched_code)
            self._state.last_sandbox_result = sandbox_result
            
            if sandbox_result.success:
                self._state.add_log("Compilation test PASSED")
                break
            else:
                self._state.add_log(f"Compilation test FAILED: {sandbox_result.error_message[:200]}")
                if self._state.attempts < self._state.max_attempts:
                    self._state.add_log("Will retry with error feedback...")
        
        # Check if we have a successful patch
        if not self._state.patched_code or not self._state.last_sandbox_result or not self._state.last_sandbox_result.success:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=issue_number,
                target_file=self._state.target_file,
                error="Failed to generate working patch after all attempts",
                attempts_used=self._state.attempts,
                logs=self._state.logs
            )
        
        # Security review
        self._state.status = "reviewing"
        self._state.add_log("Running OWASP security review...")
        security_audit, is_secure = self._evaluate_security(self._state.llm_response or {})
        
        self._state.add_log(f"Security review complete: {'SECURE' if is_secure else 'CONCERNS FOUND'}")
        
        # Create PR
        self._state.status = "creating_pr"
        self._state.add_log("Creating pull request...")
        
        explanation = (self._state.llm_response or {}).get("explanation", "Automated fix by LogicFlow")
        
        pr_result = self.github.create_pull_request(
            issue_id=issue_number,
            explanation=explanation,
            fixed_code=self._state.patched_code,
            file_path=self._state.target_file
        )
        
        self._state.pr_result = pr_result
        
        if pr_result.success:
            self._state.add_log(f"PR created: {pr_result.pr_url}")
            self._state.status = "completed"
        else:
            self._state.add_log(f"PR creation issue: {pr_result.error}")
            if pr_result.fallback_git_args:
                self._state.add_log("Fallback git commands generated")
            self._state.status = "completed"  # Still considered success if we have the patch
        
        return AgentResult(
            success=True,
            issue_number=issue_number,
            target_file=self._state.target_file,
            pr_url=pr_result.pr_url,
            branch_name=pr_result.branch_name,
            explanation=explanation,
            security_audit=security_audit,
            is_secure=is_secure,
            attempts_used=self._state.attempts,
            fallback_git_args=pr_result.fallback_git_args,
            logs=self._state.logs
        )
    
    def process_issue_from_raw(
        self,
        issue_title: str,
        issue_body: str,
        error_messages: List[str],
        target_file: str,
        original_code: str,
        dependencies: Optional[Dict[str, str]] = None
    ) -> AgentResult:
        """
        Process an issue from raw data (useful for VS Code extension integration).
        
        Args:
            issue_title: Title/description of the issue
            issue_body: Full issue description
            error_messages: List of error messages
            target_file: Path to the file to fix
            original_code: Original file content
            dependencies: Optional trimmed dependencies
            
        Returns:
            AgentResult with outcome details
        """
        self._reset_state()
        self._state.status = "analyzing"
        
        # Create a synthetic issue
        self._state.issue = GitHubIssue(
            id=0,
            number=0,
            title=issue_title,
            body=issue_body,
            state="open",
            labels=[],
            error_messages=error_messages
        )
        
        self._state.target_file = target_file
        self._state.original_code = original_code
        self._state.context_dependencies = dependencies or {}
        
        self._state.add_log(f"Processing local issue: {issue_title}")
        self._state.add_log(f"Target file: {target_file}")
        
        # Build context for LLM
        error_message = "\n".join(error_messages) if error_messages else "See issue description"
        context_message = self._build_context_message(
            target_content=original_code,
            dependencies=self._state.context_dependencies,
            error_message=error_message,
            issue_description=issue_body,
            file_path=target_file
        )
        
        # Self-healing loop
        self._state.status = "patching"
        while self._state.attempts < self._state.max_attempts:
            self._state.attempts += 1
            self._state.add_log(f"Attempt {self._state.attempts} of {self._state.max_attempts}")
            
            is_retry = self._state.attempts > 1
            llm_response = self._call_llm(context_message, is_retry=is_retry)
            
            if llm_response is None:
                continue
            
            self._state.llm_response = llm_response
            patched_code = self._validate_patch(llm_response.get("patches", {}))
            
            if not patched_code:
                continue
            
            self._state.patched_code = patched_code
            self._state.add_log(f"Generated patch ({len(patched_code)} chars)")
            
            # Test in sandbox
            self._state.status = "testing"
            sandbox_result = self._run_sandbox_test(patched_code)
            self._state.last_sandbox_result = sandbox_result
            
            if sandbox_result.success:
                self._state.add_log("Compilation test PASSED")
                break
            else:
                self._state.add_log(f"Compilation test FAILED")
                if self._state.attempts < self._state.max_attempts:
                    self._state.add_log("Will retry with error feedback...")
        
        # Check results
        if not self._state.patched_code:
            self._state.status = "failed"
            return AgentResult(
                success=False,
                issue_number=0,
                target_file=target_file,
                error="Failed to generate patch",
                attempts_used=self._state.attempts,
                logs=self._state.logs
            )
        
        # Security review
        self._state.status = "reviewing"
        security_audit, is_secure = self._evaluate_security(self._state.llm_response or {})
        
        explanation = (self._state.llm_response or {}).get("explanation", "Automated fix")
        
        self._state.status = "completed"
        return AgentResult(
            success=True,
            issue_number=0,
            target_file=target_file,
            explanation=explanation,
            security_audit=security_audit,
            is_secure=is_secure,
            attempts_used=self._state.attempts,
            logs=self._state.logs
        )
    
    def get_state(self) -> AgentState:
        """Get current agent state."""
        return self._state
    
    def get_patched_code(self) -> Optional[str]:
        """Get the patched code from the last run."""
        return self._state.patched_code