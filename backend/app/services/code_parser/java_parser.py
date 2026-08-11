"""
Java Code Parser & AST Structure Extractor
Provides clean, token-efficient Java class structure extraction and method body retrieval.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class JavaCodeParser:
    """
    Parses Java source files to extract:
    1. Class Structure: Package, imports, annotations, superclasses, interfaces,
       fields, constructors, and method signatures (WITHOUT method bodies).
    2. Method Bodies: On-demand retrieval of exact method implementations.
    """

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
        class_decl_pattern = r"((?:@\w+(?:\([^)]*\))?\s+)*)?(?:public|protected|private|abstract|final|static|\s)*\b(class|interface|enum|record)\s+([A-Za-z0-9_<>,?\s]+)"
        class_decl_match = re.search(class_decl_pattern, code)

        class_name = ""
        class_kind = "class"
        extends_class = None
        implements_interfaces = []

        if class_decl_match:
            header_text = code[class_decl_match.start():code.find("{", class_decl_match.start())]
            class_kind = class_decl_match.group(2)
            raw_name = class_decl_match.group(3).split()[0]
            class_name = raw_name.split("<")[0]  # strip generic params

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
        field_pattern = r"^\s*((?:@\w+(?:\([^)]*\))?\s+)*)?(public|protected|private|package-private)?\s*(static)?\s*(final)?\s+([A-Za-z0-9_<>?,.\s\[\]]+)\s+([A-Za-z0-9_]+)\s*(?:=.*)?;$"
        for line in lines:
            m = re.match(field_pattern, line)
            if m and not any(kw in line for kw in ["return", "class", "interface", "void"]):
                annos_raw, vis, is_static, is_final, f_type, f_name = m.groups()
                field_annos = [a.strip() for a in re.findall(r"@\w+", annos_raw or "")]
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

        # Find method/constructor headers
        method_hdr_pattern = r"((?:@\w+(?:\([^)]*\))?\s+)*)?\s*(public|protected|private)?\s*(static)?\s*(final)?\s*(abstract|synchronized)?\s*([A-Za-z0-9_<>?,.\s\[\]]+)?\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?:throws\s+[A-Za-z0-9_,\s]+)?\s*\{"
        
        pending_annos = []
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("@") and not re.search(r"\b(class|interface|enum|record)\b", stripped):
                pending_annos.extend(re.findall(r"@\w+", stripped))
                continue

            m = re.search(method_hdr_pattern, line)
            if m:
                annos_raw, vis, is_static, is_final, is_abstract, ret_type, m_name, params_raw = m.groups()
                
                # Ignore control flow structures like if, for, while, switch
                if m_name in ("if", "for", "while", "switch", "catch"):
                    pending_annos = []
                    continue

                m_annos = pending_annos + [a.strip() for a in re.findall(r"@\w+", annos_raw or "")]
                pending_annos = []
                params = [p.strip() for p in params_raw.split(",") if p.strip()]

                # Check if constructor
                if class_name and m_name == class_name and not ret_type:
                    constructors.append({
                        "name": m_name,
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
        hdr_regex = re.compile(rf"\b{re.escape(method_name)}\s*\([^)]*\)\s*(?:throws\s+[A-Za-z0-9_,\s]+)?\s*\{{")

        start_line = -1
        start_char_idx = -1

        for idx, line in enumerate(lines):
            match = hdr_regex.search(line)
            if match:
                start_line = idx + 1
                # Find start brace index in code string
                start_char_idx = code.find("{", code.find(line))
                break

        if start_line == -1 or start_char_idx == -1:
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
        for p in Path(worktree_path).rglob("*.java"):
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
        for p in wt_path.rglob("*.java"):
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
