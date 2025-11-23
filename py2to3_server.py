import asyncio
import ast
import re
import subprocess
import tempfile
import os
import json
import traceback
import time
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

# Try to import fissix (modern lib2to3 fork for Python 3.9+)
try:
    from fissix import refactor
    HAS_FISSIX = True
except ImportError:
    HAS_FISSIX = False

server = Server("py2to3-migration")

# =============================================================================
# FR-0.3: Safety & Limits Configuration
# =============================================================================
LIMITS = {
    "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB per file
    "max_files_per_operation": 1000,           # Max files to process at once
    "max_code_length": 1_000_000,              # Max characters for code input
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
    """
    Create a standardized JSON response for all tools.

    Args:
        tool_name: Name of the tool that was called
        status: "success" or "error"
        data: The actual result data (for success responses)
        error: Error details (for error responses)
        metadata: Additional debugging metadata

    Returns:
        JSON-formatted response string
    """
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
    """
    Create a standardized error response with full debugging info.

    Args:
        tool_name: Name of the tool that failed
        exception: The exception that was raised
        context: Additional context about what was being attempted

    Returns:
        JSON-formatted error response string
    """
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
        metadata={
            "limits": LIMITS,
            "fissix_available": HAS_FISSIX,
        }
    )


def check_file_size(filepath: str, tool_name: str) -> str:
    """
    Check if a file exceeds the size limit.

    Returns:
        Error response string if limit exceeded, None otherwise
    """
    try:
        size = os.path.getsize(filepath)
        if size > LIMITS["max_file_size_bytes"]:
            return create_response(
                tool_name=tool_name,
                status="error",
                error={
                    "type": "FileSizeLimitExceeded",
                    "message": f"File size ({size:,} bytes) exceeds limit ({LIMITS['max_file_size_bytes']:,} bytes)",
                    "file": filepath,
                    "size_bytes": size,
                    "limit_bytes": LIMITS["max_file_size_bytes"],
                }
            )
    except OSError as e:
        return error_response(tool_name, e, f"checking file size: {filepath}")

    return None


def check_code_length(code: str, tool_name: str) -> str:
    """
    Check if code input exceeds the length limit.

    Returns:
        Error response string if limit exceeded, None otherwise
    """
    if len(code) > LIMITS["max_code_length"]:
        return create_response(
            tool_name=tool_name,
            status="error",
            error={
                "type": "CodeLengthLimitExceeded",
                "message": f"Code length ({len(code):,} chars) exceeds limit ({LIMITS['max_code_length']:,} chars)",
                "length": len(code),
                "limit": LIMITS["max_code_length"],
            }
        )
    return None

# Python 2 patterns to detect (regex-based fallback + additional patterns)
PY2_PATTERNS = {
    # Print and I/O
    "print_statement": r'^[^#]*\bprint\s+[^(=]',
    "raw_input": r'\braw_input\s*\(',
    "execfile": r'\bexecfile\s*\(',

    # String/Unicode
    "unicode_literal": r'\bu["\']',
    "unicode_type": r'\bunicode\s*\(',
    "basestring": r'\bbasestring\b',
    "backticks": r'`[^`]+`',

    # Numbers - improved to catch hex long literals
    "long_suffix": r'(?:\d+|0[xX][0-9a-fA-F]+)[lL]\b',
    "old_octal": r'(?<!\w)0\d{2,}(?![xXbBoOlL])\b',

    # Iterators and functions
    "xrange": r'\bxrange\s*\(',
    "reduce": r'(?<![\.\w])reduce\s*\(',
    "apply": r'(?<!\w)apply\s*\(',
    "cmp_func": r'\bcmp\s*[(\=]',  # cmp() or cmp=
    "coerce": r'\bcoerce\s*\(',
    "intern": r'(?<!sys\.)intern\s*\(',
    "file_builtin": r'(?<!\w)file\s*\(',
    "buffer_builtin": r'(?<!\w)buffer\s*\(',

    # Dictionary methods
    "iteritems": r'\.iteritems\s*\(',
    "iterkeys": r'\.iterkeys\s*\(',
    "itervalues": r'\.itervalues\s*\(',
    "has_key": r'\.has_key\s*\(',
    "viewitems": r'\.viewitems\s*\(',
    "viewkeys": r'\.viewkeys\s*\(',
    "viewvalues": r'\.viewvalues\s*\(',

    # Operators and syntax
    "old_ne": r'<>',
    "except_comma": r'except\s+[\w.]+\s*,\s*\w+',
    "old_raise": r'raise\s+[\w.]+\s*,',
    "old_repr": r'`[^`]+`',

    # Renamed modules
    "configparser": r'(?<!\w)ConfigParser\b',
    "queue_module": r'(?<!\w)Queue\b',
    "urllib2": r'\burllib2\b',
    "urlparse": r'\burlparse\b',
    "stringio": r'(?<!\w)StringIO\b',
    "cstringio": r'\bcStringIO\b',
    "cpickle": r'\bcPickle\b',
    "tkinter": r'(?<!\w)Tkinter\b',
    "http_cookiejar": r'\bcookielib\b',
    "thread_module": r'(?<!\w)thread\b(?!ing)',
    "commands_module": r'\bcommands\b',
    "htmlparser": r'\bHTMLParser\b',
    "httplib": r'\bhttplib\b',
}

def get_fissix_fixers():
    """Get all available fissix fixers for comprehensive detection."""
    if not HAS_FISSIX:
        return []

    from fissix import fixes
    import pkgutil

    fixer_names = []
    for importer, modname, ispkg in pkgutil.iter_modules(fixes.__path__):
        if modname.startswith('fix_'):
            fixer_names.append(f'fissix.fixes.{modname}')
    return fixer_names

def analyze_with_fissix(code):
    """Use fissix to analyze code and find Python 2 patterns."""
    if not HAS_FISSIX:
        return []

    issues = []

    # Create a refactoring tool with all fixers
    fixers = get_fissix_fixers()

    try:
        rt = refactor.RefactoringTool(fixers, options={'print_function': False})

        # Parse the code
        tree = rt.refactor_string(code + '\n', '<input>')

        # The refactoring tool will have applied fixes - we can compare
        # original vs refactored to find issues
        refactored = str(tree)

        if refactored != code + '\n':
            # Find differences line by line
            orig_lines = code.split('\n')
            new_lines = refactored.rstrip('\n').split('\n')

            for i, (orig, new) in enumerate(zip(orig_lines, new_lines), 1):
                if orig != new:
                    issues.append({
                        'line': i,
                        'original': orig,
                        'converted': new,
                        'type': 'fissix_conversion'
                    })
    except Exception as e:
        # If fissix parsing fails, that's also useful info
        issues.append({
            'line': 0,
            'original': str(e),
            'converted': '',
            'type': 'parse_error'
        })

    return issues

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="analyze_py2_code",
            description="Analyze Python code for Python 2 patterns that need migration to Python 3. Returns a list of issues found with line numbers and descriptions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to analyze"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="run_2to3",
            description="Run Python's 2to3 tool on code and return the suggested changes as a diff",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 2 code to convert"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="convert_print_statements",
            description="Convert Python 2 print statements to Python 3 print() functions",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code with print statements"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="check_syntax",
            description="Check if code is valid Python 3 syntax",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to check"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="get_migration_guide",
            description="Get a migration guide for a specific Python 2 to 3 issue",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "description": "The issue type (e.g., 'print', 'unicode', 'dict_methods', 'exceptions')"
                    }
                },
                "required": ["issue"]
            }
        ),
        Tool(
            name="analyze_directory",
            description="Scan a directory for Python 2 patterns across all .py files. Returns a summary report with issue counts per file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to scan"
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., 'venv', '__pycache__', 'node_modules')"
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="convert_file",
            description="Convert a Python 2 file to Python 3 in place, with automatic backup",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file to convert"
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "Create a .py2.bak backup file (default: true)"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Show changes without writing (default: false)"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="migration_report",
            description="Generate a comprehensive migration report for a directory with prioritized files and effort estimates",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to analyze"
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude"
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="validate_conversion",
            description="Validate a converted Python file and identify issues requiring human or AI review. Returns syntax check, remaining patterns, and flags for manual investigation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the converted Python file to validate"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="conversion_report",
            description="Generate a post-conversion report comparing original and converted files. Shows what changed, what needs review, and test recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "original_path": {
                        "type": "string",
                        "description": "Path to original file (or .py2.bak backup)"
                    },
                    "converted_path": {
                        "type": "string",
                        "description": "Path to converted Python 3 file"
                    }
                },
                "required": ["original_path", "converted_path"]
            }
        ),
        Tool(
            name="scan_compat",
            description="Run compatibility scan on specific files to detect Python 2 patterns. Returns classified issues with severity, category, and suggested fixes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to analyze"
                    }
                },
                "required": ["files"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "analyze_py2_code":
        code = arguments.get("code", "")

        # FR-0.3: Check code length limit
        limit_error = check_code_length(code, name)
        if limit_error:
            return [TextContent(type="text", text=limit_error)]

        issues = []
        issue_counts = {}  # Track counts by category
        lines = code.split('\n')
        fissix_conversions = {}  # Track fissix-suggested conversions

        # First, use fissix for comprehensive AST-based analysis
        if HAS_FISSIX:
            fissix_issues = analyze_with_fissix(code)
            for issue in fissix_issues:
                if issue['type'] == 'fissix_conversion':
                    fissix_conversions[issue['line']] = issue['converted']

        # Pattern descriptions
        issue_descriptions = {
            # Print and I/O
            "print_statement": "Print statement (use print() function)",
            "raw_input": "raw_input() (use input() in Python 3)",
            "execfile": "execfile() (use exec(open().read()))",

            # String/Unicode
            "unicode_literal": "Unicode literal u'' (not needed in Python 3)",
            "unicode_type": "unicode() (use str in Python 3)",
            "basestring": "basestring (use str in Python 3)",
            "backticks": "Backticks `x` for repr (use repr(x))",

            # Numbers
            "long_suffix": "Long integer suffix L (not needed in Python 3)",
            "old_octal": "Old octal literal 0755 (use 0o755)",

            # Iterators and functions
            "xrange": "xrange() (use range() in Python 3)",
            "reduce": "reduce() (import from functools)",
            "apply": "apply() (use func(*args, **kwargs))",
            "cmp_func": "cmp() or cmp= (removed in Python 3)",
            "coerce": "coerce() (removed in Python 3)",
            "intern": "intern() (use sys.intern())",
            "file_builtin": "file() builtin (use open())",
            "buffer_builtin": "buffer() (use memoryview())",

            # Dictionary methods
            "iteritems": ".iteritems() (use .items() in Python 3)",
            "iterkeys": ".iterkeys() (use .keys() in Python 3)",
            "itervalues": ".itervalues() (use .values() in Python 3)",
            "has_key": ".has_key() (use 'in' operator)",
            "viewitems": ".viewitems() (use .items() in Python 3)",
            "viewkeys": ".viewkeys() (use .keys() in Python 3)",
            "viewvalues": ".viewvalues() (use .values() in Python 3)",

            # Operators and syntax
            "old_ne": "<> operator (use !=)",
            "except_comma": "Old except syntax (use 'as' keyword)",
            "old_raise": "Old raise syntax (use raise E('msg'))",
            "old_repr": "Backticks for repr (use repr())",

            # Renamed modules
            "configparser": "ConfigParser (use configparser)",
            "queue_module": "Queue (use queue)",
            "urllib2": "urllib2 (use urllib.request)",
            "urlparse": "urlparse (use urllib.parse)",
            "stringio": "StringIO (use io.StringIO)",
            "cstringio": "cStringIO (use io.StringIO)",
            "cpickle": "cPickle (use pickle)",
            "tkinter": "Tkinter (use tkinter)",
            "http_cookiejar": "cookielib (use http.cookiejar)",
            "thread_module": "thread (use _thread or threading)",
            "commands_module": "commands (use subprocess)",
            "htmlparser": "HTMLParser (use html.parser)",
            "httplib": "httplib (use http.client)",
        }

        # Regex-based pattern matching
        for i, line in enumerate(lines, 1):
            # Skip shebang and encoding lines
            if i <= 2 and (line.startswith('#!') or 'coding' in line):
                continue

            for pattern_name, pattern in PY2_PATTERNS.items():
                if re.search(pattern, line):
                    # Track count
                    issue_counts[pattern_name] = issue_counts.get(pattern_name, 0) + 1

                    issue_desc = issue_descriptions.get(pattern_name, pattern_name)
                    issues.append(f"Line {i}: {issue_desc}")
                    issues.append(f"  → {line.strip()}")

                    # Show fissix conversion if available
                    if i in fissix_conversions:
                        issues.append(f"  ✓ {fissix_conversions[i].strip()}")

        if not issues:
            return [TextContent(type="text", text="No Python 2 patterns detected. Code appears Python 3 compatible.")]

        # Build summary statistics
        total = len([x for x in issues if x.startswith('Line ')])

        # Group counts by category
        categories = {
            "Print/IO": ["print_statement", "raw_input", "execfile"],
            "String/Unicode": ["unicode_literal", "unicode_type", "basestring", "backticks", "old_repr"],
            "Numbers": ["long_suffix", "old_octal"],
            "Builtins": ["xrange", "reduce", "apply", "cmp_func", "coerce", "intern", "file_builtin", "buffer_builtin"],
            "Dict methods": ["iteritems", "iterkeys", "itervalues", "has_key", "viewitems", "viewkeys", "viewvalues"],
            "Syntax": ["old_ne", "except_comma", "old_raise"],
            "Imports": ["configparser", "queue_module", "urllib2", "urlparse", "stringio", "cstringio", "cpickle", "tkinter", "http_cookiejar", "thread_module", "commands_module", "htmlparser", "httplib"],
        }

        summary = f"## Analysis Summary\n\n**Total issues found: {total}**\n"
        if HAS_FISSIX:
            summary += "*Analysis powered by fissix*\n\n"
        else:
            summary += "*Install fissix for enhanced analysis: pip install fissix*\n\n"

        summary += "### By Category:\n"

        for cat_name, patterns in categories.items():
            cat_count = sum(issue_counts.get(p, 0) for p in patterns)
            if cat_count > 0:
                summary += f"- **{cat_name}**: {cat_count}\n"

        summary += "\n### Detailed Breakdown:\n"
        for pattern, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            summary += f"- {pattern}: {count}\n"

        summary += "\n---\n\n### Detailed Issues:\n\n"

        result = summary + "\n".join(issues)
        return [TextContent(type="text", text=result)]

    elif name == "run_2to3":
        code = arguments.get("code", "")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            if HAS_FISSIX:
                # Use fissix (modern lib2to3 fork, Python 3.9+ compatible)
                from fissix import main as fissix_main
                import sys
                from io import StringIO

                # Capture output
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = StringIO()
                sys.stderr = StringIO()

                try:
                    # Run fissix refactoring
                    fissix_main.main("fissix.fixes", args=['-w', '-n', temp_path])
                    stdout_val = sys.stdout.getvalue()
                    stderr_val = sys.stderr.getvalue()
                except SystemExit:
                    stdout_val = sys.stdout.getvalue()
                    stderr_val = sys.stderr.getvalue()
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                # Read converted file
                with open(temp_path, 'r') as f:
                    converted = f.read()

                output = f"=== fissix Output (Python 3.9+ compatible) ===\n{stdout_val}\n{stderr_val}\n\n"
                output += f"=== Converted Code ===\n{converted}"
            else:
                # Fall back to system 2to3
                result = subprocess.run(
                    ['2to3', '-w', '-n', temp_path],
                    capture_output=True,
                    text=True
                )

                with open(temp_path, 'r') as f:
                    converted = f.read()

                output = f"=== 2to3 Output ===\n{result.stdout}\n{result.stderr}\n\n"
                output += f"=== Converted Code ===\n{converted}"

            return [TextContent(type="text", text=output)]
        except FileNotFoundError:
            return [TextContent(type="text", text="Error: Neither fissix nor 2to3 found. Install fissix: pip install fissix")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error during conversion: {str(e)}")]
        finally:
            os.unlink(temp_path)

    elif name == "convert_print_statements":
        code = arguments.get("code", "")

        # Simple print statement conversion
        # Handles: print "text" → print("text")
        #          print x, y → print(x, y)

        lines = code.split('\n')
        converted = []

        for line in lines:
            # Match print statement (not already a function call)
            match = re.match(r'^(\s*)print\s+(?!\()(.*?)(\s*#.*)?$', line)
            if match:
                indent = match.group(1)
                content = match.group(2).rstrip()
                comment = match.group(3) or ''

                # Handle trailing comma (no newline)
                if content.endswith(','):
                    content = content[:-1]
                    converted.append(f"{indent}print({content}, end=' '){comment}")
                else:
                    converted.append(f"{indent}print({content}){comment}")
            else:
                converted.append(line)

        result = '\n'.join(converted)
        return [TextContent(type="text", text=result)]

    elif name == "check_syntax":
        code = arguments.get("code", "")

        try:
            ast.parse(code)
            return [TextContent(type="text", text="✓ Valid Python 3 syntax")]
        except SyntaxError as e:
            return [TextContent(type="text", text=f"✗ Syntax error at line {e.lineno}: {e.msg}\n  {e.text}")]

    elif name == "get_migration_guide":
        issue = arguments.get("issue", "").lower()

        guides = {
            "print": """## Print Statement → Print Function

Python 2:
```python
print "Hello"
print x, y
print >>sys.stderr, "error"
```

Python 3:
```python
print("Hello")
print(x, y)
print("error", file=sys.stderr)
```

For compatibility, add at top of file:
```python
from __future__ import print_function
```""",

            "unicode": """## Unicode Changes

Python 2:
```python
u"unicode string"
"byte string"
unicode(x)
```

Python 3:
```python
"unicode string"  # All strings are unicode
b"byte string"    # Explicit bytes
str(x)            # unicode → str
```

For compatibility:
```python
from __future__ import unicode_literals
```""",

            "dict_methods": """## Dictionary Methods

Python 2:
```python
d.iteritems()
d.iterkeys()
d.itervalues()
d.has_key(k)
```

Python 3:
```python
d.items()      # Returns view, not list
d.keys()       # Returns view
d.values()     # Returns view
k in d         # Use 'in' operator
```

If you need a list:
```python
list(d.items())
```""",

            "exceptions": """## Exception Handling

Python 2:
```python
except Exception, e:
    pass

raise ValueError, "message"
```

Python 3:
```python
except Exception as e:
    pass

raise ValueError("message")
```""",

            "division": """## Division

Python 2:
```python
5 / 2  # = 2 (integer division)
```

Python 3:
```python
5 / 2   # = 2.5 (true division)
5 // 2  # = 2 (integer division)
```

For compatibility:
```python
from __future__ import division
```""",

            "imports": """## Changed Imports

Python 2 → Python 3:
- `ConfigParser` → `configparser`
- `Queue` → `queue`
- `cPickle` → `pickle`
- `urllib2` → `urllib.request`
- `urlparse` → `urllib.parse`
- `StringIO` → `io.StringIO`
- `cStringIO` → `io.StringIO`

Use `six` or `future` libraries for compatibility.
"""
        }

        if issue in guides:
            return [TextContent(type="text", text=guides[issue])]
        else:
            available = ", ".join(guides.keys())
            return [TextContent(type="text", text=f"Unknown issue type. Available guides: {available}")]

    elif name == "analyze_directory":
        path = arguments.get("path", "")
        exclude = arguments.get("exclude", ["venv", "__pycache__", ".git", "node_modules", ".tox", "build", "dist", "*.egg-info"])

        if not os.path.isdir(path):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidDirectory",
                    "message": f"'{path}' is not a valid directory",
                    "path": path,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        results = []
        total_issues = 0
        files_with_issues = 0
        files_scanned = 0
        skipped_files = []

        for root, dirs, files in os.walk(path):
            # Filter excluded directories
            dirs[:] = [d for d in dirs if not any(
                d == ex or d.endswith(ex.lstrip('*')) for ex in exclude
            )]

            for file in files:
                if not file.endswith('.py'):
                    continue

                # FR-0.3: Check file count limit
                if files_scanned >= LIMITS["max_files_per_operation"]:
                    skipped_files.append(os.path.join(root, file))
                    continue

                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, path)

                # FR-0.3: Check file size limit
                size_error = check_file_size(filepath, name)
                if size_error:
                    results.append((rel_path, "Skipped: file too large"))
                    continue

                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()

                    # Count issues in this file
                    file_issues = 0
                    lines = code.split('\n')

                    for i, line in enumerate(lines, 1):
                        if i <= 2 and (line.startswith('#!') or 'coding' in line):
                            continue
                        for pattern in PY2_PATTERNS.values():
                            if re.search(pattern, line):
                                file_issues += 1

                    if file_issues > 0:
                        results.append((rel_path, file_issues))
                        total_issues += file_issues
                        files_with_issues += 1

                    files_scanned += 1

                except Exception as e:
                    results.append((rel_path, f"Error: {str(e)}"))

        # Sort by issue count descending
        results.sort(key=lambda x: x[1] if isinstance(x[1], int) else 0, reverse=True)

        # Build response data
        file_results = []
        for filepath, count in results:
            if isinstance(count, int):
                file_results.append({"file": filepath, "issues": count})
            else:
                file_results.append({"file": filepath, "status": count})

        response_data = {
            "path": path,
            "files_scanned": files_scanned,
            "files_with_issues": files_with_issues,
            "total_issues": total_issues,
            "files": file_results,
        }

        if skipped_files:
            response_data["skipped_count"] = len(skipped_files)
            response_data["skipped_reason"] = f"Exceeded max_files_per_operation limit ({LIMITS['max_files_per_operation']})"

        response = create_response(
            tool_name=name,
            status="success",
            data=response_data,
            metadata={
                "limits": LIMITS,
                "fissix_available": HAS_FISSIX,
            }
        )

        return [TextContent(type="text", text=response)]

    elif name == "convert_file":
        file_path = arguments.get("file_path", "")
        backup = arguments.get("backup", True)
        dry_run = arguments.get("dry_run", False)

        if not os.path.isfile(file_path):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidFile",
                    "message": f"'{file_path}' is not a valid file",
                    "path": file_path,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        if not file_path.endswith('.py'):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidFileType",
                    "message": f"'{file_path}' is not a Python file",
                    "path": file_path,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # FR-0.3: Check file size limit
        size_error = check_file_size(file_path, name)
        if size_error:
            return [TextContent(type="text", text=size_error)]

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_code = f.read()

            if not HAS_FISSIX:
                error_resp = create_response(
                    tool_name=name,
                    status="error",
                    error={
                        "type": "MissingDependency",
                        "message": "fissix is required for file conversion. Install with: pip install fissix",
                    }
                )
                return [TextContent(type="text", text=error_resp)]

            # Use fissix to convert
            fixers = get_fissix_fixers()
            rt = refactor.RefactoringTool(fixers, options={'print_function': False})
            tree = rt.refactor_string(original_code + '\n', file_path)
            converted_code = str(tree).rstrip('\n')

            if converted_code == original_code:
                response = create_response(
                    tool_name=name,
                    status="success",
                    data={
                        "file": file_path,
                        "action": "no_changes_needed",
                        "message": "File is already Python 3 compatible",
                    }
                )
                return [TextContent(type="text", text=response)]

            if dry_run:
                # Show diff
                import difflib
                diff = difflib.unified_diff(
                    original_code.splitlines(keepends=True),
                    converted_code.splitlines(keepends=True),
                    fromfile=f"{file_path} (original)",
                    tofile=f"{file_path} (converted)"
                )
                diff_text = ''.join(diff)

                orig_lines = original_code.split('\n')
                conv_lines = converted_code.split('\n')
                changed = sum(1 for o, c in zip(orig_lines, conv_lines) if o != c)

                response = create_response(
                    tool_name=name,
                    status="success",
                    data={
                        "file": file_path,
                        "action": "dry_run",
                        "lines_changed": changed,
                        "diff": diff_text,
                    }
                )
                return [TextContent(type="text", text=response)]

            # Create backup if requested
            backup_path = None
            if backup:
                backup_path = file_path + '.py2.bak'
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original_code)

            # Write converted file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(converted_code)

            # Count changes
            orig_lines = original_code.split('\n')
            conv_lines = converted_code.split('\n')
            changed = sum(1 for o, c in zip(orig_lines, conv_lines) if o != c)

            response = create_response(
                tool_name=name,
                status="success",
                data={
                    "file": file_path,
                    "action": "converted",
                    "lines_changed": changed,
                    "backup_file": backup_path,
                }
            )
            return [TextContent(type="text", text=response)]

        except Exception as e:
            return [TextContent(type="text", text=error_response(name, e, f"converting file: {file_path}"))]

    elif name == "migration_report":
        path = arguments.get("path", "")
        exclude = arguments.get("exclude", ["venv", "__pycache__", ".git", "node_modules", ".tox", "build", "dist", "*.egg-info"])

        if not os.path.isdir(path):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidDirectory",
                    "message": f"'{path}' is not a valid directory",
                    "path": path,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        file_data = []
        total_issues = 0
        category_totals = {}
        files_scanned = 0
        skipped_files = []

        categories = {
            "Print/IO": ["print_statement", "raw_input", "execfile"],
            "String/Unicode": ["unicode_literal", "unicode_type", "basestring", "backticks", "old_repr"],
            "Numbers": ["long_suffix", "old_octal"],
            "Builtins": ["xrange", "reduce", "apply", "cmp_func", "coerce", "intern", "file_builtin", "buffer_builtin"],
            "Dict methods": ["iteritems", "iterkeys", "itervalues", "has_key", "viewitems", "viewkeys", "viewvalues"],
            "Syntax": ["old_ne", "except_comma", "old_raise"],
            "Imports": ["configparser", "queue_module", "urllib2", "urlparse", "stringio", "cstringio", "cpickle", "tkinter", "http_cookiejar", "thread_module", "commands_module", "htmlparser", "httplib"],
        }

        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not any(
                d == ex or d.endswith(ex.lstrip('*')) for ex in exclude
            )]

            for file in files:
                if not file.endswith('.py'):
                    continue

                # FR-0.3: Check file count limit
                if files_scanned >= LIMITS["max_files_per_operation"]:
                    skipped_files.append(os.path.join(root, file))
                    continue

                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, path)

                # FR-0.3: Check file size limit
                try:
                    if os.path.getsize(filepath) > LIMITS["max_file_size_bytes"]:
                        continue  # Skip large files silently in report
                except OSError:
                    continue

                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()

                    file_issues = {}
                    lines = code.split('\n')

                    for i, line in enumerate(lines, 1):
                        if i <= 2 and (line.startswith('#!') or 'coding' in line):
                            continue
                        for pattern_name, pattern in PY2_PATTERNS.items():
                            if re.search(pattern, line):
                                file_issues[pattern_name] = file_issues.get(pattern_name, 0) + 1

                    if file_issues:
                        issue_count = sum(file_issues.values())
                        file_data.append({
                            'path': rel_path,
                            'issues': file_issues,
                            'total': issue_count,
                            'lines': len(lines)
                        })
                        total_issues += issue_count

                        for pattern, count in file_issues.items():
                            for cat, patterns in categories.items():
                                if pattern in patterns:
                                    category_totals[cat] = category_totals.get(cat, 0) + count
                                    break

                    files_scanned += 1

                except Exception:
                    pass

        # Sort by total issues descending
        file_data.sort(key=lambda x: x['total'], reverse=True)

        # Calculate effort estimate (rough: ~2 min per issue for review + fix)
        hours = (total_issues * 2) / 60
        if hours < 1:
            effort = f"{int(hours * 60)} minutes"
        elif hours < 8:
            effort = f"{hours:.1f} hours"
        else:
            effort = f"{hours/8:.1f} days"

        # Build priority lists
        quick_wins = [{"file": f['path'], "issues": f['total']} for f in file_data if f['total'] < 5][:5]
        high_density = sorted(
            [f for f in file_data if f['total'] >= 5],
            key=lambda x: x['total']/x['lines'] if x['lines'] > 0 else 0,
            reverse=True
        )
        high_density_list = [{"file": f['path'], "issues": f['total'], "density": round(f['total']/f['lines']*100, 1) if f['lines'] > 0 else 0} for f in high_density[:5]]
        major_refactors = [{"file": f['path'], "issues": f['total']} for f in file_data[:5]]

        # Build priority files list
        priority_files = []
        for fd in file_data[:20]:
            density = fd['total'] / fd['lines'] * 100 if fd['lines'] > 0 else 0
            priority_files.append({
                "file": fd['path'],
                "issues": fd['total'],
                "lines": fd['lines'],
                "density": round(density, 1),
            })

        response_data = {
            "path": path,
            "summary": {
                "files_requiring_changes": len(file_data),
                "files_scanned": files_scanned,
                "total_issues": total_issues,
                "estimated_effort": effort,
            },
            "issues_by_category": category_totals,
            "priority_files": priority_files,
            "recommended_order": {
                "quick_wins": quick_wins,
                "high_density": high_density_list,
                "major_refactors": major_refactors,
            },
        }

        if skipped_files:
            response_data["skipped_count"] = len(skipped_files)
            response_data["skipped_reason"] = f"Exceeded max_files_per_operation limit ({LIMITS['max_files_per_operation']})"

        if len(file_data) > 20:
            response_data["additional_files"] = len(file_data) - 20

        response = create_response(
            tool_name=name,
            status="success",
            data=response_data,
            metadata={
                "limits": LIMITS,
                "fissix_available": HAS_FISSIX,
            }
        )

        return [TextContent(type="text", text=response)]

    elif name == "validate_conversion":
        file_path = arguments.get("file_path", "")

        if not os.path.isfile(file_path):
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "InvalidFile",
                    "message": f"'{file_path}' is not a valid file",
                    "path": file_path,
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # FR-0.3: Check file size limit
        size_error = check_file_size(file_path, name)
        if size_error:
            return [TextContent(type="text", text=size_error)]

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()

            # 1. Syntax check
            syntax_valid = True
            syntax_error = None
            try:
                ast.parse(code)
            except SyntaxError as e:
                syntax_valid = False
                syntax_error = {
                    "line": e.lineno,
                    "message": e.msg,
                    "text": e.text.strip() if e.text else ""
                }

            # 2. Check for remaining Python 2 patterns
            remaining_patterns = []
            lines = code.split('\n')
            for i, line in enumerate(lines, 1):
                if i <= 2 and (line.startswith('#!') or 'coding' in line):
                    continue
                for pattern_name, pattern in PY2_PATTERNS.items():
                    if re.search(pattern, line):
                        remaining_patterns.append({
                            "line": i,
                            "pattern": pattern_name,
                            "text": line.strip()
                        })

            # 3. Identify runtime-only issues needing human review
            needs_human_review = []

            # Patterns that require human judgment
            runtime_patterns = {
                r'\bexec\s*\(': {
                    "issue": "exec() usage",
                    "reason": "Dynamic code execution may have different behavior in Python 3",
                    "severity": "high"
                },
                r'\beval\s*\(': {
                    "issue": "eval() usage",
                    "reason": "Dynamic evaluation may behave differently with string/bytes",
                    "severity": "medium"
                },
                r'(?<![/\d])/(?![/\d*])': {
                    "issue": "Division operator",
                    "reason": "Division returns float in Python 3 (was int in Python 2)",
                    "severity": "high"
                },
                r'\bopen\s*\([^)]+\)': {
                    "issue": "File operations",
                    "reason": "Default encoding changed; may need explicit encoding parameter",
                    "severity": "medium"
                },
                r'\.encode\s*\(|\.decode\s*\(': {
                    "issue": "String encoding/decoding",
                    "reason": "str/bytes handling changed significantly",
                    "severity": "medium"
                },
                r'\bpickle\b': {
                    "issue": "Pickle usage",
                    "reason": "Pickle protocol differences between Python 2/3",
                    "severity": "medium"
                },
                r'\bsocket\b': {
                    "issue": "Socket operations",
                    "reason": "Socket data is bytes in Python 3",
                    "severity": "medium"
                },
                r'\bsubprocess\b': {
                    "issue": "Subprocess calls",
                    "reason": "Output is bytes by default in Python 3",
                    "severity": "low"
                },
                r'sys\.std(in|out|err)': {
                    "issue": "Standard streams",
                    "reason": "Standard streams handle text differently in Python 3",
                    "severity": "low"
                },
                r'__metaclass__': {
                    "issue": "Old metaclass syntax",
                    "reason": "Use class Foo(metaclass=Meta) in Python 3",
                    "severity": "high"
                },
                r'\.sort\s*\([^)]*cmp\s*=': {
                    "issue": "sort() with cmp parameter",
                    "reason": "cmp parameter removed; use key with functools.cmp_to_key",
                    "severity": "high"
                },
            }

            for i, line in enumerate(lines, 1):
                for pattern, info in runtime_patterns.items():
                    if re.search(pattern, line):
                        needs_human_review.append({
                            "line": i,
                            "issue": info["issue"],
                            "reason": info["reason"],
                            "severity": info["severity"],
                            "text": line.strip()
                        })

            # 4. Determine overall status
            if not syntax_valid:
                status = "failed"
            elif remaining_patterns:
                status = "incomplete"
            elif needs_human_review:
                status = "needs_review"
            else:
                status = "success"

            # 5. Generate test recommendations
            test_recommendations = []

            if any(r["issue"] == "Division operator" for r in needs_human_review):
                test_recommendations.append("Test all arithmetic operations for integer vs float division")

            if any(r["issue"] in ["File operations", "String encoding/decoding"] for r in needs_human_review):
                test_recommendations.append("Test file I/O with various encodings (UTF-8, Latin-1, etc.)")

            if any(r["issue"] == "Pickle usage" for r in needs_human_review):
                test_recommendations.append("Test pickle load/dump with data from Python 2")

            if any(r["issue"] in ["Socket operations", "Subprocess calls"] for r in needs_human_review):
                test_recommendations.append("Test network/subprocess operations for bytes vs str handling")

            if not test_recommendations:
                test_recommendations.append("Run existing test suite to verify behavior")

            response = create_response(
                tool_name=name,
                status="success",
                data={
                    "file": file_path,
                    "validation_status": status,
                    "syntax_valid": syntax_valid,
                    "syntax_error": syntax_error,
                    "remaining_py2_patterns": remaining_patterns,
                    "needs_human_review": needs_human_review,
                    "review_count": {
                        "high_severity": len([r for r in needs_human_review if r["severity"] == "high"]),
                        "medium_severity": len([r for r in needs_human_review if r["severity"] == "medium"]),
                        "low_severity": len([r for r in needs_human_review if r["severity"] == "low"]),
                    },
                    "test_recommendations": test_recommendations,
                },
                metadata={"limits": LIMITS}
            )
            return [TextContent(type="text", text=response)]

        except Exception as e:
            return [TextContent(type="text", text=error_response(name, e, f"validating file: {file_path}"))]

    elif name == "conversion_report":
        original_path = arguments.get("original_path", "")
        converted_path = arguments.get("converted_path", "")

        # Validate files exist
        for path, label in [(original_path, "original"), (converted_path, "converted")]:
            if not os.path.isfile(path):
                error_resp = create_response(
                    tool_name=name,
                    status="error",
                    error={
                        "type": "InvalidFile",
                        "message": f"'{path}' ({label}) is not a valid file",
                        "path": path,
                    }
                )
                return [TextContent(type="text", text=error_resp)]

        try:
            with open(original_path, 'r', encoding='utf-8', errors='replace') as f:
                original_code = f.read()
            with open(converted_path, 'r', encoding='utf-8', errors='replace') as f:
                converted_code = f.read()

            orig_lines = original_code.split('\n')
            conv_lines = converted_code.split('\n')

            # 1. Count original issues
            original_issues = {}
            for i, line in enumerate(orig_lines, 1):
                if i <= 2 and (line.startswith('#!') or 'coding' in line):
                    continue
                for pattern_name, pattern in PY2_PATTERNS.items():
                    if re.search(pattern, line):
                        original_issues[pattern_name] = original_issues.get(pattern_name, 0) + 1

            # 2. Count remaining issues in converted
            remaining_issues = {}
            for i, line in enumerate(conv_lines, 1):
                if i <= 2 and (line.startswith('#!') or 'coding' in line):
                    continue
                for pattern_name, pattern in PY2_PATTERNS.items():
                    if re.search(pattern, line):
                        remaining_issues[pattern_name] = remaining_issues.get(pattern_name, 0) + 1

            # 3. Calculate what was fixed
            fixed_issues = {}
            for pattern, count in original_issues.items():
                remaining = remaining_issues.get(pattern, 0)
                if count > remaining:
                    fixed_issues[pattern] = count - remaining

            # 4. Generate diff summary
            import difflib
            differ = difflib.unified_diff(
                orig_lines,
                conv_lines,
                fromfile=original_path,
                tofile=converted_path,
                lineterm=''
            )
            diff_lines = list(differ)

            additions = len([line for line in diff_lines if line.startswith('+') and not line.startswith('+++')])
            deletions = len([line for line in diff_lines if line.startswith('-') and not line.startswith('---')])

            # 5. Check syntax of converted file
            syntax_valid = True
            try:
                ast.parse(converted_code)
            except SyntaxError:
                syntax_valid = False

            # 6. Determine status
            total_original = sum(original_issues.values())
            total_remaining = sum(remaining_issues.values())
            total_fixed = sum(fixed_issues.values())

            if total_remaining == 0 and syntax_valid:
                status = "converted"
                if total_fixed == 0:
                    status = "no_changes_needed"
            elif total_remaining > 0:
                status = "needs_review"
            elif not syntax_valid:
                status = "failed"
            else:
                status = "converted"

            # 7. Identify what still needs attention
            needs_attention = []
            for pattern, count in remaining_issues.items():
                needs_attention.append({
                    "pattern": pattern,
                    "count": count,
                    "action": "Manual conversion required"
                })

            response = create_response(
                tool_name=name,
                status="success",
                data={
                    "original_file": original_path,
                    "converted_file": converted_path,
                    "conversion_status": status,
                    "syntax_valid": syntax_valid,
                    "summary": {
                        "original_issues": total_original,
                        "issues_fixed": total_fixed,
                        "issues_remaining": total_remaining,
                        "fix_rate": f"{(total_fixed/total_original*100):.1f}%" if total_original > 0 else "N/A",
                        "lines_added": additions,
                        "lines_removed": deletions,
                    },
                    "fixed_patterns": fixed_issues,
                    "remaining_patterns": remaining_issues,
                    "needs_attention": needs_attention,
                    "next_steps": [
                        "Run validate_conversion for detailed review items" if remaining_issues else "Run test suite to verify behavior",
                        "Check division operations for int vs float" if total_fixed > 0 else None,
                        "Review file I/O for encoding issues" if any('file' in p or 'io' in p.lower() for p in fixed_issues) else None,
                    ]
                },
                metadata={"limits": LIMITS}
            )

            # Clean up None values from next_steps
            response_dict = json.loads(response)
            response_dict["data"]["next_steps"] = [s for s in response_dict["data"]["next_steps"] if s]
            response = json.dumps(response_dict, indent=2)

            return [TextContent(type="text", text=response)]

        except Exception as e:
            return [TextContent(type="text", text=error_response(name, e, "generating conversion report"))]

    elif name == "scan_compat":
        files = arguments.get("files", [])

        if not files:
            error_resp = create_response(
                tool_name=name,
                status="error",
                error={
                    "type": "NoFilesProvided",
                    "message": "No files provided for scanning",
                }
            )
            return [TextContent(type="text", text=error_resp)]

        # FR-4.2: Issue classification with severity and categories
        COMPAT_PATTERNS = {
            # Deprecated functions (iterators)
            "xrange": {
                "pattern": r'\bxrange\s*\(',
                "code": "PY2-ITER-001",
                "message": "xrange() is not available in Python 3",
                "suggested_fix": "Use range() instead",
                "severity": "error",
                "category": "iterators"
            },
            "iteritems": {
                "pattern": r'\.iteritems\s*\(',
                "code": "PY2-ITER-002",
                "message": "dict.iteritems() is not available in Python 3",
                "suggested_fix": "Use dict.items() instead",
                "severity": "error",
                "category": "iterators"
            },
            "itervalues": {
                "pattern": r'\.itervalues\s*\(',
                "code": "PY2-ITER-003",
                "message": "dict.itervalues() is not available in Python 3",
                "suggested_fix": "Use dict.values() instead",
                "severity": "error",
                "category": "iterators"
            },
            "iterkeys": {
                "pattern": r'\.iterkeys\s*\(',
                "code": "PY2-ITER-004",
                "message": "dict.iterkeys() is not available in Python 3",
                "suggested_fix": "Use dict.keys() instead",
                "severity": "error",
                "category": "iterators"
            },
            "has_key": {
                "pattern": r'\.has_key\s*\(',
                "code": "PY2-ITER-005",
                "message": "dict.has_key() is not available in Python 3",
                "suggested_fix": "Use 'key in dict' instead",
                "severity": "error",
                "category": "iterators"
            },

            # Obsolete type names (text-types)
            "unicode_type": {
                "pattern": r'\bunicode\s*\(',
                "code": "PY2-TYPE-001",
                "message": "unicode() is not available in Python 3",
                "suggested_fix": "Use str() instead",
                "severity": "error",
                "category": "text-types"
            },
            "long_type": {
                "pattern": r'(?:\d+|0[xX][0-9a-fA-F]+)[lL]\b',
                "code": "PY2-TYPE-002",
                "message": "Long integer suffix L is not valid in Python 3",
                "suggested_fix": "Remove the L suffix",
                "severity": "error",
                "category": "text-types"
            },
            "basestring": {
                "pattern": r'\bbasestring\b',
                "code": "PY2-TYPE-003",
                "message": "basestring is not available in Python 3",
                "suggested_fix": "Use str instead",
                "severity": "error",
                "category": "text-types"
            },
            "unicode_literal": {
                "pattern": r'\bu["\']',
                "code": "PY2-TYPE-004",
                "message": "Unicode literal prefix u'' is unnecessary in Python 3",
                "suggested_fix": "Remove the u prefix (all strings are unicode in Python 3)",
                "severity": "info",
                "category": "text-types"
            },

            # Legacy operators
            "old_ne": {
                "pattern": r'<>',
                "code": "PY2-OP-001",
                "message": "<> comparison operator is not valid in Python 3",
                "suggested_fix": "Use != instead",
                "severity": "error",
                "category": "operators"
            },
            "backticks": {
                "pattern": r'`[^`]+`',
                "code": "PY2-OP-002",
                "message": "Backticks for repr are not valid in Python 3",
                "suggested_fix": "Use repr() instead",
                "severity": "error",
                "category": "operators"
            },

            # Outdated syntax
            "print_statement": {
                "pattern": r'^[^#]*\bprint\s+[^(=]',
                "code": "PY2-SYN-001",
                "message": "Print statement syntax is not valid in Python 3",
                "suggested_fix": "Use print() function instead",
                "severity": "error",
                "category": "syntax"
            },
            "except_comma": {
                "pattern": r'except\s+[\w.]+\s*,\s*\w+',
                "code": "PY2-SYN-002",
                "message": "Old except syntax with comma is not valid in Python 3",
                "suggested_fix": "Use 'except Exception as e:' instead",
                "severity": "error",
                "category": "syntax"
            },
            "old_raise": {
                "pattern": r'raise\s+[\w.]+\s*,',
                "code": "PY2-SYN-003",
                "message": "Old raise syntax is not valid in Python 3",
                "suggested_fix": "Use raise Exception('message') instead",
                "severity": "error",
                "category": "syntax"
            },
            "exec_statement": {
                "pattern": r'^[^#]*\bexec\s+[^(]',
                "code": "PY2-SYN-004",
                "message": "exec statement syntax is not valid in Python 3",
                "suggested_fix": "Use exec() function instead",
                "severity": "error",
                "category": "syntax"
            },

            # Relocated stdlib modules
            "ConfigParser": {
                "pattern": r'(?<!\w)ConfigParser\b',
                "code": "PY2-LIB-001",
                "message": "ConfigParser module was renamed in Python 3",
                "suggested_fix": "Use 'import configparser' instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "StringIO": {
                "pattern": r'(?<!\w)StringIO\b(?!\.)',
                "code": "PY2-LIB-002",
                "message": "StringIO module was moved in Python 3",
                "suggested_fix": "Use 'from io import StringIO' instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "cStringIO": {
                "pattern": r'\bcStringIO\b',
                "code": "PY2-LIB-003",
                "message": "cStringIO is not available in Python 3",
                "suggested_fix": "Use 'from io import StringIO' instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "cPickle": {
                "pattern": r'\bcPickle\b',
                "code": "PY2-LIB-004",
                "message": "cPickle is not available in Python 3",
                "suggested_fix": "Use 'import pickle' instead (it's fast in Python 3)",
                "severity": "error",
                "category": "stdlib-move"
            },
            "Queue": {
                "pattern": r'(?<!\w)Queue\b',
                "code": "PY2-LIB-005",
                "message": "Queue module was renamed in Python 3",
                "suggested_fix": "Use 'import queue' instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "urllib2": {
                "pattern": r'\burllib2\b',
                "code": "PY2-LIB-006",
                "message": "urllib2 is not available in Python 3",
                "suggested_fix": "Use urllib.request and urllib.error instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "urlparse": {
                "pattern": r'\burlparse\b',
                "code": "PY2-LIB-007",
                "message": "urlparse module was moved in Python 3",
                "suggested_fix": "Use urllib.parse instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "httplib": {
                "pattern": r'\bhttplib\b',
                "code": "PY2-LIB-008",
                "message": "httplib was renamed in Python 3",
                "suggested_fix": "Use http.client instead",
                "severity": "error",
                "category": "stdlib-move"
            },
            "HTMLParser": {
                "pattern": r'\bHTMLParser\b',
                "code": "PY2-LIB-009",
                "message": "HTMLParser module was moved in Python 3",
                "suggested_fix": "Use html.parser instead",
                "severity": "error",
                "category": "stdlib-move"
            },

            # Other deprecated builtins
            "raw_input": {
                "pattern": r'\braw_input\s*\(',
                "code": "PY2-BUILTIN-001",
                "message": "raw_input() is not available in Python 3",
                "suggested_fix": "Use input() instead",
                "severity": "error",
                "category": "builtins"
            },
            "execfile": {
                "pattern": r'\bexecfile\s*\(',
                "code": "PY2-BUILTIN-002",
                "message": "execfile() is not available in Python 3",
                "suggested_fix": "Use exec(open(file).read()) instead",
                "severity": "error",
                "category": "builtins"
            },
            "reduce": {
                "pattern": r'(?<![\.\w])reduce\s*\(',
                "code": "PY2-BUILTIN-003",
                "message": "reduce() was moved to functools in Python 3",
                "suggested_fix": "Use 'from functools import reduce'",
                "severity": "warning",
                "category": "builtins"
            },
            "apply": {
                "pattern": r'(?<!\w)apply\s*\(',
                "code": "PY2-BUILTIN-004",
                "message": "apply() is not available in Python 3",
                "suggested_fix": "Use func(*args, **kwargs) instead",
                "severity": "error",
                "category": "builtins"
            },
            "file_builtin": {
                "pattern": r'(?<!\w)file\s*\(',
                "code": "PY2-BUILTIN-005",
                "message": "file() builtin is not available in Python 3",
                "suggested_fix": "Use open() instead",
                "severity": "error",
                "category": "builtins"
            },
            "cmp_func": {
                "pattern": r'\bcmp\s*\(',
                "code": "PY2-BUILTIN-006",
                "message": "cmp() is not available in Python 3",
                "suggested_fix": "Use (a > b) - (a < b) or functools.cmp_to_key",
                "severity": "error",
                "category": "builtins"
            },
        }

        all_issues = []
        files_scanned = 0
        files_with_issues = 0
        category_counts = {}
        severity_counts = {"error": 0, "warning": 0, "info": 0}

        for filepath in files:
            if not os.path.isfile(filepath):
                all_issues.append({
                    "file": filepath,
                    "line": 0,
                    "code": "SCAN-ERR-001",
                    "message": f"File not found: {filepath}",
                    "severity": "error",
                    "category": "scan-error"
                })
                continue

            # Check file size
            try:
                if os.path.getsize(filepath) > LIMITS["max_file_size_bytes"]:
                    all_issues.append({
                        "file": filepath,
                        "line": 0,
                        "code": "SCAN-ERR-002",
                        "message": f"File exceeds size limit ({LIMITS['max_file_size_bytes']} bytes)",
                        "severity": "warning",
                        "category": "scan-error"
                    })
                    continue
            except OSError:
                continue

            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                files_scanned += 1
                file_has_issues = False

                for line_num, line in enumerate(lines, 1):
                    # Skip shebang and encoding lines
                    if line_num <= 2 and (line.startswith('#!') or 'coding' in line):
                        continue

                    for pattern_name, pattern_info in COMPAT_PATTERNS.items():
                        if re.search(pattern_info["pattern"], line):
                            file_has_issues = True
                            issue = {
                                "file": filepath,
                                "line": line_num,
                                "code": pattern_info["code"],
                                "message": pattern_info["message"],
                                "suggested_fix": pattern_info["suggested_fix"],
                                "severity": pattern_info["severity"],
                                "category": pattern_info["category"],
                                "source": line.strip()
                            }
                            all_issues.append(issue)

                            # Update counts
                            severity_counts[pattern_info["severity"]] += 1
                            cat = pattern_info["category"]
                            category_counts[cat] = category_counts.get(cat, 0) + 1

                if file_has_issues:
                    files_with_issues += 1

            except Exception as e:
                all_issues.append({
                    "file": filepath,
                    "line": 0,
                    "code": "SCAN-ERR-003",
                    "message": f"Error reading file: {str(e)}",
                    "severity": "error",
                    "category": "scan-error"
                })

        response = create_response(
            tool_name=name,
            status="success",
            data={
                "issues": all_issues,
                "summary": {
                    "total_issues": len(all_issues),
                    "files_scanned": files_scanned,
                    "files_with_issues": files_with_issues,
                    "by_severity": severity_counts,
                    "by_category": category_counts,
                },
            },
            metadata={"limits": LIMITS}
        )
        return [TextContent(type="text", text=response)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]

# Resources
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="guide://py2to3-quickref",
            name="Python 2 to 3 Quick Reference",
            description="Quick reference for common Python 2 to 3 migration patterns",
            mimeType="text/markdown"
        )
    ]

@server.read_resource()
async def read_resource(uri: str):
    if uri == "guide://py2to3-quickref":
        return """# Python 2 to 3 Quick Reference

## Most Common Changes

| Python 2 | Python 3 |
|----------|----------|
| `print "x"` | `print("x")` |
| `raw_input()` | `input()` |
| `xrange()` | `range()` |
| `d.iteritems()` | `d.items()` |
| `d.has_key(k)` | `k in d` |
| `unicode()` | `str()` |
| `except E, e:` | `except E as e:` |

## Future Imports for Compatibility

```python
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
from __future__ import absolute_import
```

## Tools
- `2to3`: Built-in conversion tool
- `futurize`: Forward-compatible code
- `modernize`: Similar to futurize
- `six`: Compatibility library
"""
    return "Resource not found"

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
