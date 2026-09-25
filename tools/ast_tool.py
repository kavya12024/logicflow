"""
LogicFlow AST Tool
Extracts specific functions or classes from source code using Abstract Syntax Trees.
Enables surgical editing: LLMs focus only on the buggy 10-25 line function instead of 
regenerating an entire 100+ line file, eliminating truncation and hallucinations.
"""

import ast
import re
import textwrap
import logging
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger("LogicFlow.ast_tool")


@dataclass
class TracebackInfo:
    """Parsed details from a stack trace or test failure."""
    target_file: Optional[str] = None
    line_number: Optional[int] = None
    function_name: Optional[str] = None
    error_type: Optional[str] = None
    error_message: str = ""
    full_traceback: str = ""


class ASTExtractor:
    """Extracts, analyzes, and replaces code blocks using Python AST."""
    
    @staticmethod
    def get_source_segment(source: str, node: ast.AST) -> Optional[str]:
        """Get the exact source code for an AST node."""
        return ast.get_source_segment(source, node)
    
    @staticmethod
    def find_target_function(source_code: str, function_name: str) -> Optional[str]:
        """
        Finds and extracts a specific function's source code, including decorators.
        Works for top-level functions and class methods.
        """
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == function_name:
                        segment = ast.get_source_segment(source_code, node)
                        return segment
            return None
        except Exception as e:
            logger.warning(f"Failed to parse AST to find function '{function_name}': {e}")
            return None

    @staticmethod
    def find_target_class(source_code: str, class_name: str) -> Optional[str]:
        """Finds and extracts a specific class's source code."""
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return ast.get_source_segment(source_code, node)
            return None
        except Exception as e:
            logger.warning(f"Failed to parse AST to find class '{class_name}': {e}")
            return None

    @staticmethod
    def parse_traceback(error_text: str) -> TracebackInfo:
        """
        Parses standard Python tracebacks, pytest failures, and unittest errors.
        Extracts target file, line number, failing function, and error message.
        """
        info = TracebackInfo(full_traceback=error_text)
        
        # 1. Match standard Python traceback lines:
        # File "/path/to/file.py", line 42, in my_func
        tb_matches = re.findall(
            r'File ["\']([^"\']+\.py)["\'], line (\d+)(?:, in (\w+))?', 
            error_text
        )
        if tb_matches:
            # The last match is usually the deepest frame in user code
            for file_path, line_str, func_name in reversed(tb_matches):
                # Filter out standard library or virtualenv paths if possible
                if not any(skip in file_path.lower() for skip in ["site-packages", "unittest", "pytest", "importlib"]):
                    info.target_file = file_path.replace("\\", "/")
                    info.line_number = int(line_str)
                    if func_name:
                        info.function_name = func_name
                    break
            
            # If all were site-packages or standard library, discard them
            # (Never target Python standard library or installed packages)
            pass

        # 2. Match pytest assertion failures:
        # E       assert calculate(...) == 12
        # E       AssertionError: ...
        pytest_err = re.search(r'(E\s+.*\n?)+', error_text)
        if pytest_err:
            info.error_message = pytest_err.group(0).strip()
            
        # 3. Match Exception line:
        # TypeError: unsupported operand type(s) ...
        # ValueError: ...
        exc_match = re.search(r'([A-Z]\w*Error|[A-Z]\w*Exception):\s*(.+)', error_text)
        if exc_match:
            info.error_type = exc_match.group(1)
            if not info.error_message:
                info.error_message = f"{exc_match.group(1)}: {exc_match.group(2).strip()}"
                
        # 4. If function wasn't in traceback header, check for 'in <function_name>'
        if not info.function_name:
            func_match = re.search(r'\bin\s+([a-zA-Z_]\w*)\b', error_text)
            if func_match:
                candidate = func_match.group(1)
                if candidate not in ["test", "run", "main"]:
                    info.function_name = candidate

        return info

    @staticmethod
    def resolve_target_from_test_failure(
        traceback_text: str,
        workspace_dir: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        When tests fail, determine the real source module and function under test
        rather than modifying the test file or Python standard library.
        Returns (target_source_file_rel, target_function_name).
        """
        from pathlib import Path
        ws = Path(workspace_dir).resolve()
        
        FORBIDDEN = ["site-packages", "unittest", "pytest", "importlib", "appdata", "program files", "python3", "lib/"]
        
        tb_matches = re.findall(r'File ["\']([^"\']+\.py)["\'], line (\d+)(?:, in (\w+))?', traceback_text)
        
        # 1. First check if any frame in traceback is from a genuine workspace source file
        for f_path, line_str, f_name in reversed(tb_matches):
            p = Path(f_path)
            f_name_lower = p.name.lower()
            f_path_clean = str(p).replace("\\", "/").lower()
            
            is_test = f_name_lower.startswith("test_") or f_name_lower.endswith("_test.py")
            is_lib = any(skip in f_path_clean for skip in FORBIDDEN)
            
            if not is_test and not is_lib:
                try:
                    rel = str(p.resolve().relative_to(ws)).replace("\\", "/")
                    return rel, f_name
                except Exception:
                    # If file is in workspace tree
                    matching = list(ws.rglob(p.name))
                    if matching:
                        return str(matching[0].relative_to(ws)).replace("\\", "/"), f_name

        # 2. If frames were inside test files (e.g. assertion failed in test method):
        test_file_path = None
        for f_path, line_str, f_name in reversed(tb_matches):
            p = Path(f_path)
            f_path_clean = str(p).replace("\\", "/").lower()
            if not any(skip in f_path_clean for skip in FORBIDDEN):
                if p.name.startswith("test_") or p.name.endswith("_test.py"):
                    test_file_path = f_path
                    break
                    
        if test_file_path:
            p_test = Path(test_file_path)
            candidate_names = []
            if p_test.name.startswith("test_"):
                candidate_names.append(p_test.name[5:])
            if p_test.name.endswith("_test.py"):
                candidate_names.append(p_test.name[:-8] + ".py")
                
            func_candidates = []
            
            # Inspect the failing test method body in the test file
            for f_path, line_str, test_method_name in reversed(tb_matches):
                if test_method_name and test_method_name.startswith("test_"):
                    try:
                        p_t = Path(f_path)
                        if not p_t.is_absolute():
                            matching_tests = list(ws.rglob(p_t.name))
                            p_t = matching_tests[0] if matching_tests else p_t
                        if p_t.exists():
                            t_content = p_t.read_text(encoding="utf-8", errors="ignore")
                            method_code = ASTExtractor.find_target_function(t_content, test_method_name)
                            if method_code:
                                for call_name in re.findall(r'([a-zA-Z_]\w*)\s*\(', method_code):
                                    if not call_name.startswith("assert") and not call_name.startswith("test_") and call_name.lower() not in ["self", "len", "str", "int", "float", "round", "failed", "fail", "error"]:
                                        if call_name not in func_candidates:
                                            func_candidates.append(call_name)
                    except Exception:
                        pass

            # Also check traceback failure line
            for line in traceback_text.splitlines():
                if line.startswith("FAILED") or line.startswith("FAIL:"):
                    continue
                if any(k in line.lower() for k in ["assert", "==", "!=", "expected"]):
                    calls = re.findall(r'([a-zA-Z_]\w*)\s*\(', line)
                    for c in calls:
                        if not c.startswith("assert") and not c.startswith("test_") and c.lower() not in ["self", "len", "str", "int", "float", "round", "failed", "fail", "error"]:
                            if c not in func_candidates:
                                func_candidates.append(c)
                                
            # Verify candidate file and candidate function in workspace
            for cand_name in candidate_names:
                for src_file in ws.rglob(cand_name):
                    try:
                        src_content = src_file.read_text(encoding="utf-8", errors="ignore")
                        rel_src = str(src_file.relative_to(ws)).replace("\\", "/")
                        for fc in func_candidates:
                            if ASTExtractor.find_target_function(src_content, fc):
                                return rel_src, fc
                        return rel_src, (func_candidates[0] if func_candidates else None)
                    except Exception:
                        continue

        # 3. Check for test import failures (e.g. ModuleNotFoundError or Failed to import test module)
        mod_match = re.search(r'Failed to import test module:\s*(\w+)', traceback_text)
        if not mod_match:
            mod_match = re.search(r'No module named\s*[\'"](\w+)[\'"]', traceback_text)
            
        if mod_match:
            mod_name = mod_match.group(1)
            for cand in [f"{mod_name}.py", f"{mod_name.replace('test_', '')}.py"]:
                for src_file in ws.rglob(cand):
                    if not any(skip in str(src_file).lower() for skip in FORBIDDEN):
                        return str(src_file.relative_to(ws)).replace("\\", "/"), None
                        
        return None, None

    @staticmethod
    def extract_function_from_error(source_code: str, error_message: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Attempts to extract the specific function involved in a traceback.
        Returns (extracted_code, function_name).
        """
        parsed = ASTExtractor.parse_traceback(error_message)
        if parsed.function_name:
            extracted = ASTExtractor.find_target_function(source_code, parsed.function_name)
            if extracted:
                return extracted, parsed.function_name
        
        # Fallback 1: check if line number falls within any function in source_code
        if parsed.line_number:
            try:
                tree = ast.parse(source_code)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                            if node.lineno <= parsed.line_number <= node.end_lineno:
                                segment = ast.get_source_segment(source_code, node)
                                if segment:
                                    return segment, node.name
            except Exception:
                pass
                
        # Fallback 2: check if any function defined in source_code is named in error_message
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if re.search(r'\b' + re.escape(node.name) + r'\b', error_message):
                        segment = ast.get_source_segment(source_code, node)
                        if segment:
                            return segment, node.name
        except Exception:
            pass
                
        return None, None

    @staticmethod
    def get_file_outline(source_code: str) -> str:
        """
        Returns a compact structural outline of a 100+ line file:
        classes, methods, top-level functions, and constants.
        Gives the LLM context of the rest of the file without line bloat.
        """
        try:
            tree = ast.parse(source_code)
            outline_lines = []
            
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    outline_lines.append(f"class {node.name}:")
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [a.arg for a in item.args.args]
                            outline_lines.append(f"    def {item.name}({', '.join(args)}): ...")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in node.args.args]
                    outline_lines.append(f"def {node.name}({', '.join(args)}): ...")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            outline_lines.append(f"{target.id} = ...")
                            
            return "\n".join(outline_lines)
        except Exception:
            return ""

    @staticmethod
    def replace_function_in_source(original_source: str, function_name: str, new_function_code: str) -> Optional[str]:
        """
        Replaces a specific function in original source code with new version.
        Preserves indentation, surrounding comments, imports, and other functions.
        Handles both top-level functions and class methods.
        """
        try:
            # Strip markdown code blocks if the model returned them
            clean_code = re.sub(r'^```(?:python)?\s*\n?', '', new_function_code.strip(), flags=re.IGNORECASE)
            clean_code = re.sub(r'\n?```$', '', clean_code.strip())
            
            # Unescape literal \n if present without actual newlines
            if "\\n" in clean_code and "\n" not in clean_code:
                clean_code = clean_code.replace("\\n", "\n")
                
            tree = ast.parse(original_source)
            target_node = None
            parent_node = None
            
            # Search for the function
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == function_name:
                        target_node = child
                        parent_node = node
                        break
                if target_node:
                    break
            
            # If not found via walk with parent, search tree.body
            if not target_node:
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                        target_node = node
                        break
                        
            if not target_node:
                logger.warning(f"Function '{function_name}' not found for replacement.")
                return None
                
            start_line = target_node.lineno - 1  # 0-indexed
            end_line = target_node.end_lineno    # 1-indexed, so lines[:end_line] includes it
            
            lines = original_source.splitlines()
            
            # Determine existing indentation of target function
            target_line = lines[start_line]
            indent_match = re.match(r"^(\s*)", target_line)
            existing_indent = indent_match.group(1) if indent_match else ""
            
            # Clean and re-indent the new function code
            cleaned_new_code = textwrap.dedent(clean_code.strip())
            new_code_lines = cleaned_new_code.splitlines()
            
            indented_new_lines = []
            for line in new_code_lines:
                if line.strip():
                    indented_new_lines.append(f"{existing_indent}{line}")
                else:
                    indented_new_lines.append("")
                    
            # Splice new function back into original lines
            result_lines = lines[:start_line] + indented_new_lines + lines[end_line:]
            new_source = "\n".join(result_lines)
            
            # Validate that the resulting source compiles syntactically
            try:
                ast.parse(new_source)
                return new_source
            except SyntaxError as se:
                logger.warning(f"Spliced code syntax check failed ({se}); trying raw alignment fallback")
                fallback_lines = lines[:start_line] + [clean_code] + lines[end_line:]
                fallback_source = "\n".join(fallback_lines)
                try:
                    ast.parse(fallback_source)
                    return fallback_source
                except SyntaxError:
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to replace function '{function_name}' via AST: {e}")
            return None