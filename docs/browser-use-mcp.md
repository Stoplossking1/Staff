# Browser Use MCP Setup

Documentation index: https://docs.cloud.browser-use.com/llms.txt

MCP server endpoint:

- `https://api.browser-use.com/mcp`

## API key

Set your Browser Use key in environment:

```bash
export BROWSER_USE_API_KEY="YOUR_API_KEY"
```

For local project use, copy `.env.example` to `.env` and fill `BROWSER_USE_API_KEY`.

## Claude Code

```bash
claude mcp add --transport http browser-use https://api.browser-use.com/mcp
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "browser-use": {
      "url": "https://api.browser-use.com/mcp",
      "headers": {
        "x-browser-use-api-key": "YOUR_API_KEY"
      }
    }
  }
}
```

## Cursor

Project config is committed at `.cursor/mcp.json`.

Equivalent config:

```json
{
  "mcpServers": {
    "browser-use": {
      "url": "https://api.browser-use.com/mcp",
      "headers": {
        "x-browser-use-api-key": "YOUR_API_KEY"
      }
    }
  }
}
```

## Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "browser-use": {
      "serverUrl": "https://api.browser-use.com/mcp",
      "headers": {
        "x-browser-use-api-key": "YOUR_API_KEY"
      }
    }
  }
}
```

## Available MCP tools

| Tool | Description | Cost |
| --- | --- | --- |
| `browser_task` | Run a full automation task | $0.01 init + per-step (default $0.006/step) |
| `execute_skill` | Run a skill | $0.02/call |
| `list_skills` | List available skills | Free |
| `get_cookies` | Extract cookies for auth | Free |
| `list_browser_profiles` | List profiles | Free |
| `monitor_task` | Check task progress | Free |
