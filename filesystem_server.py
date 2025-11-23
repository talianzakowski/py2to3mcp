import asyncio
import os
import json
import traceback
import time
import hashlib
import tempfile
import fnmatch
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("filesystem")

# =============================================================================
# FR-0.3: Safety & Limits Configuration
# =============================================================================
LIMITS = {
    "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB per file
    "max_files_per_operation": 1000,           # Max files to process at once
    "max_content_length": 1_000_000,           # Max characters for content
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
        # FR-1.1: List Files
        Tool(
            name="list_project_files",
            description="List files in a directory with optional pattern matching and exclusions. Returns relative paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "Root directory to list files from"
                    },
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns to include (e.g., ['*.py', '*.js']). Empty means all files."
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., ['venv', '__pycache__', 'node_modules'])"
                    }
                },
                "required": ["root"]
            }
        ),
        # FR-1.2: Read Files
        Tool(
            name="read_files",
            description="Read contents of multiple files. Returns file contents as key-value pairs with truncation if too large.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to read"
                    }
                },
                "required": ["paths"]
            }
        ),
        # FR-1.3: Write Files
        Tool(
            name="write_files",
            description="Write content to multiple files atomically (temp file + rename). Reports per-file success/failure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "object",
                        "description": "Mapping of file paths to content to write",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required": ["files"]
            }
        ),
        # FR-1.4: File Metadata
        Tool(
            name="stat_files",
            description="Get file metadata including size, modification time, and optional hash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to get stats for"
                    },
                    "include_hash": {
                        "type": "boolean",
                        "description": "Include SHA256 hash of file contents (default: false)"
                    }
                },
                "required": ["paths"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):

    # =========================================================================
    # FR-1.1: List Project Files
    # =========================================================================
    if name == "list_project_files":
        root = arguments.get("root", "")
        patterns = arguments.get("patterns", [])
        exclude = arguments.get("exclude", ["venv", "__pycache__", ".git", "node_modules", ".tox", "build", "dist"])

        if not os.path.isdir(root):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidDirectory",
                    "message": f"'{root}' is not a valid directory",
                    "path": root,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        files = []
        files_found = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter excluded directories
            dirnames[:] = [d for d in dirnames if not any(
                fnmatch.fnmatch(d, ex) for ex in exclude
            )]

            for filename in filenames:
                # Check file count limit
                if files_found >= LIMITS["max_files_per_operation"]:
                    break

                # Check if file matches patterns (if specified)
                if patterns:
                    if not any(fnmatch.fnmatch(filename, p) for p in patterns):
                        continue

                # Check exclusions
                if any(fnmatch.fnmatch(filename, ex) for ex in exclude):
                    continue

                filepath = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(filepath, root)
                files.append(rel_path)
                files_found += 1

            if files_found >= LIMITS["max_files_per_operation"]:
                break

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "root": root,
                "files": sorted(files),
                "count": len(files),
                "truncated": files_found >= LIMITS["max_files_per_operation"],
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    # =========================================================================
    # FR-1.2: Read Files
    # =========================================================================
    elif name == "read_files":
        paths = arguments.get("paths", [])

        if len(paths) > LIMITS["max_files_per_operation"]:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "TooManyFiles",
                    "message": f"Requested {len(paths)} files, limit is {LIMITS['max_files_per_operation']}",
                    "requested": len(paths),
                    "limit": LIMITS["max_files_per_operation"],
                }
            )
            return [TextContent(type="text", text=error_resp)]

        results = {}
        errors = {}

        for path in paths:
            try:
                if not os.path.isfile(path):
                    errors[path] = "File not found"
                    continue

                size = os.path.getsize(path)
                if size > LIMITS["max_file_size_bytes"]:
                    errors[path] = f"File too large ({size:,} bytes, limit {LIMITS['max_file_size_bytes']:,})"
                    continue

                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()

                # Truncate if too long
                truncated = False
                if len(content) > LIMITS["max_content_length"]:
                    content = content[:LIMITS["max_content_length"]]
                    truncated = True

                results[path] = {
                    "content": content,
                    "truncated": truncated,
                    "size": size,
                }

            except Exception as e:
                errors[path] = str(e)

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "files": results,
                "errors": errors if errors else None,
                "read_count": len(results),
                "error_count": len(errors),
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    # =========================================================================
    # FR-1.3: Write Files
    # =========================================================================
    elif name == "write_files":
        files = arguments.get("files", {})

        if len(files) > LIMITS["max_files_per_operation"]:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "TooManyFiles",
                    "message": f"Requested {len(files)} files, limit is {LIMITS['max_files_per_operation']}",
                }
            )
            return [TextContent(type="text", text=error_resp)]

        results = {}
        errors = {}

        for path, content in files.items():
            try:
                # Check content length
                if len(content) > LIMITS["max_content_length"]:
                    errors[path] = f"Content too large ({len(content):,} chars, limit {LIMITS['max_content_length']:,})"
                    continue

                # Ensure parent directory exists
                parent_dir = os.path.dirname(path)
                if parent_dir and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)

                # Atomic write: write to temp file, then rename
                dir_name = os.path.dirname(path) or '.'
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=dir_name,
                    delete=False
                ) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name

                # Rename temp file to target (atomic on most systems)
                os.replace(tmp_path, path)

                results[path] = {
                    "written": True,
                    "size": len(content),
                }

            except Exception as e:
                errors[path] = str(e)
                # Clean up temp file if it exists
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "results": results,
                "errors": errors if errors else None,
                "written_count": len(results),
                "error_count": len(errors),
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    # =========================================================================
    # FR-1.4: File Metadata (stat)
    # =========================================================================
    elif name == "stat_files":
        paths = arguments.get("paths", [])
        include_hash = arguments.get("include_hash", False)

        if len(paths) > LIMITS["max_files_per_operation"]:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "TooManyFiles",
                    "message": f"Requested {len(paths)} files, limit is {LIMITS['max_files_per_operation']}",
                }
            )
            return [TextContent(type="text", text=error_resp)]

        results = {}
        errors = {}

        for path in paths:
            try:
                if not os.path.exists(path):
                    errors[path] = "File not found"
                    continue

                stat = os.stat(path)

                file_info = {
                    "size": stat.st_size,
                    "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
                    "ctime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_ctime)),
                    "is_file": os.path.isfile(path),
                    "is_dir": os.path.isdir(path),
                }

                # Include hash if requested (and file isn't too large)
                if include_hash and os.path.isfile(path):
                    if stat.st_size <= LIMITS["max_file_size_bytes"]:
                        sha256 = hashlib.sha256()
                        with open(path, 'rb') as f:
                            for chunk in iter(lambda: f.read(8192), b''):
                                sha256.update(chunk)
                        file_info["sha256"] = sha256.hexdigest()
                    else:
                        file_info["sha256"] = None
                        file_info["hash_skipped"] = "File too large"

                results[path] = file_info

            except Exception as e:
                errors[path] = str(e)

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "files": results,
                "errors": errors if errors else None,
                "stat_count": len(results),
                "error_count": len(errors),
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
