"""
LogicFlow GitHub Integration Tool
Handles issue extraction, branch management, and pull request creation.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

from config import LogicFlowConfig, get_config

logger = logging.getLogger("LogicFlow.github_tool")


@dataclass
class GitHubIssue:
    """Parsed GitHub issue with extracted metadata."""
    id: int
    number: int
    title: str
    body: str
    state: str
    labels: List[str]
    referenced_files: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    code_snippets: List[str] = field(default_factory=list)
    created_at: str = ""
    html_url: str = ""


@dataclass
class PullRequestResult:
    """Result of pull request creation."""
    success: bool
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    error: Optional[str] = None
    fallback_git_args: Optional[Dict[str, Any]] = None


class GitHubManager:
    """
    Manages GitHub operations including issue fetching and PR creation.
    Implements graceful degradation when API is unavailable.
    """
    
    # Patterns for extracting file references from issues
    FILE_PATTERNS = [
        r'(?:file|path|in|at)\s+[`"\']?([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)[`"\']?',
        r'([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)(?:\s+on line\s+\d+|\s*:\d+)',
        r'[`"\']([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)[`"\']',
        r'\b(src|lib|app|tests|cmd|pkg|internal)/[a-zA-Z0-9_/.-]+\.[a-zA-Z]+',
    ]
    
    # Patterns for extracting error messages
    ERROR_PATTERNS = [
        r'(?:error|Error|ERROR)[:\s]+(.+?)(?:\n|$)',
        r'(?:exception|Exception|EXCEPTION)[:\s]+(.+?)(?:\n|$)',
        r'(?:Traceback|traceback)[\s\S]*?(\w+Error:.+?)(?:\n\n|\n$)',
        r'(?:panic|PANIC)[:\s]+(.+?)(?:\n|$)',
        r'(?:fatal|FATAL)[:\s]+(.+?)(?:\n|$)',
    ]
    
    def __init__(self, config: Optional[LogicFlowConfig] = None):
        self.config = config or get_config()
        self._github_client = None
        self._repo = None
    
    def _get_client(self):
        """Lazy-initialize GitHub client."""
        if self._github_client is None:
            try:
                from github import Github
                self._github_client = Github(self.config.github.token)
                logger.info("GitHub client initialized")
            except ImportError:
                logger.error("PyGithub not installed. Run: pip install PyGithub")
                return None
            except Exception as e:
                logger.error(f"Failed to initialize GitHub client: {e}")
                return None
        return self._github_client
    
    def _get_repo(self):
        """Get GitHub repository object."""
        if self._repo is None:
            client = self._get_client()
            if client is None:
                return None
            
            if not self.config.github.repo:
                logger.error("GitHub repository not configured")
                return None
            
            try:
                self._repo = client.get_repo(self.config.github.repo)
                logger.info(f"Connected to repository: {self.config.github.repo}")
            except Exception as e:
                logger.error(f"Failed to access repository: {e}")
                return None
        
        return self._repo
    
    def _extract_files_from_text(self, text: str) -> List[str]:
        """Extract file path references from text."""
        files = set()
        for pattern in self.FILE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                # Clean up the match
                clean_path = match.strip("`'\" \t")
                if clean_path and "/" in clean_path or "." in clean_path:
                    files.add(clean_path)
        return list(files)
    
    def _extract_errors_from_text(self, text: str) -> List[str]:
        """Extract error messages from text."""
        errors = []
        for pattern in self.ERROR_PATTERNS:
            matches = re.findall(pattern, text, re.MULTILINE)
            errors.extend([m.strip() for m in matches if m.strip()])
        return errors[:5]  # Limit to 5 most relevant errors
    
    def _extract_code_snippets(self, text: str) -> List[str]:
        """Extract code blocks from markdown text."""
        pattern = r'```(?:\w+)?\n([\s\S]*?)```'
        matches = re.findall(pattern, text)
        return [m.strip() for m in matches if m.strip()]
    
    def _parse_issue(self, issue) -> GitHubIssue:
        """Convert GitHub issue object to our internal representation."""
        body = issue.body or ""
        
        return GitHubIssue(
            id=issue.id,
            number=issue.number,
            title=issue.title,
            body=body,
            state=issue.state,
            labels=[label.name for label in issue.labels],
            referenced_files=self._extract_files_from_text(body),
            error_messages=self._extract_errors_from_text(body),
            code_snippets=self._extract_code_snippets(body),
            created_at=issue.created_at.isoformat() if issue.created_at else "",
            html_url=issue.html_url
        )
    
    def fetch_open_issues(
        self,
        limit: int = 50,
        labels: Optional[List[str]] = None
    ) -> List[GitHubIssue]:
        """
        Fetch open issues from the configured repository.
        
        Args:
            limit: Maximum number of issues to fetch
            labels: Optional list of labels to filter by
            
        Returns:
            List of parsed GitHubIssue objects
        """
        repo = self._get_repo()
        if repo is None:
            logger.error("Cannot fetch issues: repository not available")
            return []
        
        issues = []
        try:
            if labels:
                label_query = " ".join([f'label:"{l}"' for l in labels])
                github_issues = repo.get_issues(
                    state="open",
                    labels=labels
                )
            else:
                github_issues = repo.get_issues(state="open")
            
            for issue in github_issues[:limit]:
                # Skip pull requests (they appear in issues list)
                if issue.pull_request is not None:
                    continue
                
                parsed = self._parse_issue(issue)
                issues.append(parsed)
            
            logger.info(f"Fetched {len(issues)} open issues")
            
        except Exception as e:
            logger.error(f"Failed to fetch issues: {e}")
        
        return issues
    
    def fetch_issue_by_number(self, issue_number: int) -> Optional[GitHubIssue]:
        """Fetch a specific issue by its number."""
        repo = self._get_repo()
        if repo is None:
            return None
        
        try:
            issue = repo.get_issue(issue_number)
            return self._parse_issue(issue)
        except Exception as e:
            logger.error(f"Failed to fetch issue #{issue_number}: {e}")
            return None
    
    def _create_branch_name(self, issue_number: int) -> str:
        """Generate a branch name for the fix."""
        safe_prefix = self.config.github.branch_prefix.replace("/", "-")
        return f"{safe_prefix}-{issue_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def _get_default_branch(self) -> Optional[str]:
        """Get the default branch of the repository."""
        repo = self._get_repo()
        if repo is None:
            return self.config.github.base_branch
        
        try:
            return repo.default_branch
        except Exception:
            return self.config.github.base_branch
    
    def create_pull_request(
        self,
        issue_id: int,
        explanation: str,
        fixed_code: str,
        file_path: str,
        additional_files: Optional[Dict[str, str]] = None
    ) -> PullRequestResult:
        """
        Create a pull request with the fixed code.
        
        Args:
            issue_id: The GitHub issue number being fixed
            explanation: Explanation of the fix (used in PR body)
            fixed_code: The patched code content
            file_path: Path to the fixed file in the repository
            additional_files: Optional dict of other files to include
            
        Returns:
            PullRequestResult with PR URL or fallback git arguments
        """
        repo = self._get_repo()
        
        if repo is None:
            logger.warning("GitHub API unavailable, returning fallback git args")
            return self._create_fallback_result(issue_id, explanation, fixed_code, file_path)
        
        branch_name = self._create_branch_name(issue_id)
        base_branch = self._get_default_branch()
        
        try:
            # Get the base branch SHA
            base_ref = repo.get_git_ref(f"heads/{base_branch}")
            base_sha = base_ref.object.sha
            
            # Create new branch
            repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
            logger.info(f"Created branch: {branch_name}")
            
            # Commit the fixed file
            all_files = {file_path: fixed_code}
            if additional_files:
                all_files.update(additional_files)
            
            commit_sha = None
            for fp, content in all_files.items():
                try:
                    # Try to get existing file to preserve SHA
                    existing_file = repo.get_contents(fp, ref=branch_name)
                    if isinstance(existing_file, list):
                        existing_file = existing_file[0]
                    repo.update_file(
                        path=fp,
                        message=f"fix: resolve issue #{issue_id} in {fp}",
                        content=content,
                        sha=existing_file.sha,
                        branch=branch_name
                    )
                except Exception:
                    # File doesn't exist, create it
                    repo.create_file(
                        path=fp,
                        message=f"fix: resolve issue #{issue_id} - create {fp}",
                        content=content,
                        branch=branch_name
                    )
                
                # Get latest commit SHA
                try:
                    branch_ref = repo.get_git_ref(f"heads/{branch_name}")
                    commit_sha = branch_ref.object.sha
                except Exception:
                    pass
            
            # Create pull request
            pr_title = f"{self.config.github.pr_title_prefix} #{issue_id}"
            pr_body = self._format_pr_body(issue_id, explanation, file_path)
            
            pr = repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=branch_name,
                base=base_branch
            )
            
            logger.info(f"Created PR: {pr.html_url}")
            
            # Add label if possible
            try:
                pr.add_to_labels("automated", "logicflow")
            except Exception:
                pass
            
            return PullRequestResult(
                success=True,
                pr_url=pr.html_url,
                branch_name=branch_name,
                commit_sha=commit_sha
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to create PR: {error_msg}")
            
            # Check for rate limit or auth errors
            if "rate limit" in error_msg.lower() or "403" in error_msg or "401" in error_msg:
                return self._create_fallback_result(issue_id, explanation, fixed_code, file_path, error_msg)
            
            return PullRequestResult(
                success=False,
                error=error_msg,
                branch_name=branch_name
            )
    
    def _format_pr_body(self, issue_id: int, explanation: str, file_path: str) -> str:
        """Format the pull request body."""
        return f"""## Summary

This PR automatically resolves issue #{issue_id}.

### Changes Made
- Modified: `{file_path}`

### Fix Explanation
{explanation}

### Generated by
LogicFlow (The Digital Archeologist) - Autonomous AI Coding Agent

---
Closes #{issue_id}
"""
    
    def _create_fallback_result(
        self,
        issue_id: int,
        explanation: str,
        fixed_code: str,
        file_path: str,
        error: Optional[str] = None
    ) -> PullRequestResult:
        """
        Create fallback result with git command arguments
        for when GitHub API is unavailable.
        """
        branch_name = self._create_branch_name(issue_id)
        base_branch = self._get_default_branch()
        
        return PullRequestResult(
            success=False,
            error=error or "GitHub API unavailable",
            fallback_git_args={
                "branch_name": branch_name,
                "base_branch": base_branch,
                "file_path": file_path,
                "commit_message": f"fix: resolve issue #{issue_id} in {file_path}",
                "pr_title": f"{self.config.github.pr_title_prefix} #{issue_id}",
                "pr_body": self._format_pr_body(issue_id, explanation, file_path),
                "code_content": fixed_code,
                "commands": [
                    f"git checkout {base_branch}",
                    f"git checkout -b {branch_name}",
                    f"mkdir -p $(dirname {file_path})",
                    f"cat > {file_path} << 'LOGICFLOW_EOF'\n{fixed_code}\nLOGICFLOW_EOF",
                    f"git add {file_path}",
                    f"git commit -m 'fix: resolve issue #{issue_id} in {file_path}'",
                    f"git push origin {branch_name}",
                    f"# Then create PR via GitHub UI or gh CLI:",
                    f"gh pr create --title '{self.config.github.pr_title_prefix} #{issue_id}' --body '{explanation[:200]}' --base {base_branch} --head {branch_name}"
                ]
            }
        )
    
    def is_configured(self) -> Tuple[bool, str]:
        """Check if GitHub integration is properly configured."""
        if not self.config.github.token:
            return False, "GITHUB_TOKEN not set"
        if not self.config.github.repo:
            return False, "GITHUB_REPO not set (format: owner/repo)"
        
        # Test connection
        repo = self._get_repo()
        if repo is None:
            return False, "Could not connect to repository"
        
        return True, f"Connected to {self.config.github.repo}"