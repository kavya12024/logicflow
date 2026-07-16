"""
LogicFlow AST Tool
Extracts specific functions or classes from source code using Abstract Syntax Trees.
This allows the LLM to focus only on the buggy logic instead of the whole file.
"""

import ast
import textwrap
import logging
from typing import Optional, Tuple

logger = logging.getLogger("LogicFlow.ast_tool")


class ASTExtractor:
    """Extracts and replaces code blocks using Python AST."""
    
    @staticmethod
    def get_source_segment(source: str, node: ast.AST) -> str:
        """Get the exact source code for an AST node."""
        return ast.get_source_segment(source, node)
    
    @staticmethod
    def find_target_function(source_code: str, function_name: str) -> Optional[str]:
        """
        Finds and extracts a specific function's source code.
        Returns just the function code, or None if not found.
        """
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == function_name:
                        return ASTExtractor.get_source_segment(source_code, node)
            return None
        except Exception as e:
            logger.warning(f"Failed to parse AST to find function: {e}")
            return None

    @staticmethod
    def find_target_class(source_code: str, class_name: str) -> Optional[str]:
        """Finds and extracts a specific class's source code."""
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return ASTExtractor.get_source_segment(source_code, node)
            return None
        except Exception as e:
            logger.warning(f"Failed to parse AST to find class: {e}")
            return None

    @staticmethod
    def extract_function_from_error(source_code: str, error_message: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Attempts to extract the specific function involved in a traceback.
        Returns (extracted_code, function_name).
        """
        # Try to find "in <function_name>" in the traceback
        import re
        match = re.search(r'in (\w+)\s*\n", error_message)
        if not match:
            match = re.search(r'File ".+", line \d+, in (\w+)', error_message)
            
        if match:
            func_name = match.group(1)
            extracted_code = ASTExtractor.find_target_function(source_code, func_name)
            if extracted_code:
                return extracted_code, func_name
                
        return None, None

    @staticmethod
    def replace_function_in_source(original_source: str, function_name: str, new_function_code: str) -> Optional[str]:
        """
        Replaces a specific function in the original source code with a new version.
        Uses AST to find line numbers, then does string slicing.
        """
        try:
            tree = ast.parse(original_source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                    # Get line numbers
                    start_line = node.lineno - 1 # 0-indexed
                    end_line = node.end_lineno # ast end_lineno is exclusive-ish, let's use get_source_segment length
                    
                    # Split source into lines
                    lines = original_source.splitlines()
                    
                    # Construct new file
                    new_lines = lines[:start_line]
                    new_lines.append(new_function_code.strip())
                    new_lines.extend(lines[end_line:])
                    
                    return "\n".join(new_lines)
            return None
        except Exception as e:
            logger.error(f"Failed to replace function via AST: {e}")
            return None