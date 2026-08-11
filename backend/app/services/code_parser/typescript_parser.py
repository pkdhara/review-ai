"""
TypeScript & Angular Code Parser & AST Structure Extractor.
Provides token-efficient class/component structure extraction, HTML template reading,
and method body retrieval for TypeScript and Angular applications.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class TypeScriptCodeParser:
    """
    Parses TypeScript / Angular source files (.ts) and HTML templates (.html) to extract:
    1. Class/Component Structure: Imports, decorators (@Component, @Injectable, etc.),
       selector, templateUrl, templateContent, extends/implements, injected dependencies, fields,
       and method signatures (WITHOUT bodies).
    2. HTML Templates: Automatic fetch and on-demand retrieval of Angular component HTML templates.
    3. Method Bodies: On-demand retrieval of exact method implementations.
    4. Symbol Search & Reference Discovery in worktree.
    """

    @staticmethod
    def extract_template_content(worktree_path: str, template_path_or_url: str) -> Optional[str]:
        """Reads HTML template content from worktree, searching relative paths or rglob."""
        if not worktree_path or not template_path_or_url:
            return None
        wt = Path(worktree_path)
        if not wt.exists():
            return None

        clean_p = template_path_or_url.lstrip("./")
        target = wt / clean_p
        if target.exists():
            try:
                return target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        # Try matching filename under worktree
        file_name = Path(clean_p).name
        matches = list(wt.rglob(file_name))
        if matches:
            try:
                return matches[0].read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        return None

    @staticmethod
    def parse_class_structure(code: str, file_path: str = "", worktree_path: str = "") -> Dict[str, Any]:
        """
        Extracts high-level TypeScript / Angular metadata for token optimization.
        Excludes method implementation bodies. Automatically attaches HTML template content if available.
        """
        lines = code.splitlines()

        # Imports
        import_pattern = r"import\s+(?:type\s+)?(?:\{[^}]*\}|\*\s+as\s+[\w_]+|[\w_]+)\s+from\s+['\"]([^'\"]+)['\"]"
        imports = re.findall(import_pattern, code)

        # Class level decorators (@Component, @Injectable, @Directive, @Pipe, @NgModule, etc.)
        class_decorators = []
        selector = None
        template_url = None
        style_urls = []

        # Find @Component({ ... }), @Injectable(), etc.
        decorator_block_match = re.finditer(r"@(\w+)\s*\(\s*(\{[\s\S]*?\})?\s*\)", code)
        for dmatch in decorator_block_match:
            d_name = dmatch.group(1)
            d_body = dmatch.group(2) or ""
            class_decorators.append(f"@{d_name}")

            if d_name == "Component" and d_body:
                # Selector
                sel_m = re.search(r"selector\s*:\s*['\"]([^'\"]+)['\"]", d_body)
                if sel_m:
                    selector = sel_m.group(1)
                # Template URL
                tmpl_m = re.search(r"templateUrl\s*:\s*['\"]([^'\"]+)['\"]", d_body)
                if tmpl_m:
                    template_url = tmpl_m.group(1)
                # Style URLs
                styles_m = re.search(r"styleUrls\s*:\s*\[([^\]]*)\]", d_body)
                if styles_m:
                    style_urls = [s.strip().strip("'\"") for s in styles_m.group(1).split(",") if s.strip()]

        # Class / Interface / Directive / Service Declaration
        class_decl_pattern = (
            r"(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(class|interface|enum|type)\s+([A-Za-z0-9_]+)"
            r"(?:<[^>]*>)?(?:\s+extends\s+([A-Za-z0-9_,\s<>]+?))?(?:\s+implements\s+([A-Za-z0-9_,\s<>]+?))?(?=\s*\{|\s*$)"
        )
        class_decl_match = re.search(class_decl_pattern, code)

        class_name = ""
        class_kind = "class"
        extends_class = None
        implements_interfaces = []

        if class_decl_match:
            class_kind_raw = class_decl_match.group(1)
            class_name = class_decl_match.group(2)
            raw_extends = class_decl_match.group(3)
            raw_implements = class_decl_match.group(4)

            if "Component" in [d.lstrip("@") for d in class_decorators]:
                class_kind = "component"
            elif "Injectable" in [d.lstrip("@") for d in class_decorators]:
                class_kind = "service"
            elif "Directive" in [d.lstrip("@") for d in class_decorators]:
                class_kind = "directive"
            elif "Pipe" in [d.lstrip("@") for d in class_decorators]:
                class_kind = "pipe"
            else:
                class_kind = class_kind_raw

            if raw_extends:
                extends_class = raw_extends.strip().split("<")[0]

            if raw_implements:
                implements_interfaces = [i.strip().split("<")[0] for i in raw_implements.split(",") if i.strip()]
        else:
            if file_path:
                class_name = Path(file_path).stem

        # Fetch HTML template content if template_url & worktree_path available
        template_content = None
        if template_url and worktree_path:
            # First try relative to file_path directory
            if file_path:
                rel_dir = Path(file_path).parent
                tmpl_rel_path = str(rel_dir / template_url.lstrip("./"))
                template_content = TypeScriptCodeParser.extract_template_content(worktree_path, tmpl_rel_path)

            if not template_content:
                template_content = TypeScriptCodeParser.extract_template_content(worktree_path, template_url)

        # Injected Dependencies & Fields
        injected_dependencies = []
        fields = []

        # Find inject(...) calls in field assignments: e.g. private userService = inject(UserService);
        inject_field_pattern = r"(?:public|private|protected|readonly|\s)*\b([A-Za-z0-9_]+)\s*(?::\s*([A-Za-z0-9_<>\[\]]+))?\s*=\s*inject\(\s*([A-Za-z0-9_]+)\s*\)"
        for im in re.finditer(inject_field_pattern, code):
            f_name, f_type, injected_cls = im.groups()
            injected_dependencies.append(f"{f_name}: {injected_cls or f_type or 'Any'}")
            fields.append({
                "name": f_name,
                "type": f_type or injected_cls or "any",
                "visibility": "private",
                "static": False,
                "readonly": True,
                "decorators": ["@Inject"],
                "is_injected": True,
            })

        # Field declarations (e.g., @Input() productId: string = '';)
        field_pattern = r"^\s*(@(?:Input|Output|HostBinding|ViewChild|Select)(?:\([^)]*\))?\s*)*(public|private|protected)?\s*(static)?\s*(readonly)?\s*([A-Za-z0-9_]+)\s*(?:\?\s*)?(?::\s*([A-Za-z0-9_<>\[\]\s|&?:.]+))?\s*(?:=.*)?;$"
        for line in lines:
            m = re.match(field_pattern, line)
            if m:
                deco_raw, vis, is_static, is_readonly, f_name, f_type = m.groups()
                if f_name in ("constructor", "if", "for", "while", "return", "import", "export"):
                    continue
                f_decos = [a.strip() for a in re.findall(r"@\w+", deco_raw or "")]
                fields.append({
                    "name": f_name,
                    "type": (f_type or "any").strip(),
                    "visibility": vis or "public",
                    "static": bool(is_static),
                    "readonly": bool(is_readonly),
                    "decorators": f_decos,
                    "is_injected": False,
                })

        # Constructors and Methods
        constructors = []
        methods = []

        ctor_pattern = r"^\s*(public|private|protected)?\s*constructor\s*\(([^)]*)\)"
        for idx, line in enumerate(lines, 1):
            cm = re.search(ctor_pattern, line)
            if cm:
                vis, params_raw = cm.groups()
                params = [p.strip() for p in params_raw.split(",") if p.strip()]
                for p in params:
                    if any(kw in p for kw in ["public", "private", "protected", "readonly"]):
                        injected_dependencies.append(p)
                constructors.append({
                    "name": "constructor",
                    "visibility": vis or "public",
                    "parameters": params,
                    "line_number": idx,
                })
                break

        method_hdr_pattern = (
            r"^\s*(@\w+(?:\([^)]*\))?\s*)*"
            r"(public|private|protected)?\s*(async)?\s*(static)?\s*(get|set)?\s*"
            r"([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?::\s*([A-Za-z0-9_<>\[\]\s|&?:.]+))?\s*\{"
        )
        for idx, line in enumerate(lines, 1):
            mm = re.search(method_hdr_pattern, line)
            if mm:
                deco_raw, vis, is_async, is_static, accessor, m_name, params_raw, ret_type = mm.groups()
                if m_name in ("constructor", "if", "for", "while", "switch", "catch", "function"):
                    continue

                m_decos = [a.strip() for a in re.findall(r"@\w+", deco_raw or "")]
                params = [p.strip() for p in params_raw.split(",") if p.strip()]
                full_name = f"{accessor} {m_name}".strip() if accessor else m_name

                methods.append({
                    "name": full_name,
                    "returnType": (ret_type or "void").strip(),
                    "visibility": vis or "public",
                    "parameters": params,
                    "async": bool(is_async),
                    "static": bool(is_static),
                    "is_getter": accessor == "get",
                    "is_setter": accessor == "set",
                    "decorators": m_decos,
                    "line_number": idx,
                })

        return {
            "file_path": file_path,
            "imports": list(set(imports)),
            "class": class_name or Path(file_path).stem if file_path else "Unknown",
            "kind": class_kind,
            "decorators": class_decorators,
            "selector": selector,
            "template_url": template_url,
            "template_content": template_content,
            "style_urls": style_urls,
            "extends": extends_class,
            "implements": implements_interfaces,
            "injected_dependencies": list(set(injected_dependencies)),
            "fields": fields,
            "constructors": constructors,
            "methods": methods,
        }

    @staticmethod
    def extract_method_implementation(code: str, method_name: str, file_path: str = "") -> Optional[Dict[str, Any]]:
        """
        Retrieves the exact implementation body of a TypeScript method by name.
        Uses brace tracking with string, template literal, and comment state handling.
        """
        lines = code.splitlines()
        clean_mname = method_name.split()[-1]

        hdr_regex = re.compile(
            rf"\b(get|set)?\s*{re.escape(clean_mname)}\s*\([^)]*\)\s*(?::\s*[A-Za-z0-9_<>\[\]\s|&?:.]+)?\s*\{{"
        )

        start_line = -1
        start_char_idx = -1

        for idx, line in enumerate(lines):
            match = hdr_regex.search(line)
            if match:
                start_line = idx + 1
                start_char_idx = code.find("{", code.find(line))
                break

        if start_line == -1 or start_char_idx == -1:
            return None

        brace_count = 0
        end_char_idx = -1
        in_string = False
        in_template = False
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
            elif in_template:
                if ch == "`":
                    in_template = False
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
                elif ch == "`":
                    in_template = True
                elif ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_char_idx = i
                        break
            i += 1

        if end_char_idx == -1:
            method_code = "\n".join(lines[start_line - 1 : min(start_line + 50, len(lines))])
            end_line = min(start_line + 50, len(lines))
        else:
            method_code = code[code.rfind("\n", 0, start_char_idx) + 1 : end_char_idx + 1].strip()
            end_line = start_line + method_code.count("\n")

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
        """Searches TypeScript and HTML files in worktree for matching classes, selectors, or methods."""
        results = []
        if not worktree_path or not Path(worktree_path).exists():
            return results

        pattern = re.compile(rf"\b{re.escape(query)}\b", re.IGNORECASE)
        wt = Path(worktree_path)
        for ext in ("*.ts", "*.html"):
            for p in wt.rglob(ext):
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                    for idx, line in enumerate(lines, 1):
                        if pattern.search(line):
                            results.append({
                                "file_path": str(p.relative_to(wt)),
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
        Finds occurrences of a symbol across TypeScript & HTML files and classifies each
        match into 'definition', 'usage', or 'import'.
        """
        results = []
        if not worktree_path or not symbol or not Path(worktree_path).exists():
            return results

        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        def_pattern = re.compile(
            rf"\b(class|interface|enum|type)\s+{re.escape(symbol)}\b"
            rf"|\b{re.escape(symbol)}\s*\([^)]*\)\s*(?::\s*[A-Za-z0-9_<>\[\]]+)?\s*\{{"
            rf"|selector\s*:\s*['\"]{re.escape(symbol)}['\"]"
        )
        import_pattern = re.compile(rf"^\s*import\b.*?\b{re.escape(symbol)}\b")

        wt_path = Path(worktree_path)
        for ext in ("*.ts", "*.html"):
            for p in wt_path.rglob(ext):
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
