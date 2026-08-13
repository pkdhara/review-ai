"""
Java Code Parser & AST Structure Extractor
Provides clean, token-efficient Java class structure extraction and method body retrieval.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

IGNORED_DIRS = {".git", "node_modules", "target", "dist", "build", ".idea", ".vscode", ".angular", "coverage", ".next", "vendor"}


class JavaCodeParser:
    """
    Parses Java source files to extract:
    1. Class Structure: Package, imports, annotations, superclasses, interfaces,
       fields, constructors, and method signatures (WITHOUT method bodies).
    2. Method Bodies: On-demand retrieval of exact method implementations.
    """

    @staticmethod
    def _safe_walk(worktree_path: Path, extensions: tuple = ()) -> List[Path]:
        results = []
        for root, dirs, files in os.walk(worktree_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for f in files:
                if extensions and any(f.endswith(ext) for ext in extensions):
                    results.append(Path(root) / f)
        return results

    @staticmethod
    def parse_class_structure(code: str, file_path: str = "") -> Dict[str, Any]:
        """
        Extracts high-level class metadata for token optimization.
        Excludes method bodies entirely.
        """
        lines = code.splitlines()

        # Package
        pkg_match = re.search(r"^\s*package\s+([\w\.]+);", code, re.MULTILINE)
        package_name = pkg_match.group(1) if pkg_match else ""

        # Imports
        imports = re.findall(r"^\s*import\s+(?:static\s+)?([\w\.\*]+);", code, re.MULTILINE)

        # Class level annotations
        class_annotations = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@") and not re.search(r"\b(class|interface|enum|record)\b", stripped):
                # Simple extraction of class-level annotations before header
                class_annotations.append(stripped.split("(")[0])
            elif re.search(r"\b(class|interface|enum|record)\b", stripped):
                break

        # Class Declaration
        class_decl_pattern = r"\b(class|interface|enum|record)\s+([A-Za-z0-9_]+)"
        class_decl_match = re.search(class_decl_pattern, code)

        class_name = ""
        class_kind = "class"
        extends_class = None
        implements_interfaces = []

        if class_decl_match:
            header_text = code[class_decl_match.start():code.find("{", class_decl_match.start())] if "{" in code[class_decl_match.start():] else code[class_decl_match.start():]
            class_kind = class_decl_match.group(1)
            class_name = class_decl_match.group(2)

            # Extends
            ext_match = re.search(r"\bextends\s+([A-Za-z0-9_<>,?\s]+?)(?=\bimplements\b|\b{\b|$)", header_text)
            if ext_match:
                extends_class = ext_match.group(1).strip()

            # Implements
            imp_match = re.search(r"\bimplements\s+([A-Za-z0-9_<>,?\s]+?)(?=\b{\b|$)", header_text)
            if imp_match:
                implements_interfaces = [i.strip() for i in imp_match.group(1).split(",") if i.strip()]

        # Fields
        fields = []
        field_pattern = re.compile(r"^\s*(?:@\w+\s+)*(public|protected|private)?\s*(static\s+)?(final\s+)?([A-Za-z0-9_<>?,.\[\]]+)\s+([A-Za-z0-9_]+)\s*(?:=[^;]+)?;$")
        for line in lines:
            stripped = line.strip()
            if not stripped or ";" not in stripped or "(" in stripped or any(kw in line for kw in ("return", "class", "interface", "package", "import")):
                continue
            m = field_pattern.match(line)
            if m:
                vis, is_static, is_final, f_type, f_name = m.groups()
                field_annos = [a.strip() for a in re.findall(r"@\w+", line)]
                fields.append({
                    "name": f_name,
                    "type": f_type.strip(),
                    "visibility": vis or "package-private",
                    "static": bool(is_static),
                    "final": bool(is_final),
                    "annotations": field_annos,
                })

        # Methods and Constructors
        methods = []
        constructors = []

        # Find method/constructor headers without catastrophic backtracking
        method_hdr_pattern = re.compile(
            r"^\s*(?:@\w+\s+)*(public|protected|private)?\s*(static\s+)?(final\s+)?(abstract\s+|synchronized\s+)?([A-Za-z0-9_<>?,.\[\]]+)\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)"
        )
        
        pending_annos = []
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("@") and not re.search(r"\b(class|interface|enum|record)\b", stripped):
                pending_annos.extend(re.findall(r"@\w+", stripped))
                continue

            if not stripped.endswith("{") or "(" not in stripped:
                if not stripped.startswith("@"):
                    pending_annos = []
                continue

            if any(stripped.startswith(kw) for kw in ("if", "for", "while", "switch", "catch", "else", "try", "finally", "return", "throw")):
                pending_annos = []
                continue

            m = re.search(method_hdr_pattern, line)
            if m:
                vis, is_static, is_final, is_abstract, ret_type, m_name, params_raw = m.groups()
                
                if m_name in ("if", "for", "while", "switch", "catch"):
                    pending_annos = []
                    continue

                m_annos = pending_annos + [a.strip() for a in re.findall(r"@\w+", line)]
                pending_annos = []
                params = [p.strip() for p in params_raw.split(",") if p.strip()]

                # Check if constructor
                c_name = m_name if (class_name and m_name == class_name) else (ret_type if (class_name and ret_type == class_name) else None)
                if c_name:
                    constructors.append({
                        "name": c_name,
                        "visibility": vis or "package-private",
                        "parameters": params,
                        "annotations": m_annos,
                        "line_number": idx,
                    })
                elif ret_type and ret_type.strip() not in ("new", "return"):
                    methods.append({
                        "name": m_name,
                        "returnType": ret_type.strip(),
                        "visibility": vis or "package-private",
                        "parameters": params,
                        "static": bool(is_static),
                        "final": bool(is_final),
                        "abstract": bool(is_abstract),
                        "annotations": m_annos,
                        "line_number": idx,
                    })
            else:
                if not stripped.startswith("@"):
                    pending_annos = []

        return {
            "file_path": file_path,
            "package": package_name,
            "class": class_name or Path(file_path).stem if file_path else "Unknown",
            "kind": class_kind,
            "annotations": class_annotations,
            "extends": extends_class,
            "implements": implements_interfaces,
            "imports": imports,
            "fields": fields,
            "constructors": constructors,
            "methods": methods,
        }

    @staticmethod
    def extract_method_implementation(code: str, method_name: str, file_path: str = "") -> Optional[Dict[str, Any]]:
        """
        Retrieves the exact implementation body of a specific method by name.
        Uses bracket matching to extract the full body.
        """
        lines = code.splitlines()
        hdr_regex = re.compile(rf"\b{re.escape(method_name)}\s*\([^)]*\)")

        start_line = -1
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if "(" in line and hdr_regex.search(line):
                if not any(stripped.startswith(kw) for kw in ("if", "for", "while", "switch", "catch")):
                    start_line = idx + 1
                    break

        if start_line == -1:
            return None

        # Build character index for start_line
        line_offsets = []
        curr = 0
        for l in lines:
            line_offsets.append(curr)
            curr += len(l) + 1

        start_char_idx = code.find("{", line_offsets[start_line - 1])
        if start_char_idx == -1:
            return None

        # Bracket matching to find method body end with string/comment state tracking
        brace_count = 0
        end_char_idx = -1
        in_string = False
        in_char = False
        in_single_comment = False
        in_multi_comment = False
        escaped = False

        i = start_char_idx
        code_len = len(code)
        while i < code_len:
            ch = code[i]
            next_ch = code[i + 1] if i + 1 < code_len else ""

            if escaped:
                escaped = False
                i += 1
                continue

            if ch == "\\":
                escaped = True
                i += 1
                continue

            if in_single_comment:
                if ch == "\n":
                    in_single_comment = False
            elif in_multi_comment:
                if ch == "*" and next_ch == "/":
                    in_multi_comment = False
                    i += 1
            elif in_string:
                if ch == '"':
                    in_string = False
            elif in_char:
                if ch == "'":
                    in_char = False
            else:
                if ch == "/" and next_ch == "/":
                    in_single_comment = True
                    i += 1
                elif ch == "/" and next_ch == "*":
                    in_multi_comment = True
                    i += 1
                elif ch == '"':
                    in_string = True
                elif ch == "'":
                    in_char = True
                elif ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_char_idx = i
                        break
            i += 1

        if end_char_idx == -1:
            # Fallback if brace count doesn't close cleanly
            method_code = "\n".join(lines[start_line - 1 : min(start_line + 50, len(lines))])
            end_line = min(start_line + 50, len(lines))
        else:
            method_code = code[code.rfind("\n", 0, start_char_idx) + 1 : end_char_idx + 1].strip()
            end_line = start_line + method_code.count("\n")

        # Extract header annotations & signature line
        header_line = lines[start_line - 1].strip()
        annotations = [a.strip() for a in re.findall(r"@\w+", header_line)]

        return {
            "file_path": file_path,
            "method_name": method_name,
            "start_line": start_line,
            "end_line": end_line,
            "header": header_line,
            "annotations": annotations,
            "body": method_code,
        }

    @staticmethod
    def find_symbols_in_repo(worktree_path: str, query: str) -> List[Dict[str, Any]]:
        """Searches Java files in worktree for matching classes, interfaces, or methods."""
        results = []
        if not worktree_path or not Path(worktree_path).exists():
            return results

        pattern = re.compile(rf"\b{re.escape(query)}\b", re.IGNORECASE)
        matching_files = JavaCodeParser._safe_walk(Path(worktree_path), extensions=(".java",))
        for p in matching_files:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    if pattern.search(line):
                        results.append({
                            "file_path": str(p.relative_to(worktree_path)),
                            "line_number": idx,
                            "line_content": line.strip(),
                        })
                        if len(results) >= 50:
                            return results
            except Exception:
                continue
        return results

    @staticmethod
    def find_references_in_repo(worktree_path: str, symbol: str) -> List[Dict[str, Any]]:
        """
        Finds occurrences of a symbol across the Java repository and classifies each
        match into 'definition', 'usage', or 'import'.
        """
        results = []
        if not worktree_path or not symbol or not Path(worktree_path).exists():
            return results

        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        def_pattern = re.compile(
            rf"\b(class|interface|enum|record)\s+{re.escape(symbol)}\b"
            rf"|\b{re.escape(symbol)}\s*\([^)]*\)\s*(?:throws\s+[A-Za-z0-9_,\s]+)?\s*\{{"
            rf"|\b(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?[A-Za-z0-9_<>\[\]]+\s+{re.escape(symbol)}\s*\("
        )
        import_pattern = re.compile(rf"^\s*import\b.*?\b{re.escape(symbol)}\b")

        wt_path = Path(worktree_path)
        matching_files = JavaCodeParser._safe_walk(wt_path, extensions=(".java",))
        for p in matching_files:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                        continue

                    if pattern.search(stripped):
                        match_type = "usage"
                        if import_pattern.search(stripped):
                            match_type = "import"
                        elif def_pattern.search(stripped):
                            match_type = "definition"

                        results.append({
                            "file_path": str(p.relative_to(wt_path)),
                            "line_number": idx,
                            "match_type": match_type,
                            "line_content": stripped,
                        })
                        if len(results) >= 50:
                            return results
            except Exception:
                continue
        return results
