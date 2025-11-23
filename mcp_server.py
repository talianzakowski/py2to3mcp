import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

# Initialize the server
server = Server("my-first-mcp-server")

# Define available tools
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_greeting",
            description="Generate a personalized greeting",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the person to greet"
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="calculate",
            description="Perform basic math operations",
            inputSchema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"],
                        "description": "Math operation to perform"
                    },
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["operation", "a", "b"]
            }
        )
    ]

# Handle tool calls
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_greeting":
        person_name = arguments.get("name", "World")
        return [TextContent(type="text", text=f"Hello, {person_name}! Welcome to MCP.")]

    elif name == "calculate":
        op = arguments["operation"]
        a, b = arguments["a"], arguments["b"]

        if op == "add":
            result = a + b
        elif op == "subtract":
            result = a - b
        elif op == "multiply":
            result = a * b
        elif op == "divide":
            result = a / b if b != 0 else "Error: division by zero"

        return [TextContent(type="text", text=f"Result: {result}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]

# Define available resources
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="info://server-info",
            name="Server Info",
            description="Information about this MCP server",
            mimeType="text/plain"
        )
    ]

@server.read_resource()
async def read_resource(uri: str):
    if uri == "info://server-info":
        return "My First MCP Server\n\nTools: get_greeting, calculate\nVersion: 0.1.0"
    return "Resource not found"

# Main entry point
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
