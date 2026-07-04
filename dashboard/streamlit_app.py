"""
LogicFlow Streamlit Dashboard
Visual operational manager for the LogicFlow agent.
"""

import os
import sys
import logging

# Mute all verbose logging before any imports
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("tokenizers").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("faiss").setLevel(logging.WARNING)
logging.getLogger("github").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.ERROR)

import streamlit as st
from typing import Optional, List, Dict, Any

from config import LogicFlowConfig, get_config, reset_config
from tools.faiss_tool import FaissIndexer
from tools.docker_test_tool import DockerSandbox
from tools.github_tool import GitHubManager
from agents.core import LogicFlowAgent, AgentResult

# Configure Streamlit page
st.set_page_config(
    page_title="LogicFlow - The Digital Archeologist",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for cleaner look (no emojis)
st.markdown("""
<style>
    .stApp {
        font-family: 'Segoe UI', -apple-system, sans-serif;
    }
    .success-box {
        padding: 10px;
        border-radius: 4px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .error-box {
        padding: 10px;
        border-radius: 4px;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .info-box {
        padding: 10px;
        border-radius: 4px;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
    }
    .warning-box {
        padding: 10px;
        border-radius: 4px;
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
    }
    div[data-testid="stSidebar"] {
        background-color: #f8f9fa;
    }
    .log-container {
        max-height: 400px;
        overflow-y: auto;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        background-color: #1e1e1e;
        color: #d4d4d4;
        padding: 10px;
        border-radius: 4px;
    }
    .log-entry {
        margin-bottom: 2px;
        padding: 2px 0;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session_state() -> None:
    """Initialize Streamlit session state variables."""
    if "agent" not in st.session_state:
        st.session_state.agent = None
    if "config" not in st.session_state:
        st.session_state.config = get_config()
    if "issues" not in st.session_state:
        st.session_state.issues = []
    if "indexed_files" not in st.session_state:
        st.session_state.indexed_files = []
    if "logs" not in st.session_state:
        st.session_state.logs = []
    if "result" not in st.session_state:
        st.session_state.result = None
    if "index_built" not in st.session_state:
        st.session_state.index_built = False
    if "docker_available" not in st.session_state:
        st.session_state.docker_available = None
    if "github_configured" not in st.session_state:
        st.session_state.github_configured = None


def render_sidebar() -> LogicFlowConfig:
    """Render the sidebar configuration panel."""
    st.sidebar.title("Configuration")
    
    config = st.session_state.config
    
    with st.sidebar.expander("Ollama Settings", expanded=False):
        config.ollama.base_url = st.text_input(
            "Ollama Base URL",
            value=config.ollama.base_url,
            key="ollama_url"
        )
        config.ollama.model = st.text_input(
            "Model Name",
            value=config.ollama.model,
            key="ollama_model"
        )
        config.ollama.request_timeout = st.number_input(
            "Request Timeout (s)",
            min_value=60,
            max_value=600,
            value=int(config.ollama.request_timeout),
            key="ollama_timeout"
        )
    
    with st.sidebar.expander("Workspace Settings", expanded=False):
        config.workspace.demo_dir = st.text_input(
            "Workspace Directory",
            value=config.workspace.demo_dir,
            key="workspace_dir"
        )
        config.faiss.index_path = st.text_input(
            "FAISS Index Path",
            value=config.faiss.index_path,
            key="faiss_path"
        )
        config.faiss.chunk_size = st.number_input(
            "Chunk Size",
            min_value=128,
            max_value=2048,
            value=config.faiss.chunk_size,
            step=64,
            key="chunk_size"
        )
    
    with st.sidebar.expander("GitHub Settings", expanded=False):
        config.github.token = st.text_input(
            "GitHub Token",
            value=config.github.token,
            type="password",
            key="github_token"
        )
        config.github.repo = st.text_input(
            "Repository (owner/repo)",
            value=config.github.repo,
            key="github_repo"
        )
        config.github.base_branch = st.text_input(
            "Base Branch",
            value=config.github.base_branch,
            key="github_branch"
        )
    
    with st.sidebar.expander("Docker Settings", expanded=False):
        config.docker.timeout_seconds = st.number_input(
            "Timeout (s)",
            min_value=30,
            max_value=300,
            value=config.docker.timeout_seconds,
            key="docker_timeout"
        )
        config.docker.network_disabled = st.checkbox(
            "Disable Network",
            value=config.docker.network_disabled,
            key="docker_network"
        )
    
    if st.sidebar.button("Apply Configuration", type="primary"):
        reset_config()
        st.session_state.config = config
        st.session_state.agent = None
        st.session_state.index_built = False
        st.rerun()
    
    st.sidebar.divider()
    return config


def render_indexing_section(config: LogicFlowConfig) -> None:
    """Render the repository indexing controls."""
    st.header("Repository Indexing")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Build New Index", type="primary"):
            with st.spinner("Building FAISS index..."):
                agent = get_or_create_agent(config)
                if agent.initialize_index(force_rebuild=True):
                    st.session_state.index_built = True
                    st.session_state.indexed_files = agent.faiss.get_indexed_files()
                    st.success(f"Index built with {len(st.session_state.indexed_files)} files")
                else:
                    st.error("Failed to build index. Check workspace directory.")
    
    with col2:
        if st.button("Load Existing Index"):
            agent = get_or_create_agent(config)
            if agent.initialize_index(force_rebuild=False):
                st.session_state.index_built = True
                st.session_state.indexed_files = agent.faiss.get_indexed_files()
                st.success(f"Loaded index with {len(st.session_state.indexed_files)} files")
            else:
                st.warning("No existing index found. Build a new one.")
    
    with col3:
        if st.button("Check Index Stats"):
            if st.session_state.index_built:
                agent = get_or_create_agent(config)
                stats = agent.faiss.get_stats()
                st.json(stats)
            else:
                st.info("No index loaded")
    
    if st.session_state.indexed_files:
        with st.expander("Indexed Files"):
            for f in sorted(st.session_state.indexed_files):
                st.code(f, language=None)


def render_issue_selection(config: LogicFlowConfig) -> Optional[int]:
    """Render the issue selection dropdown."""
    st.header("Issue Selection")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if not config.github.token or not config.github.repo:
            st.warning("Configure GitHub settings to fetch issues")
            return None
        
        if st.button("Fetch Open Issues"):
            with st.spinner("Fetching issues from GitHub..."):
                github_mgr = GitHubManager(config)
                st.session_state.issues = github_mgr.fetch_open_issues(limit=50)
                
                if not st.session_state.issues:
                    st.info("No open issues found")
                else:
                    st.success(f"Fetched {len(st.session_state.issues)} issues")
    
    with col2:
        issue_num = st.number_input(
            "Or enter issue #",
            min_value=1,
            value=1,
            key="manual_issue_num"
        )
        if st.button("Use This Issue"):
            return issue_num
    
    if st.session_state.issues:
        issue_options = [
            f"#{i.number} - {i.title[:60]}{'...' if len(i.title) > 60 else ''}"
            for i in st.session_state.issues
        ]
        
        selected_idx = st.selectbox(
            "Select an issue",
            range(len(issue_options)),
            format_func=lambda x: issue_options[x],
            key="issue_select"
        )
        
        # Show issue details
        selected_issue = st.session_state.issues[selected_idx]
        
        with st.expander("Issue Details"):
            st.write(f"**Title:** {selected_issue.title}")
            st.write(f"**State:** {selected_issue.state}")
            if selected_issue.labels:
                st.write(f"**Labels:** {', '.join(selected_issue.labels)}")
            if selected_issue.referenced_files:
                st.write("**Referenced Files:**")
                for f in selected_issue.referenced_files:
                    st.code(f)
            if selected_issue.error_messages:
                st.write("**Error Messages:**")
                for e in selected_issue.error_messages:
                    st.error(e)
            st.write("**Body:**")
            st.text(selected_issue.body[:2000] + ("..." if len(selected_issue.body) > 2000 else ""))
        
        return selected_issue.number
    
    return None


def render_target_file_override(config: LogicFlowConfig) -> Optional[str]:
    """Render optional target file override."""
    if st.session_state.indexed_files:
        with st.expander("Override Target File (Optional)"):
            return st.selectbox(
                "Select target file",
                ["Automatic Detection"] + sorted(st.session_state.indexed_files),
                key="target_file_override"
            )
    return None


def render_launch_section(config: LogicFlowConfig, issue_number: Optional[int], target_override: Optional[str]) -> None:
    """Render the main execution controls."""
    st.header("Execution")
    
    if not st.session_state.index_built:
        st.warning("Build or load an index before running LogicFlow")
        return
    
    if issue_number is None:
        st.info("Select an issue to process")
        return
    
    target_file = None
    if target_override and target_override != "Automatic Detection":
        target_file = target_override
    
    col1, col2 = st.columns(2)
    
    with col1:
        run_button = st.button(
            "Launch LogicFlow",
            type="primary",
            key="launch_button"
        )
    
    with col2:
        if st.button("Clear Logs", key="clear_logs"):
            st.session_state.logs = []
            st.session_state.result = None
    
    if run_button:
        execute_agent(config, issue_number, target_file)


def execute_agent(config: LogicFlowConfig, issue_number: int, target_file: Optional[str]) -> None:
    """Execute the LogicFlow agent with progress display."""
    st.session_state.logs = []
    st.session_state.result = None
    
    agent = get_or_create_agent(config)
    
    # Create a progress placeholder
    progress_container = st.empty()
    log_container = st.empty()
    
    with st.spinner("LogicFlow is working..."):
        result = agent.process_issue(
            issue_number=issue_number,
            target_file_override=target_file
        )
        
        st.session_state.result = result
        st.session_state.logs = result.logs


def render_log_stream() -> None:
    """Render the log output stream."""
    st.header("Execution Logs")
    
    logs = st.session_state.logs
    if not logs:
        st.info("No logs yet. Launch LogicFlow to see execution progress.")
        return
    
    log_html = '<div class="log-container">'
    for log_entry in logs:
        # Escape HTML
        safe_entry = log_entry.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        log_html += f'<div class="log-entry">{safe_entry}</div>'
    log_html += '</div>'
    
    st.markdown(log_html, unsafe_allow_html=True)


def render_results() -> None:
    """Render the execution results."""
    result: AgentResult = st.session_state.result
    
    if result is None:
        return
    
    st.header("Results")
    
    if result.success:
        st.markdown('<div class="success-box">Processing completed successfully</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="error-box">Processing failed: {result.error}</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Summary")
        st.write(f"**Issue:** #{result.issue_number}")
        st.write(f"**Target File:** `{result.target_file}`")
        st.write(f"**Attempts Used:** {result.attempts_used}")
        
        if result.pr_url:
            st.write(f"**Pull Request:** [{result.pr_url}]({result.pr_url})")
        if result.branch_name:
            st.write(f"**Branch:** `{result.branch_name}`")
    
    with col2:
        st.subheader("Security Status")
        if result.is_secure:
            st.markdown('<div class="success-box">Code passed security review</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warning-box">Security concerns identified</div>', unsafe_allow_html=True)
    
    if result.explanation:
        with st.expander("Fix Explanation"):
            st.write(result.explanation)
    
    if result.security_audit:
        with st.expander("Security Audit Details"):
            st.text(result.security_audit)
    
    if result.fallback_git_args:
        with st.expander("Fallback Git Commands"):
            st.warning("GitHub API unavailable. Use these commands manually:")
            for cmd in result.fallback_git_args.get("commands", []):
                st.code(cmd, language="bash")
    
    # Show patched code if available
    agent = st.session_state.agent
    if agent:
        patched = agent.get_patched_code()
        if patched:
            with st.expander("Patched Code"):
                st.code(patched, language="auto")


def render_status_checks(config: LogicFlowConfig) -> None:
    """Render system status checks."""
    st.header("System Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("Ollama")
        try:
            import httpx
            response = httpx.get(
                f"{config.ollama.base_url.replace('/v1', '')}/api/tags",
                timeout=5.0
            )
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "unknown") for m in models]
                st.markdown('<div class="success-box">Connected</div>', unsafe_allow_html=True)
                if model_names:
                    st.write("Available models:")
                    for name in model_names:
                        st.code(name)
            else:
                st.markdown('<div class="error-box">Connection failed</div>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<div class="error-box">Error: {str(e)[:100]}</div>', unsafe_allow_html=True)
    
    with col2:
        st.subheader("Docker")
        if st.session_state.docker_available is None:
            sandbox = DockerSandbox(config)
            available, msg = sandbox.check_docker_available()
            st.session_state.docker_available = available
            st.session_state.docker_msg = msg
        
        if st.session_state.docker_available:
            st.markdown('<div class="success-box">Available</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="error-box">{st.session_state.docker_msg}</div>', unsafe_allow_html=True)
    
    with col3:
        st.subheader("GitHub")
        if st.session_state.github_configured is None:
            github_mgr = GitHubManager(config)
            configured, msg = github_mgr.is_configured()
            st.session_state.github_configured = configured
            st.session_state.github_msg = msg
        
        if st.session_state.github_configured:
            st.markdown('<div class="success-box">Configured</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="warning-box">{st.session_state.github_msg}</div>', unsafe_allow_html=True)


def get_or_create_agent(config: LogicFlowConfig) -> LogicFlowAgent:
    """Get or create the LogicFlow agent instance."""
    if st.session_state.agent is None:
        st.session_state.agent = LogicFlowAgent(config)
    return st.session_state.agent


def run_dashboard() -> None:
    """Main entry point for the Streamlit dashboard."""
    initialize_session_state()
    
    config = render_sidebar()
    render_status_checks(config)
    
    st.divider()
    
    render_indexing_section(config)
    
    st.divider()
    
    issue_number = render_issue_selection(config)
    target_override = render_target_file_override(config)
    
    st.divider()
    
    render_launch_section(config, issue_number, target_override)
    
    st.divider()
    
    render_log_stream()
    render_results()


# Entry point for direct execution
if __name__ == "__main__":
    run_dashboard()