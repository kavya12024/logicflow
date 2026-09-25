import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from config import LogicFlowConfig, get_config, reset_config
from agents.core import LogicFlowAgent, AgentResult
from tools.faiss_tool import FaissIndexer

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)

logger = logging.getLogger("LogicFlow")


def print_result(result: AgentResult) -> None:
    """Pretty-print the agent result."""
    print("\n" + "=" * 60)
    print("LOGICFLOW EXECUTION RESULT")
    print("=" * 60)
    
    print(f"\nStatus: {'SUCCESS' if result.success else 'FAILED'}")
    if result.issue_number > 0:
        print(f"Issue: #{result.issue_number}")
    print(f"Target File: {result.target_file}")
    if result.target_function:
        print(f"Surgical Target Function: {result.target_function}")
    print(f"Attempts Used: {result.attempts_used}")
    print(f"Tests Passed: {'YES' if result.test_passed else 'NO'}")
    
    if result.pr_url:
        print(f"Pull Request: {result.pr_url}")
    
    if result.branch_name:
        print(f"Branch: {result.branch_name}")
    
    print(f"Secure: {'YES' if result.is_secure else 'SECURITY CONCERNS DETECTED'}")
    
    if result.explanation:
        print(f"\nExplanation:\n{result.explanation}")
    
    if result.error:
        print(f"\nError:\n{result.error}")
    
    if result.fallback_git_args:
        print("\nFallback Git Commands:")
        for cmd in result.fallback_git_args.get("commands", []):
            print(f"  {cmd}")
    
    print("\n" + "-" * 60)
    print("Execution Logs:")
    print("-" * 60)
    for log in result.logs:
        print(f"  {log}")
    
    print("=" * 60 + "\n")


def cmd_index(args) -> None:
    """Handle 'index' command."""
    config = get_config()
    if args.workspace:
        config.workspace.demo_dir = args.workspace
    if args.output:
        config.faiss.index_path = args.output
    
    agent = LogicFlowAgent(config)
    
    if agent.initialize_index(force_rebuild=not args.load):
        logger.info("Index ready for use")
        stats = agent.faiss.get_stats()
        logger.info(f"Stats: {stats}")
    else:
        logger.error("Failed to initialize index")
        sys.exit(1)


def cmd_fix(args) -> None:
    """Handle 'fix' command for GitHub issues."""
    config = get_config()
    agent = LogicFlowAgent(config)
    
    # Initialize index
    if not agent.initialize_index(force_rebuild=False):
        if not agent.initialize_index(force_rebuild=True):
            logger.error("Cannot proceed without index")
            sys.exit(1)
    
    # Process the issue
    result = agent.process_issue(
        issue_number=args.issue,
        target_file_override=args.file
    )
    
    print_result(result)
    sys.exit(0 if result.success else 1)


def cmd_test_and_fix(args) -> None:
    """
    Handle 'test-and-fix' command.
    Autonomously runs tests in workspace, detects failures, and repairs the code.
    """
    config = get_config()
    if args.workspace:
        config.workspace.demo_dir = args.workspace
        
    agent = LogicFlowAgent(config)
    
    print("\n" + "=" * 60)
    print("LOGICFLOW AUTONOMOUS TEST & REPAIR")
    print(f"Workspace: {config.workspace.demo_dir}")
    if args.test:
        print(f"Target Test: {args.test}")
    print("=" * 60 + "\n")
    
    result = agent.process_autonomous_test_and_fix(
        test_file=args.test,
        workspace_dir=config.workspace.demo_dir
    )
    
    print_result(result)
    sys.exit(0 if result.success else 1)


def cmd_fix_local(args) -> None:
    """
    Handle 'fix-local' command.
    Directly repairs a local file with a given error message or trace without GitHub.
    """
    config = get_config()
    if args.workspace:
        config.workspace.demo_dir = args.workspace
        
    agent = LogicFlowAgent(config)
    
    print("\n" + "=" * 60)
    print("LOGICFLOW LOCAL FILE REPAIR")
    print(f"Target File: {args.file}")
    print("=" * 60 + "\n")
    
    result = agent.process_local_fix(
        target_file=args.file,
        error_message=args.error,
        test_file=args.test,
        workspace_dir=config.workspace.demo_dir
    )
    
    print_result(result)
    sys.exit(0 if result.success else 1)


def cmd_fix_code(args) -> None:
    """
    Handle 'fix-code' command.
    Auto-detects errors and repairs a complete code file or snippet.
    """
    config = get_config()
    agent = LogicFlowAgent(config)
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)
        
    code_content = file_path.read_text(encoding="utf-8", errors="ignore")
    
    print("\n" + "=" * 60)
    print("LOGICFLOW CODE AUTO-REPAIR")
    print(f"File: {args.file} ({len(code_content.splitlines())} lines)")
    print("=" * 60 + "\n")
    
    result = agent.process_code_snippet(
        code_snippet=code_content,
        error_message=args.error,
        filename=file_path.name,
        auto_save=args.save
    )
    
    print_result(result)
    if result.success and not args.save:
        patched = agent.get_patched_code()
        if patched:
            print("\n" + "=" * 25 + " FIXED CODE PREVIEW " + "=" * 25)
            print(patched)
            print("=" * 70)
            print("\nTip: Pass --save to write the fix directly to the file.")
            
    sys.exit(0 if result.success else 1)


def cmd_status(args) -> None:
    """Handle 'status' command."""
    import httpx
    from tools.docker_test_tool import DockerSandbox
    from tools.github_tool import GitHubManager
    
    config = get_config()
    
    print("\nLogicFlow System Status")
    print("=" * 40)
    
    # Check Ollama
    print("\n[Ollama]")
    try:
        response = httpx.get(
            f"{config.ollama.base_url.replace('/v1', '')}/api/tags",
            timeout=5.0
        )
        if response.status_code == 200:
            models = [m.get("name", "unknown") for m in response.json().get("models", [])]
            print(f"  Status: Connected")
            print(f"  Active Model: {config.ollama.model}")
            print(f"  Installed Models: {', '.join(models)}")
        else:
            print(f"  Status: Error ({response.status_code})")
    except Exception as e:
        print(f"  Status: Unavailable ({e})")
    
    # Check Docker
    print("\n[Docker]")
    sandbox = DockerSandbox(config)
    available, msg = sandbox.check_docker_available()
    print(f"  Status: {'Available' if available else 'Unavailable'}")
    if not available:
        print(f"  Message: {msg}")
    
    # Check GitHub
    print("\n[GitHub]")
    github = GitHubManager(config)
    configured, msg = github.is_configured()
    print(f"  Status: {'Configured' if configured else 'Not Configured'}")
    print(f"  Message: {msg}")
    
    # Check Index
    print("\n[FAISS Index]")
    indexer = FaissIndexer(config)
    if indexer.load_index():
        stats = indexer.get_stats()
        print(f"  Status: Loaded")
        print(f"  Chunks: {stats['total_chunks']}")
        print(f"  Files: {stats['unique_files']}")
        print(f"  Languages: {', '.join(stats['languages'])}")
    else:
        print(f"  Status: Not Found")
    
    print()


def cmd_dashboard(args) -> None:
    """Handle 'dashboard' command."""
    dashboard_path = Path(__file__).parent / "dashboard" / "streamlit_app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LogicFlow - The Digital Archeologist: Autonomous AI Coding Agent"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Index command
    index_parser = subparsers.add_parser("index", help="Build or load FAISS index")
    index_parser.add_argument("--workspace", "-w", help="Workspace directory to index")
    index_parser.add_argument("--output", "-o", help="Output path for index")
    index_parser.add_argument("--load", "-l", action="store_true", help="Load existing index instead of building")
    
    # Fix command (GitHub issues)
    fix_parser = subparsers.add_parser("fix", help="Fix a GitHub issue")
    fix_parser.add_argument("issue", type=int, help="GitHub issue number")
    fix_parser.add_argument("--file", "-f", help="Override target file path")
    
    # Autonomous Test-and-Fix command
    auto_parser = subparsers.add_parser(
        "test-and-fix",
        help="Autonomously detect errors by running tests in the workspace and repair them"
    )
    auto_parser.add_argument("--test", "-t", help="Optional specific test file name (e.g. test_calc.py)")
    auto_parser.add_argument("--workspace", "-w", help="Workspace directory (defaults to configured workspace)")
    
    # Local file fix command
    local_parser = subparsers.add_parser(
        "fix-local",
        help="Fix a local file directly with an error message or trace (no GitHub issue required)"
    )
    local_parser.add_argument("--file", "-f", required=True, help="Path to target file in workspace")
    local_parser.add_argument("--error", "-e", required=True, help="Error message, assertion failure, or traceback")
    local_parser.add_argument("--test", "-t", help="Optional test file to verify against")
    local_parser.add_argument("--workspace", "-w", help="Workspace directory")
    
    # Full Code Auto-Repair command
    code_parser = subparsers.add_parser(
        "fix-code",
        help="Auto-detect errors and repair a full code file or snippet"
    )
    code_parser.add_argument("--file", "-f", required=True, help="Path to code file to repair")
    code_parser.add_argument("--error", "-e", default=None, help="Optional error message or hints")
    code_parser.add_argument("--save", "-s", action="store_true", help="Save fixed code back to file on success")

    # Status command
    subparsers.add_parser("status", help="Check system status")
    
    # Dashboard command
    subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    
    args = parser.parse_args()
    
    if args.command == "index":
        cmd_index(args)
    elif args.command == "fix":
        cmd_fix(args)
    elif args.command == "test-and-fix":
        cmd_test_and_fix(args)
    elif args.command == "fix-local":
        cmd_fix_local(args)
    elif args.command == "fix-code":
        cmd_fix_code(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()