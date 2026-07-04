import argparse
import logging
import sys
from typing import Optional

from config import LogicFlowConfig, get_config, reset_config
from agents.core import LogicFlowAgent, AgentResult
from tools.faiss_tool import FaissIndexer  # ADD THIS LINE

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
    print("LOGICFLOW RESULT")
    print("=" * 60)
    
    print(f"\nSuccess: {result.success}")
    print(f"Issue: #{result.issue_number}")
    print(f"Target File: {result.target_file}")
    print(f"Attempts Used: {result.attempts_used}")
    
    if result.pr_url:
        print(f"Pull Request: {result.pr_url}")
    
    if result.branch_name:
        print(f"Branch: {result.branch_name}")
    
    print(f"\nSecure: {result.is_secure}")
    
    if result.explanation:
        print(f"\nExplanation:\n{result.explanation}")
    
    if result.error:
        print(f"\nError: {result.error}")
    
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
    """Handle 'fix' command."""
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
            print(f"  Models: {', '.join(models)}")
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
    from dashboard.streamlit_app import run_dashboard
    run_dashboard()


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
    
    # Fix command
    fix_parser = subparsers.add_parser("fix", help="Fix an issue")
    fix_parser.add_argument("issue", type=int, help="GitHub issue number")
    fix_parser.add_argument("--file", "-f", help="Override target file path")
    
    # Status command
    subparsers.add_parser("status", help="Check system status")
    
    # Dashboard command
    subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    
    args = parser.parse_args()
    
    if args.command == "index":
        cmd_index(args)
    elif args.command == "fix":
        cmd_fix(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()