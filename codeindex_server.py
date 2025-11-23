import asyncio
import os
import re
import json
import traceback
import time
import fnmatch
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("codeindex")

# =============================================================================
# FR-0.3: Safety & Limits Configuration
# =============================================================================
LIMITS = {
    "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB per file
    "max_files_per_operation": 1000,           # Max files to process at once
    "max_results": 500,                        # Max search results to return
    "timeout_seconds": 300,                     # 5 minute timeout for operations
}

# =============================================================================
# FR-0.2: Common Response Schema
# =============================================================================
def create_response(
    tool_name: str,
    status: str,
    data: dict = None,
    error: dict = None,
    metadata: dict = None
) -> str:
    """Create a standardized JSON response for all tools."""
    response = {
        "tool": tool_name,
        "status": status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if data is not None:
        response["data"] = data

    if error is not None:
        response["error"] = error

    if metadata is not None:
        response["metadata"] = metadata

    return json.dumps(response, indent=2, default=str)


def error_response(tool_name: str, exception: Exception, context: str = None) -> str:
    """Create a standardized error response with full debugging info."""
    tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
    tb_snippet = ''.join(tb_lines[-3:]) if len(tb_lines) > 3 else ''.join(tb_lines)

    error_detail = {
        "type": type(exception).__name__,
        "message": str(exception),
        "traceback_snippet": tb_snippet.strip(),
    }

    if context:
        error_detail["context"] = context

    return create_response(
        tool_name=tool_name,
        status="error",
        error=error_detail,
        metadata={"limits": LIMITS}
    )


@server.list_tools()
async def list_tools():
    return [
        # FR-2.1: Search Text
        Tool(
            name="search_text",
            description="Search for text patterns in files using regex. Returns matches with file, line, column, and context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in"
                    },
                    "file_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns for files to include (e.g., ['*.py', '*.js'])"
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., ['venv', 'node_modules'])"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Case sensitive search (default: true)"
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of context lines before/after match (default: 0)"
                    }
                },
                "required": ["pattern", "path"]
            }
        ),
        # FR-2.2: Find Import
        Tool(
            name="find_import",
            description="Find all imports of a module across files. Searches for import statements by module name or fragment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Module name or fragment to find (e.g., 'os', 'json', 'requests')"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in"
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., ['venv', 'node_modules'])"
                    }
                },
                "required": ["module", "path"]
            }
        )
    ]


def collect_files(root: str, file_patterns: list = None, exclude: list = None) -> list:
    """Collect files from directory matching patterns."""
    if exclude is None:
        exclude = ["venv", "__pycache__", ".git", "node_modules", ".tox", "build", "dist"]

    files = []

    if os.path.isfile(root):
        return [root]

    if not os.path.isdir(root):
        return []

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter excluded directories
        dirnames[:] = [d for d in dirnames if not any(
            fnmatch.fnmatch(d, ex) for ex in exclude
        )]

        for filename in filenames:
            if len(files) >= LIMITS["max_files_per_operation"]:
                break

            # Check file patterns
            if file_patterns:
                if not any(fnmatch.fnmatch(filename, p) for p in file_patterns):
                    continue

            # Check exclusions
            if any(fnmatch.fnmatch(filename, ex) for ex in exclude):
                continue

            filepath = os.path.join(dirpath, filename)
            files.append(filepath)

        if len(files) >= LIMITS["max_files_per_operation"]:
            break

    return files


@server.call_tool()
async def call_tool(name: str, arguments: dict):

    # =========================================================================
    # FR-2.1: Search Text
    # =========================================================================
    if name == "search_text":
        pattern = arguments.get("pattern", "")
        path = arguments.get("path", "")
        file_patterns = arguments.get("file_patterns", [])
        exclude = arguments.get("exclude", ["venv", "__pycache__", ".git", "node_modules"])
        case_sensitive = arguments.get("case_sensitive", True)
        context_lines = arguments.get("context_lines", 0)

        if not pattern:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidPattern",
                    "message": "Pattern cannot be empty",
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # Compile regex
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidRegex",
                    "message": f"Invalid regex pattern: {str(e)}",
                    "pattern": pattern,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # Collect files
        files = collect_files(path, file_patterns, exclude)

        if not files:
            response = create_response(
                tool_name=name,
                status="success",
                data={
                    "matches": [],
                    "total_matches": 0,
                    "files_searched": 0,
                    "truncated": False,
                },
                metadata={"limits": LIMITS}
            )
            return [TextContent(type="text", text=response)]

        matches = []
        files_with_matches = set()
        files_searched = 0

        for filepath in files:
            try:
                # Check file size
                size = os.path.getsize(filepath)
                if size > LIMITS["max_file_size_bytes"]:
                    continue

                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                files_searched += 1

                for line_num, line in enumerate(lines, 1):
                    for match in regex.finditer(line):
                        if len(matches) >= LIMITS["max_results"]:
                            break

                        # Get context lines
                        context_before = []
                        context_after = []

                        if context_lines > 0:
                            start = max(0, line_num - 1 - context_lines)
                            end = min(len(lines), line_num + context_lines)
                            context_before = [l.rstrip('\n\r') for l in lines[start:line_num - 1]]
                            context_after = [l.rstrip('\n\r') for l in lines[line_num:end]]

                        match_info = {
                            "file": filepath,
                            "line": line_num,
                            "column": match.start() + 1,
                            "text": line.rstrip('\n\r'),
                            "match": match.group(),
                        }

                        if context_before:
                            match_info["context_before"] = context_before
                        if context_after:
                            match_info["context_after"] = context_after

                        matches.append(match_info)
                        files_with_matches.add(filepath)

                    if len(matches) >= LIMITS["max_results"]:
                        break

            except Exception:
                continue

            if len(matches) >= LIMITS["max_results"]:
                break

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "matches": matches,
                "total_matches": len(matches),
                "files_searched": files_searched,
                "files_with_matches": len(files_with_matches),
                "truncated": len(matches) >= LIMITS["max_results"],
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    # =========================================================================
    # FR-2.2: Find Import
    # =========================================================================
    elif name == "find_import":
        module = arguments.get("module", "")
        path = arguments.get("path", "")
        exclude = arguments.get("exclude", ["venv", "__pycache__", ".git", "node_modules"])

        if not module:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidModule",
                    "message": "Module name cannot be empty",
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # Patterns for Python imports
        # import module, import module as alias
        # from module import something
        import_patterns = [
            rf'\bimport\s+[\w,\s]*\b{re.escape(module)}\b',
            rf'\bfrom\s+{re.escape(module)}(?:\.\w+)*\s+import\b',
            rf'\bfrom\s+\w+(?:\.\w+)*\s+import\s+[\w,\s]*\b{re.escape(module)}\b',
        ]

        combined_pattern = '|'.join(import_patterns)
        regex = re.compile(combined_pattern)

        # Only search Python files
        files = collect_files(path, ["*.py"], exclude)

        imports = []
        files_searched = 0

        for filepath in files:
            try:
                size = os.path.getsize(filepath)
                if size > LIMITS["max_file_size_bytes"]:
                    continue

                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                files_searched += 1

                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        if len(imports) >= LIMITS["max_results"]:
                            break

                        imports.append({
                            "file": filepath,
                            "line": line_num,
                            "text": line.rstrip('\n\r'),
                        })

            except Exception:
                continue

            if len(imports) >= LIMITS["max_results"]:
                break

        # Group by file
        by_file = {}
        for imp in imports:
            file = imp["file"]
            if file not in by_file:
                by_file[file] = []
            by_file[file].append({
                "line": imp["line"],
                "text": imp["text"],
            })

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "module": module,
                "imports": imports,
                "by_file": by_file,
                "total_imports": len(imports),
                "files_searched": files_searched,
                "files_with_imports": len(by_file),
                "truncated": len(imports) >= LIMITS["max_results"],
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
