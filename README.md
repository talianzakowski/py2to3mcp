# MCP Server Examples

This repository contains two MCP (Model Context Protocol) servers that extend Claude Code's capabilities:

1. **my-first-server** - Basic example with greeting and calculator tools
2. **py2to3-migration** - Python 2 to 3 migration assistant with analysis and conversion tools

## Prerequisites

- Python 3.9 or higher
- Claude Code CLI or VS Code extension

## Setup from First Principles

### 1. Clone or Create the Project

```bash
mkdir myfirstMCPserver
cd myfirstMCPserver
```

### 2. Create a Virtual Environment

```bash
python3 -m venv mcp-venv
source mcp-venv/bin/activate  # On Windows: mcp-venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install mcp fissix
```

- `mcp` - Model Context Protocol SDK
- `fissix` - Modern lib2to3 fork for Python 3.9+ (used by py2to3 server)

### 4. Create the Server Files

Copy `mcp_server.py` and `py2to3_server.py` to your project directory.

### 5. Configure Claude Code

Add the MCP servers to your Claude Code configuration. Edit `~/.claude.json` and add the following under your project path:

```json
{
  "/path/to/your/myfirstMCPserver": {
    "mcpServers": {
      "my-first-server": {
        "command": "/path/to/your/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/path/to/your/myfirstMCPserver/mcp_server.py"]
      },
      "py2to3-migration": {
        "command": "/path/to/your/myfirstMCPserver/mcp-venv/bin/python",
        "args": ["/path/to/your/myfirstMCPserver/py2to3_server.py"]
      }
    }
  }
}
```

**Important:** Replace `/path/to/your/myfirstMCPserver` with the actual absolute path to your project directory.

### 6. Restart Claude Code

After editing the configuration, restart Claude Code (or reload the VS Code window) for the MCP servers to be loaded.

### 7. Verify the Servers

Ask Claude: "Can you see the MCP servers?"

Claude should list the available tools from both servers.

## Available Tools

### my-first-server

| Tool | Description |
|------|-------------|
| `get_greeting` | Generate a personalized greeting |
| `calculate` | Perform basic math operations (add, subtract, multiply, divide) |

### py2to3-migration

| Tool | Description |
|------|-------------|
| `analyze_py2_code` | Analyze code for Python 2 patterns with detailed reporting |
| `run_2to3` | Run fissix/2to3 conversion and show results |
| `convert_print_statements` | Convert print statements to print() functions |
| `check_syntax` | Check if code is valid Python 3 syntax |
| `get_migration_guide` | Get migration guides for specific issues (print, unicode, dict_methods, exceptions, division, imports) |
| `analyze_directory` | Scan a directory for Python 2 patterns across all .py files |
| `convert_file` | Convert a Python 2 file to Python 3 with automatic backup |
| `migration_report` | Generate comprehensive migration report with effort estimates |

## Usage Examples

### Basic Server

```
"Give me a greeting for Alice"
"Calculate 42 multiplied by 17"
```

### Python 2 to 3 Migration

```
"Analyze this Python file for Python 2 patterns"
"Generate a migration report for /path/to/legacy/project"
"Convert /path/to/file.py to Python 3"
```

## Troubleshooting

### MCP server not connecting

1. **Check the Python path** - Ensure the command points to the venv's Python:
   ```bash
   which python  # Should show your venv path when activated
   ```

2. **Check config syntax** - Use `mcpServers` (camelCase), not `mcp_servers`

3. **Check file permissions** - Ensure the .py files are readable

4. **Test manually** - Run the server directly to check for errors:
   ```bash
   /path/to/mcp-venv/bin/python /path/to/mcp_server.py
   ```
   (It will wait for input - this means it's working. Press Ctrl+C to exit)

### Tools not appearing

- Restart Claude Code after configuration changes
- Check that the config is under the correct project path in `~/.claude.json`

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
            description="Description of what the tool does",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Parameter description"
                    }
                },
                "required": ["param1"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "my_tool":
        param1 = arguments.get("param1", "")
        result = f"Processed: {param1}"
        return [TextContent(type="text", text=result)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## References

- [MCP Documentation](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Fissix (lib2to3 fork)](https://github.com/jreese/fissix)
