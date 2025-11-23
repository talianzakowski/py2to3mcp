# MCP Server Suite

A collection of MCP (Model Context Protocol) servers that extend Claude Code's capabilities for Python development and code migration.

## Servers Overview

| Server | Purpose | Tools |
|--------|---------|-------|
| **my-first-server** | Basic example | 2 |
| **py2to3-migration** | Python 2 to 3 migration | 11 |
| **filesystem** | File operations | 4 |
| **codeindex** | Code search | 2 |

## Prerequisites

- Python 3.9 or higher
- Claude Code CLI or VS Code extension

## Quick Setup

### 1. Clone and Setup Environment

```bash
git clone <repository-url>
cd myfirstMCPserver
python3 -m venv mcp-venv
source mcp-venv/bin/activate  # Windows: mcp-venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Claude Code

Edit `~/.claude.json` and add:

```json
{
  "/absolute/path/to/myfirstMCPserver": {
    "mcpServers": {
      "my-first-server": {
        "command": "/absolute/path/to/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/absolute/path/to/myfirstMCPserver/mcp_server.py"]
      },
      "py2to3-migration": {
        "command": "/absolute/path/to/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/absolute/path/to/myfirstMCPserver/py2to3_server.py"]
      },
      "filesystem": {
        "command": "/absolute/path/to/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/absolute/path/to/myfirstMCPserver/filesystem_server.py"]
      },
      "codeindex": {
        "command": "/absolute/path/to/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/absolute/path/to/myfirstMCPserver/codeindex_server.py"]
      }
    }
  }
}
```

**Important:** Use `mcpServers` (camelCase), replace paths with absolute paths.

### 3. Restart Claude Code

CLI: Exit and restart | VS Code: Reload Window

---

## py2to3-migration Server

### Tools

| Tool | Description |
|------|-------------|
| `analyze_py2_code` | Analyze code string for Python 2 patterns |
| `run_2to3` | Run fissix conversion and show results |
| `convert_print_statements` | Convert print statements to functions |
| `check_syntax` | Validate Python 3 syntax |
| `get_migration_guide` | Get guides for specific issues |
| `analyze_directory` | Scan directory for Python 2 patterns |
| `convert_file` | Convert file with automatic backup |
| `migration_report` | Generate prioritized migration report |
| `validate_conversion` | Validate converted file, identify review items |
| `conversion_report` | Compare original vs converted files |
| `scan_compat` | Scan files with classified issues (FR-4) |

### Use Cases

#### Convert a Folder and All Subfolders

**Step 1: Get Migration Report**
```
"Generate a migration report for /path/to/legacy/project"
```

Returns:
- Total files and issues
- Estimated effort
- Priority files (quick wins, high density, major refactors)
- Issues by category

**Step 2: Convert Files**
```
"Convert /path/to/legacy/project/module.py to Python 3"
```

Creates backup at `module.py.py2.bak` and converts in place.

**Step 3: Get Conversion Report**
```
"Generate a conversion report comparing /path/to/module.py.py2.bak with /path/to/module.py"
```

Shows:
- Fix rate percentage
- What patterns were fixed
- What still needs attention

**Step 4: Validate for Human Review**
```
"Validate the conversion of /path/to/module.py"
```

Identifies:
- Remaining Python 2 patterns
- Runtime issues needing human judgment (division, file I/O, pickle)
- Severity levels (high/medium/low)
- Test recommendations

#### Batch Scan Specific Files (FR-4)

```
"Scan these files for Python 2 compatibility: /path/file1.py, /path/file2.py, /path/file3.py"
```

Uses `scan_compat` to return classified issues with:
- Code identifiers (PY2-ITER-001, PY2-LIB-002, etc.)
- Severity (error/warning/info)
- Category (iterators, text-types, stdlib-move, etc.)
- Suggested fixes

#### Check Specific Migration Issues

```
"Get a migration guide for unicode handling"
"Get a migration guide for dictionary methods"
```

Available guides: print, unicode, dict_methods, exceptions, division, imports

### Issue Classification (scan_compat)

**Severity Levels:**
- `error` - Won't run in Python 3
- `warning` - May cause issues
- `info` - Style/best practice

**Categories:**
- `iterators` - xrange, iteritems, has_key
- `text-types` - unicode, basestring, long
- `operators` - <>, backticks
- `syntax` - print statements, except comma
- `stdlib-move` - ConfigParser, urllib2, Queue
- `builtins` - raw_input, execfile, reduce

---

## filesystem Server

### Tools

| Tool | Description |
|------|-------------|
| `list_project_files` | List files with glob patterns and exclusions |
| `read_files` | Read multiple files with truncation support |
| `write_files` | Atomic writes (temp + rename) |
| `stat_files` | Get metadata, size, hash |

### Use Cases

#### Explore Project Structure
```
"List all Python files in /path/to/project"
"List all test files matching *_test.py"
```

#### Batch Read Files
```
"Read these files: config.py, settings.py, constants.py"
```

#### Safe File Updates
```
"Write the updated content to /path/to/file.py"
```

Uses atomic writes to prevent corruption.

---

## codeindex Server

### Tools

| Tool | Description |
|------|-------------|
| `search_text` | Regex search with file/line/column/context |
| `find_import` | Find all imports of a module |

### Use Cases

#### Find Code Patterns
```
"Search for 'def.*error' in /path/to/project"
"Find all uses of 'requests.get' in the codebase"
```

#### Audit Dependencies
```
"Find all imports of 'json' in /path/to/project"
"Find all imports of 'pickle' in /path/to/project"
```

Returns file locations grouped by file.

---

## Example Workflows

### Complete Python 2 to 3 Migration

```
1. "Generate a migration report for /legacy/project"
   → See overview, effort estimate, priority files

2. "Scan these files for compatibility: /legacy/project/main.py, /legacy/project/utils.py"
   → Get classified issues with suggested fixes

3. "Convert /legacy/project/main.py to Python 3"
   → Auto-convert with backup

4. "Generate conversion report for /legacy/project/main.py.py2.bak vs /legacy/project/main.py"
   → See what was fixed

5. "Validate the conversion of /legacy/project/main.py"
   → Get human review items and test recommendations

6. Repeat for each file, addressing high-severity items first
```

### Codebase Exploration

```
1. "List all Python files in /project excluding venv and __pycache__"
   → Get project structure

2. "Find all imports of 'requests' in /project"
   → See dependency usage

3. "Search for 'TODO|FIXME' in /project"
   → Find work items
```

### Dependency Audit

```
1. "Find all imports of 'pickle' in /project"
   → Identify security/compatibility concerns

2. "Validate conversion of files using pickle"
   → Get specific guidance on pickle protocol issues
```

---

## Response Format

All tools return standardized JSON responses:

```json
{
  "tool": "tool_name",
  "status": "success",
  "timestamp": "2025-01-01T00:00:00Z",
  "data": { ... },
  "metadata": {
    "limits": { ... }
  }
}
```

### Safety Limits

- Max file size: 10 MB
- Max files per operation: 1000
- Max code length: 1,000,000 characters
- Timeout: 300 seconds

---

## Troubleshooting

### Server Not Connecting

1. Check `~/.claude.json` location and syntax
2. Verify absolute paths to Python and scripts
3. Use `mcpServers` (camelCase)
4. Test manually: `/path/to/mcp-venv/bin/python /path/to/server.py`

### Tools Not Appearing

- Restart Claude Code after config changes
- Verify JSON syntax (no trailing commas)
- Check server is under correct project path

### Conversion Issues

- Run `validate_conversion` to identify remaining issues
- Check for runtime issues (division, encoding) that need manual review
- Use `get_migration_guide` for specific patterns

---

## Creating Your Own MCP Server

Basic template:

```python
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("my-server")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="my_tool",
            description="Description",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "Param description"}
                },
                "required": ["param1"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "my_tool":
        return [TextContent(type="text", text=f"Result: {arguments.get('param1')}")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

---

## References

- [MCP Documentation](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Fissix (lib2to3 fork)](https://github.com/jreese/fissix)

## Test Samples

The `test_samples/` directory contains Python 2 example files for testing:

- `simple_prints.py` - Print statements
- `dict_operations.py` - iteritems, has_key
- `string_unicode.py` - Unicode, basestring
- `exceptions_old.py` - Old except/raise syntax
- `imports_old.py` - Renamed stdlib modules
- `builtins_old.py` - Deprecated builtins
- `division_issues.py` - Integer division (runtime)
- `file_encoding.py` - File I/O, pickle (runtime)
- `classes_old.py` - Old-style classes
- `complex_mixed.py` - All patterns combined
