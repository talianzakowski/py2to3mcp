# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a new MCP (Model Context Protocol) server project. The codebase is currently empty and needs to be initialized.

## Getting Started

To build an MCP server, you'll typically need to:
1. Initialize a Node.js/TypeScript project
2. Install the MCP SDK (`@modelcontextprotocol/sdk`)
3. Implement server handlers for tools, resources, or prompts

## MCP Server Architecture

MCP servers communicate via stdio and expose:
- **Tools**: Functions that can be called by LLM clients
- **Resources**: Data sources that can be read
- **Prompts**: Reusable prompt templates

Refer to the MCP documentation at https://modelcontextprotocol.io for implementation details.