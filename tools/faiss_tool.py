"""
LogicFlow FAISS RAG Tool
Implements local semantic indexing with FAISS and sentence-transformers.
Includes context trimming optimizer for token minimization.
"""

import os
import re
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
import faiss

from config import LogicFlowConfig, get_config

logger = logging.getLogger("LogicFlow.faiss_tool")


@dataclass
class CodeChunk:
    """Represents a chunk of code with metadata."""
    content: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    chunk_type: str = "code"  # code, signature, macro, struct


class ContextTrimmer:
    """
    Extracts only essential structural elements from dependency files
    to minimize token usage while preserving type information.
    """
    
    # Patterns for different language constructs
    PATTERNS = {
        "c": {
            "macros": r'^\s*#define\s+\w+.*$',
            "structs": r'^\s*(?:typedef\s+)?struct\s+\w*\s*\{?[^;]*$',
            "enums": r'^\s*(?:typedef\s+)?enum\s+\w*\s*\{?[^;]*$',
            "function_sigs": r'^\s*(?:static\s+)?(?:inline\s+)?(?:const\s+)?\w[\w\s\*]*\s+\w+\s*\([^)]*\)\s*(?:;\s*$|const\s*;$)',
            "type_defs": r'^\s*typedef\s+.*;$',
            "extern": r'^\s*extern\s+.*;$',
            "function_pointers": r'^\s*\w[\w\s\*]*\(\s*\*\s*\w+\s*\)\s*\([^)]*\)\s*;',
        },
        "cpp": {
            "macros": r'^\s*#define\s+\w+.*$',
            "classes": r'^\s*(?:template\s*<[^>]*>\s*)?(?:class|struct)\s+\w+[^{]*\{?$',
            "function_sigs": r'^\s*(?:(?:virtual|static|inline|constexpr|explicit|constexpr)\s+)*[\w:<>*&\s]+\s+\w+(?:::\w+)*\s*\([^)]*\)(?:\s*const)?\s*(?:override|final)?\s*(?:=\s*0)?\s*;',
            "templates": r'^\s*template\s*<[^>]*>',
            "namespaces": r'^\s*namespace\s+\w+\s*\{?',
            "type_aliases": r'^\s*using\s+\w+\s*=.*;$',
        },
        "python": {
            "classes": r'^\s*class\s+\w+[^:]*:',
            "function_sigs": r'^\s*(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->\s*[^:]+)?:',
            "imports": r'^(?:from\s+[\w.]+\s+)?import\s+[\w,\s.*]+',
            "type_aliases": r'^\s*\w+\s*=\s*(?:Optional|List|Dict|Tuple|Set|Union|Callable)\[.*\]',
            "constants": r'^\s*[A-Z_][A-Z0-9_]*\s*[:=]',
        },
        "java": {
            "classes": r'^\s*(?:public|private|protected)?\s*(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+\w+[^{]*\{?',
            "method_sigs": r'^\s*(?:public|private|protected|static|final|abstract|synchronized|native)?\s+[\w<>\[\],\s]+\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*[;{]',
            "annotations": r'^\s*@\w+(?:\([^)]*\))?',
            "interfaces": r'^\s*interface\s+\w+[^{]*\{?',
        },
        "go": {
            "structs": r'^\s*type\s+\w+\s+struct\s*\{',
            "interfaces": r'^\s*type\s+\w+\s+interface\s*\{',
            "function_sigs": r'^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+\s*\([^)]*\)(?:\s*\([^)]*\))?',
            "type_defs": r'^\s*type\s+\w+\s+',
            "constants": r'^\s*const\s+',
        },
        "rust": {
            "structs": r'^\s*(?:pub\s+)?struct\s+\w+[^{]*\{?',
            "enums": r'^\s*(?:pub\s+)?enum\s+\w+[^{]*\{?',
            "traits": r'^\s*(?:pub\s+)?trait\s+\w+[^{]*\{?',
            "function_sigs": r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:->\s*[^{]+)?',
            "type_aliases": r'^\s*(?:pub\s+)?type\s+\w+\s*=',
            "impls": r'^\s*impl(?:<[^>]*>)?\s+\w+',
        },
        "typescript": {
            "interfaces": r'^\s*(?:export\s+)?interface\s+\w+[^{]*\{?',
            "types": r'^\s*(?:export\s+)?type\s+\w+\s*=',
            "function_sigs": r'^\s*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*[;{]',
            "classes": r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+\w+[^{]*\{?',
            "enums": r'^\s*(?:export\s+)?enum\s+\w+\s*\{?',
            "imports": r'^\s*import\s+.*from\s+[\'"][^\'"]+[\'"]',
        },
        "javascript": {
            "function_sigs": r'^\s*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*\{?',
            "class_sigs": r'^\s*(?:export\s+)?class\s+\w+[^{]*\{?',
            "const_declarations": r'^\s*(?:export\s+)?const\s+\w+\s*=\s*(?:require\(|function|class|\[|\{)',
        },
    }

    @classmethod
    def trim_dependency_file(cls, content: str, language: str) -> str:
        """
        Extract only structural elements from a dependency file.
        Returns stripped content containing only signatures, macros, and types.
        """
        patterns = cls.PATTERNS.get(language, cls.PATTERNS.get("c", {}))
        if not patterns:
            return ""
        
        lines = content.split("\n")
        extracted_lines: List[str] = []
        
        for line in lines:
            for pattern_type, pattern in patterns.items():
                try:
                    if re.match(pattern, line):
                        extracted_lines.append(line)
                        break
                except re.error:
                    continue
        
        return "\n".join(extracted_lines)

    @classmethod
    def trim_multiple_dependencies(
        cls, 
        dependencies: Dict[str, str], 
        language_map: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Trim multiple dependency files at once.
        
        Args:
            dependencies: Mapping of file paths to their full content
            language_map: Mapping of file paths to their detected languages
            
        Returns:
            Mapping of file paths to their trimmed content
        """
        trimmed = {}
        for file_path, content in dependencies.items():
            language = language_map.get(file_path, "unknown")
            trimmed_content = cls.trim_dependency_file(content, language)
            if trimmed_content.strip():
                trimmed[file_path] = trimmed_content
        return trimmed


class FaissIndexer:
    """
    Local FAISS-based semantic indexer for code repositories.
    Builds, persists, and queries vector indices for code retrieval.
    """
    
    def __init__(self, config: Optional[LogicFlowConfig] = None):
        self.config = config or get_config()
        self.embedding_model: Optional[SentenceTransformer] = None
        self.index: Optional[faiss.IndexFlatL2] = None
        self.chunks: List[CodeChunk] = []
        self._initialized = False
        
    def _initialize_model(self) -> None:
        """Lazy-load the embedding model to avoid startup overhead."""
        if self.embedding_model is None:
            logger.info(f"Loading embedding model: {self.config.faiss.embedding_model}")
            self.embedding_model = SentenceTransformer(self.config.faiss.embedding_model)
            logger.info("Embedding model loaded successfully")
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext = Path(file_path).suffix
        return self.config.get_language_from_extension(ext)
    
    def _chunk_code(self, content: str, file_path: str) -> List[CodeChunk]:
        """
        Split code file into overlapping chunks for indexing.
        Respects function/class boundaries where possible.
        """
        language = self._detect_language(file_path)
        lines = content.split("\n")
        chunks: List[CodeChunk] = []
        
        chunk_size = self.config.faiss.chunk_size
        overlap = self.config.faiss.chunk_overlap
        
        # Try to chunk at logical boundaries first
        boundary_patterns = {
            "python": [r'^\s*def\s+', r'^\s*class\s+'],
            "c": [r'^\w[\w\s\*]+\s+\w+\s*\(', r'^\s*struct\s+'],
            "cpp": [r'^\w[\w:<>\s\*]+\s+\w+\s*\(', r'^\s*(?:class|struct)\s+'],
            "java": [r'^\s*(?:public|private|protected)\s+.*\s+\w+\s*\(', r'^\s*(?:class|interface|enum)\s+'],
            "go": [r'^func\s+', r'^type\s+\w+\s+struct'],
            "rust": [r'^fn\s+', r'^pub\s+fn\s+', r'^struct\s+', r'^impl\s+'],
            "typescript": [r'^\s*(?:export\s+)?(?:async\s+)?function\s+', r'^\s*(?:export\s+)?(?:interface|class|type)\s+'],
            "javascript": [r'^\s*(?:export\s+)?(?:async\s+)?function\s+', r'^\s*(?:export\s+)?class\s+'],
        }
        
        patterns = boundary_patterns.get(language, [])
        
        if patterns and len(lines) > chunk_size // 4:
            # Boundary-aware chunking
            chunk_lines: List[str] = []
            chunk_start = 0
            
            for i, line in enumerate(lines):
                chunk_lines.append(line)
                
                # Check if we've reached chunk size or found a boundary
                is_boundary = any(re.match(p, line) for p in patterns) if patterns else False
                reached_size = len(chunk_lines) >= chunk_size
                
                if (reached_size or (is_boundary and len(chunk_lines) >= chunk_size // 2)):
                    if chunk_lines:
                        chunk_content = "\n".join(chunk_lines)
                        chunks.append(CodeChunk(
                            content=chunk_content,
                            file_path=file_path,
                            start_line=chunk_start + 1,
                            end_line=i + 1,
                            language=language
                        ))
                        # Keep overlap lines
                        chunk_lines = chunk_lines[-overlap:] if overlap > 0 else []
                        chunk_start = i - len(chunk_lines) + 1
        else:
            # Simple fixed-size chunking with overlap
            i = 0
            while i < len(lines):
                end_idx = min(i + chunk_size, len(lines))
                chunk_lines = lines[i:end_idx]
                
                if chunk_lines:
                    chunk_content = "\n".join(chunk_lines)
                    chunks.append(CodeChunk(
                        content=chunk_content,
                        file_path=file_path,
                        start_line=i + 1,
                        end_line=end_idx,
                        language=language
                    ))
                
                i += chunk_size - overlap if overlap < chunk_size else chunk_size
        
        return chunks
    
    def build_index(self, directory: Optional[str] = None) -> int:
        """
        Build FAISS index from all supported files in directory.
        
        Returns:
            Number of chunks indexed
        """
        self._initialize_model()
        
        target_dir = Path(directory or self.config.workspace.demo_dir)
        if not target_dir.exists():
            logger.error(f"Directory does not exist: {target_dir}")
            return 0
        
        self.chunks = []
        supported_exts = set(self.config.workspace.supported_extensions)
        
        logger.info(f"Scanning directory: {target_dir}")
        
        for root, _, files in os.walk(target_dir):
            # Skip hidden directories and common non-source dirs
            rel_path = Path(root).relative_to(target_dir)
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", 
                        ".idea", ".vscode", "dist", "build", ".logicflow_temp"}
            if any(part in skip_dirs for part in rel_path.parts):
                continue
            
            for filename in files:
                file_path = Path(root) / filename
                if file_path.suffix.lower() not in supported_exts:
                    continue
                
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if len(content) > self.config.workspace.max_file_size_bytes:
                        logger.warning(f"Skipping large file: {file_path}")
                        continue
                    
                    file_chunks = self._chunk_code(content, str(file_path.relative_to(target_dir)))
                    self.chunks.extend(file_chunks)
                    
                except Exception as e:
                    logger.warning(f"Error reading {file_path}: {e}")
                    continue
        
        if not self.chunks:
            logger.warning("No valid code chunks found to index")
            return 0
        
        logger.info(f"Generated {len(self.chunks)} code chunks")
        
        # Generate embeddings
        texts = [chunk.content for chunk in self.chunks]
        embeddings = self.embedding_model.encode(texts, show_progress_bar=True)
        
        # Build FAISS index
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(np.array(embeddings, dtype=np.float32))
        
        self._initialized = True
        logger.info(f"FAISS index built with {self.index.ntotal} vectors")
        
        # Persist index
        self._save_index()
        
        return len(self.chunks)
    
    def _save_index(self) -> None:
        """Persist index and metadata to disk."""
        index_dir = Path(self.config.faiss.index_path)
        index_dir.mkdir(parents=True, exist_ok=True)
        
        if self.index is not None:
            faiss.write_index(self.index, str(index_dir / "code_index.faiss"))
        
        # Save chunk metadata
        import pickle
        metadata_path = index_dir / "chunks_metadata.pkl"
        with open(metadata_path, "wb") as f:
            pickle.dump([
                {
                    "content": c.content,
                    "file_path": c.file_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "language": c.language,
                }
                for c in self.chunks
            ], f)
        
        logger.info(f"Index saved to {index_dir}")
    
    def load_index(self) -> bool:
        """
        Load previously built index from disk.
        
        Returns:
            True if index was loaded successfully
        """
        self._initialize_model()
        
        index_dir = Path(self.config.faiss.index_path)
        index_file = index_dir / "code_index.faiss"
        metadata_file = index_dir / "chunks_metadata.pkl"
        
        if not index_file.exists() or not metadata_file.exists():
            logger.warning("No existing index found")
            return False
        
        try:
            self.index = faiss.read_index(str(index_file))
            
            import pickle
            with open(metadata_file, "rb") as f:
                metadata_list = pickle.load(f)
            
            self.chunks = [
                CodeChunk(**meta) for meta in metadata_list
            ]
            
            self._initialized = True
            logger.info(f"Loaded index with {len(self.chunks)} chunks")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False
    
    def query(
        self, 
        query_text: str, 
        top_k: Optional[int] = None,
        exclude_file: Optional[str] = None
    ) -> List[Tuple[CodeChunk, float]]:
        """
        Query the index for similar code chunks.
        
        Args:
            query_text: The query string to search for
            top_k: Number of results to return
            exclude_file: Optional file path to exclude from results
            
        Returns:
            List of (chunk, distance) tuples sorted by relevance
        """
        if not self._initialized or self.index is None:
            logger.error("Index not initialized. Call build_index() or load_index() first.")
            return []
        
        k = top_k or self.config.faiss.top_k_results
        
        # Generate query embedding
        query_embedding = self.embedding_model.encode([query_text])
        query_vector = np.array(query_embedding, dtype=np.float32)
        
        # Search index
        distances, indices = self.index.search(query_vector, min(k * 2, self.index.ntotal))
        
        results: List[Tuple[CodeChunk, float]] = []
        seen_files: set = set()
        
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            
            chunk = self.chunks[idx]
            
            # Skip excluded file
            if exclude_file and chunk.file_path == exclude_file:
                continue
            
            # Limit results per file for diversity
            if chunk.file_path in seen_files:
                continue
            seen_files.add(chunk.file_path)
            
            results.append((chunk, float(dist)))
            
            if len(results) >= k:
                break
        
        return results
    
    def get_full_file_content(self, file_path: str) -> Optional[str]:
        """Read the full content of a specific file from workspace."""
        full_path = Path(self.config.workspace.demo_dir) / file_path
        if not full_path.exists():
            return None
        try:
            return full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return None
    
    def get_context_for_fix(
        self, 
        target_file: str, 
        error_message: str,
        issue_description: str
    ) -> Tuple[Optional[str], Dict[str, str]]:
        """
        Get RAG context for fixing a bug.
        Returns (full_target_content, trimmed_dependencies).
        """
        # Get full target file
        target_content = self.get_full_file_content(target_file)
        
        # Query for relevant dependencies
        query = f"{error_message}\n{issue_description}\n{target_file}"
        results = self.query(query, top_k=8, exclude_file=target_file)
        
        # Build trimmed dependencies
        raw_deps: Dict[str, str] = {}
        lang_map: Dict[str, str] = {}
        
        for chunk, _ in results:
            if chunk.file_path not in raw_deps:
                full_content = self.get_full_file_content(chunk.file_path)
                if full_content:
                    raw_deps[chunk.file_path] = full_content
                    lang_map[chunk.file_path] = chunk.language
        
        # Trim dependencies to essential structures only
        trimmed_deps = ContextTrimmer.trim_multiple_dependencies(raw_deps, lang_map)
        
        return target_content, trimmed_deps
    
    def get_indexed_files(self) -> List[str]:
        """Get list of all indexed file paths."""
        return list(set(chunk.file_path for chunk in self.chunks))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get indexing statistics."""
        return {
            "total_chunks": len(self.chunks),
            "unique_files": len(set(c.file_path for c in self.chunks)),
            "languages": list(set(c.language for c in self.chunks if c.language != "unknown")),
            "initialized": self._initialized,
            "index_size": self.index.ntotal if self.index else 0,
        }