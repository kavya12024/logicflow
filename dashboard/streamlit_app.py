"""
LogicFlow Streamlit Dashboard
Visual operational manager for the LogicFlow autonomous coding agent.
Supports autonomous test-driven repairs, local file fixing, and GitHub issue workflows.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root directory is in sys.path so config and tools import correctly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Mute verbose logs
for lib in ["transformers", "sentence_transformers", "tokenizers", "urllib3", "httpx", "openai", "faiss", "github", "PIL"]:
    logging.getLogger(lib).setLevel(logging.ERROR)

import streamlit as st

from config import LogicFlowConfig, get_config, reset_config
from tools.faiss_tool import FaissIndexer
from tools.docker_test_tool import DockerSandbox
from tools.github_tool import GitHubManager
from agents.core import LogicFlowAgent, AgentResult

# Configure Streamlit page
st.set_page_config(
    page_title="LogicFlow - The Digital Archeologist",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        font-family: 'Segoe UI', -apple-system, sans-serif;
    }
    .success-box {
        padding: 12px;
        border-radius: 6px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        font-weight: 500;
        margin-bottom: 12px;
    }
    .error-box {
        padding: 12px;
        border-radius: 6px;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        font-weight: 500;
        margin-bottom: 12px;
    }
    .info-box {
        padding: 12px;
        border-radius: 6px;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
        margin-bottom: 12px;
    }
    .warning-box {
        padding: 12px;
        border-radius: 6px;
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
        margin-bottom: 12px;
    }
    .log-container {
        max-height: 380px;
        overflow-y: auto;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        background-color: #1e1e1e;
        color: #d4d4d4;
        padding: 12px;
        border-radius: 6px;
        border: 1px solid #333;
    }
    .log-entry {
        margin-bottom: 3px;
        line-height: 1.4;
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
    """Render sidebar configuration panel."""
    st.sidebar.title("Configuration")
    config = st.session_state.config
    
    with st.sidebar.expander("Ollama Model Settings", expanded=True):
        config.ollama.base_url = st.text_input(
            "Ollama Base URL",
            value=config.ollama.base_url,
            key="ollama_url"
        )
        config.ollama.model = st.text_input(
            "Active Model",
            value=config.ollama.model,
            help="Configured for lightweight execution: llama3.2:3b",
            key="ollama_model"
        )
        config.ollama.request_timeout = st.number_input(
            "Request Timeout (s)",
            min_value=60,
            max_value=600,
            value=int(config.ollama.request_timeout),
            key="ollama_timeout"
        )
    
    with st.sidebar.expander("Workspace & RAG Settings", expanded=False):
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
    
    with st.sidebar.expander("Docker Sandbox Settings", expanded=False):
        config.docker.timeout_seconds = st.number_input(
            "Timeout (s)",
            min_value=30,
            max_value=300,
            value=config.docker.timeout_seconds,
            key="docker_timeout"
        )
        config.docker.network_disabled = st.checkbox(
            "Disable Network (Isolation)",
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


def render_status_checks(config: LogicFlowConfig) -> None:
    """Render system diagnostics."""
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
                models = [m.get("name", "unknown") for m in response.json().get("models", [])]
                st.markdown(f'<div class="success-box">Connected ({config.ollama.model})</div>', unsafe_allow_html=True)
                if models:
                    st.caption(f"Installed: {', '.join(models)}")
            else:
                st.markdown('<div class="error-box">Connection failed</div>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<div class="error-box">Unavailable: {str(e)[:40]}</div>', unsafe_allow_html=True)
    
    with col2:
        st.subheader("Docker")
        if st.session_state.docker_available is None:
            sandbox = DockerSandbox(config)
            available, msg = sandbox.check_docker_available()
            st.session_state.docker_available = available
            st.session_state.docker_msg = msg
        
        if st.session_state.docker_available:
            st.markdown('<div class="success-box">Docker Available</div>', unsafe_allow_html=True)
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
            st.markdown(f'<div class="success-box">Connected to {config.github.repo}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="warning-box">{st.session_state.github_msg}</div>', unsafe_allow_html=True)


def render_indexing_section(config: LogicFlowConfig) -> None:
    """Render repository indexing controls."""
    st.header("Repository Indexing")
    col1, col2, col3 = st.columns(3)
    
    agent = get_or_create_agent(config)
    
    with col1:
        if st.button("Build New Index", type="primary"):
            with st.spinner("Building FAISS index..."):
                if agent.initialize_index(force_rebuild=True):
                    st.session_state.index_built = True
                    st.session_state.indexed_files = agent.faiss.get_indexed_files()
                    st.success(f"Built index with {len(st.session_state.indexed_files)} files")
                else:
                    st.error("Failed to build index.")
    
    with col2:
        if st.button("Load Existing Index"):
            if agent.initialize_index(force_rebuild=False):
                st.session_state.index_built = True
                st.session_state.indexed_files = agent.faiss.get_indexed_files()
                st.success(f"Loaded index with {len(st.session_state.indexed_files)} files")
            else:
                st.warning("No existing index found.")
    
    with col3:
        if st.button("Check Index Stats"):
            if st.session_state.index_built or agent.faiss.load_index():
                st.json(agent.faiss.get_stats())
            else:
                st.info("No index loaded")
                
    if st.session_state.indexed_files:
        with st.expander("Indexed Files"):
            for f in sorted(st.session_state.indexed_files):
                st.code(f, language=None)


def get_or_create_agent(config: LogicFlowConfig) -> LogicFlowAgent:
    """Get or create the LogicFlow agent instance."""
    if st.session_state.agent is None:
        st.session_state.agent = LogicFlowAgent(config)
    return st.session_state.agent


def render_modes(config: LogicFlowConfig) -> None:
    """Render execution modes: Upload & Fix, Autonomous Test & Repair, Local Fix, and GitHub Issue."""
    tab_upload, tab1, tab2, tab3 = st.tabs([
        "📤 Upload & Auto-Fix Code",
        "🤖 Autonomous Test & Repair",
        "📁 Local File Repair",
        "🐙 GitHub Issue Workflow"
    ])
    
    agent = get_or_create_agent(config)

    # TAB 0: Upload & Auto-Fix Full Code
    with tab_upload:
        st.subheader("Upload or Paste Full Code for Autonomous Repair")
        st.write(
            "Upload any source code file or paste your complete code snippet below. "
            "LogicFlow automatically scans for syntax, indentation, and logic errors, "
            "repairs the code using lightweight local models (llama3.2:3b), and verifies it in the sandbox."
        )
        
        col_up1, col_up2 = st.columns([2, 1])
        with col_up1:
            uploaded_file = st.file_uploader(
                "Upload Code File (.py, .js, .ts, .java, .cpp, .txt)",
                type=["py", "js", "ts", "java", "c", "cpp", "go", "txt"],
                key="code_file_uploader"
            )
        # Initialize persistence keys if not present
        if "last_uploaded_name" not in st.session_state:
            st.session_state.last_uploaded_name = None
        if "uploaded_code_cache" not in st.session_state:
            st.session_state.uploaded_code_cache = ""

        uploaded_content = ""
        if uploaded_file is not None:
            try:
                uploaded_content = uploaded_file.getvalue().decode("utf-8", errors="ignore")
                if uploaded_file.name != st.session_state.last_uploaded_name or not st.session_state.uploaded_code_cache:
                    st.session_state.last_uploaded_name = uploaded_file.name
                    st.session_state.uploaded_code_cache = uploaded_content
                    st.session_state["pasted_code_area"] = uploaded_content
                    st.session_state["code_target_filename"] = uploaded_file.name
            except Exception as e:
                st.error(f"Error reading uploaded file: {e}")

        with col_up2:
            default_fname = uploaded_file.name if uploaded_file else "tictactoe.py"
            custom_filename = st.text_input(
                "Target Filename",
                value=st.session_state.get("code_target_filename", default_fname),
                key="code_target_filename"
            )

        # Code text area: fallback cascade ensures code is never lost on rerun
        initial_text = st.session_state.get("pasted_code_area") or st.session_state.get("uploaded_code_cache") or uploaded_content
        code_input = st.text_area(
            "Or Paste / Edit Full Code Here",
            value=initial_text,
            height=260,
            placeholder="Paste your broken or unformatted code here (e.g. Tic-Tac-Toe, algorithms, etc.)...",
            key="pasted_code_area"
        )
        
        # Effective code to process: prioritize text area, fallback to uploaded cache or fresh bytes
        effective_code = (code_input or "").strip()
        if not effective_code and st.session_state.get("uploaded_code_cache"):
            effective_code = st.session_state["uploaded_code_cache"].strip()
        if not effective_code and uploaded_content:
            effective_code = uploaded_content.strip()

        if effective_code:
            display_name = st.session_state.get("code_target_filename", custom_filename)
            st.caption(f"📄 Loaded file: `{display_name}` ({len(effective_code.splitlines())} lines ready for repair)")

        col_err1, col_err2 = st.columns([3, 1])
        with col_err1:
            error_hint = st.text_input(
                "Optional Error Message / Expected Behavior",
                placeholder="Leave blank to auto-detect syntax and indentation bugs, or describe expected behavior...",
                key="code_error_hint"
            )
        with col_err2:
            st.write("")
            st.write("")
            check_btn = st.button("🔍 Pre-Check Syntax", key="btn_check_syntax")
            
        if check_btn:
            if not effective_code:
                st.warning("Please upload a file or paste your code snippet first.")
            elif custom_filename.endswith(".py"):
                try:
                    compile(effective_code, custom_filename, "exec")
                    st.success("No syntax or indentation errors detected by Python compiler! (Logic bugs will still be checked by AI).")
                except SyntaxError as e:
                    st.error(f"SyntaxError detected at line {e.lineno}: {e.msg}\nOffending code: {e.text.strip() if e.text else ''}")
                except Exception as e:
                    st.error(f"Error during pre-check: {e}")
            else:
                st.info(f"Pre-check: {len(effective_code.splitlines())} lines ready for analysis.")
                
        fix_uploaded_btn = st.button("🚀 Analyze & Auto-Fix Code", type="primary", key="btn_fix_uploaded")
        if fix_uploaded_btn:
            if not effective_code:
                st.warning("Please upload a file or paste your code snippet first.")
            else:
                st.session_state.logs = []
                st.session_state.result = None
                with st.spinner("LogicFlow is analyzing, repairing, and compiling your code..."):
                    result = agent.process_code_snippet(
                        code_snippet=effective_code,
                        error_message=error_hint.strip() if error_hint.strip() else None,
                        filename=custom_filename,
                        auto_save=False
                    )
                    st.session_state.result = result
                    st.session_state.logs = result.logs
                    st.rerun()
    
    # TAB 1: Autonomous Test & Repair
    with tab1:
        st.subheader("Autonomous Test-Driven Error Detection & Repair")
        st.write(
            "LogicFlow executes your workspace test suite, automatically detects failures, "
            "parses tracebacks to pinpoint the exact broken file and function, surgically patches "
            "the bug without altering surrounding code (safe for 100+ line files), and re-tests until green."
        )
        
        col1, col2 = st.columns([3, 1])
        with col1:
            test_file_input = st.text_input(
                "Specific Test File (optional, leave blank to discover all tests)",
                placeholder="e.g. test_payroll_calculator.py",
                key="auto_test_file"
            )
        with col2:
            st.write("")
            st.write("")
            run_auto = st.button("Run & Auto-Repair", type="primary", key="btn_run_auto")
            
        if run_auto:
            st.session_state.logs = []
            st.session_state.result = None
            with st.spinner("Running autonomous test & repair cycle..."):
                t_file = test_file_input.strip() if test_file_input.strip() else None
                result = agent.process_autonomous_test_and_fix(test_file=t_file)
                st.session_state.result = result
                st.session_state.logs = result.logs
                st.rerun()

    # TAB 2: Local File Fix
    with tab2:
        st.subheader("Fix Local File (No GitHub Issue Required)")
        st.write("Provide a target file and an error message or stack trace to repair directly.")
        
        file_options = sorted(st.session_state.indexed_files) if st.session_state.indexed_files else []
        col1, col2 = st.columns(2)
        with col1:
            if file_options:
                target_local_file = st.selectbox("Select Target File", file_options, key="select_local_file")
            else:
                target_local_file = st.text_input("Target File Relative Path", "calculator.py", key="input_local_file")
        with col2:
            test_verify_file = st.text_input("Optional Test Verification File", "", key="local_verify_test")
            
        error_msg_input = st.text_area(
            "Error Message / Stack Trace / Failed Assertion",
            placeholder="Paste error output, e.g. AssertionError: multiply(3, 4) == 12 failed...",
            height=120,
            key="local_error_input"
        )
        
        if st.button("Repair Local File", type="primary", key="btn_repair_local"):
            if not target_local_file or not error_msg_input:
                st.warning("Please provide both target file and error message.")
            else:
                st.session_state.logs = []
                st.session_state.result = None
                with st.spinner("Analyzing and repairing local file..."):
                    t_verify = test_verify_file.strip() if test_verify_file.strip() else None
                    result = agent.process_local_fix(
                        target_file=target_local_file,
                        error_message=error_msg_input,
                        test_file=t_verify
                    )
                    st.session_state.result = result
                    st.session_state.logs = result.logs
                    st.rerun()

    # TAB 3: GitHub Issue Workflow
    with tab3:
        st.subheader("Fix from GitHub Issue")
        if not config.github.token or not config.github.repo:
            st.warning("Configure GITHUB_TOKEN and GITHUB_REPO in sidebar to fetch issues.")
        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                if st.button("Fetch Open Issues"):
                    with st.spinner("Fetching issues from GitHub..."):
                        github_mgr = GitHubManager(config)
                        st.session_state.issues = github_mgr.fetch_open_issues(limit=50)
            with col2:
                issue_num_input = st.number_input("Or enter Issue #", min_value=1, value=1, key="num_issue_direct")
                
            selected_issue_number = None
            if st.session_state.issues:
                issue_labels = [f"#{i.number}: {i.title}" for i in st.session_state.issues]
                selected_idx = st.selectbox("Select Issue", range(len(issue_labels)), format_func=lambda x: issue_labels[x])
                selected_issue_number = st.session_state.issues[selected_idx].number
            elif issue_num_input:
                selected_issue_number = issue_num_input
                
            if st.button("Launch Fix for Issue", type="primary", key="btn_launch_github"):
                st.session_state.logs = []
                st.session_state.result = None
                with st.spinner(f"Fixing issue #{selected_issue_number}..."):
                    result = agent.process_issue(issue_number=selected_issue_number)
                    st.session_state.result = result
                    st.session_state.logs = result.logs
                    st.rerun()


def render_log_stream() -> None:
    """Render the log output stream."""
    logs = st.session_state.logs
    if not logs:
        return
    
    st.header("Execution Logs")
    log_html = '<div class="log-container">'
    for log_entry in logs:
        safe_entry = log_entry.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        log_html += f'<div class="log-entry">{safe_entry}</div>'
    log_html += '</div>'
    st.markdown(log_html, unsafe_allow_html=True)


def render_results() -> None:
    """Render execution results."""
    result: AgentResult = st.session_state.result
    if result is None:
        return
    
    st.header("Results")
    if result.success:
        st.markdown('<div class="success-box">✓ Execution Completed Successfully</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="error-box">✗ Execution Failed: {result.error}</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Summary")
        if result.issue_number > 0:
            st.write(f"**Issue:** #{result.issue_number}")
        st.write(f"**Target File:** `{result.target_file}`")
        if result.target_function:
            st.write(f"**Surgical Function:** `{result.target_function}`")
        st.write(f"**Attempts Used:** {result.attempts_used}")
        st.write(f"**Tests Passing:** {'Yes' if result.test_passed else 'No'}")
        if result.pr_url:
            st.write(f"**Pull Request:** [{result.pr_url}]({result.pr_url})")
        if result.branch_name:
            st.write(f"**Branch:** `{result.branch_name}`")
    
    with col2:
        st.subheader("Security Status")
        if result.is_secure:
            st.markdown('<div class="success-box">✓ Code passed security review</div>', unsafe_allow_html=True)
        elif not result.success and (not result.security_audit or "Verification failed" in result.security_audit):
            st.markdown('<div class="info-box">ℹ️ Security review pending verified fix</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warning-box">⚠️ Security concerns identified</div>', unsafe_allow_html=True)
    
    if result.explanation:
        with st.expander("Fix Explanation", expanded=True):
            st.write(result.explanation)
            
    if result.security_audit:
        with st.expander("Security Audit Details"):
            st.text(result.security_audit)
            
    if result.fallback_git_args:
        with st.expander("Fallback Git Commands"):
            for cmd in result.fallback_git_args.get("commands", []):
                st.code(cmd, language="bash")
                
    agent = st.session_state.agent
    if agent:
        patched = agent.get_patched_code()
        original = agent._state.original_code
        if patched:
            st.subheader("Code Comparison & Actions")
            code_col1, code_col2 = st.columns(2)
            with code_col1:
                st.markdown("**Original Input Code:**")
                st.code(original or "(original not recorded)", language="python")
            with code_col2:
                st.markdown("**Repaired & Verified Code:**")
                st.code(patched, language="python")

            action_col1, action_col2 = st.columns(2)
            with action_col1:
                st.download_button(
                    label=f"📥 Download Fixed {result.target_file}",
                    data=patched,
                    file_name=f"fixed_{result.target_file}",
                    mime="text/plain",
                    use_container_width=True
                )
            with action_col2:
                if st.button("💾 Save Directly to Workspace", use_container_width=True, key="btn_save_ws"):
                    ws_dir = st.session_state.config.workspace.demo_dir
                    target_out = Path(ws_dir) / result.target_file
                    target_out.parent.mkdir(parents=True, exist_ok=True)
                    target_out.write_text(patched, encoding="utf-8")
                    st.success(f"Saved successfully to {target_out}")


def run_dashboard() -> None:
    """Main entry point for Streamlit dashboard."""
    initialize_session_state()
    config = render_sidebar()
    render_status_checks(config)
    st.divider()
    render_indexing_section(config)
    st.divider()
    render_modes(config)
    st.divider()
    render_log_stream()
    render_results()


if __name__ == "__main__":
    run_dashboard()