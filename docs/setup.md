# Local Setup: Browser Use + OpenAI + Laminar

This guide sets up local development for:
- replay stream (`f1-stream`, video-only)
- agent loop process (env-configured command)
- OpenAI + Laminar env wiring
- Browser Use MCP configuration notes

## Prerequisites
- Node.js `20.19+` or `22.12+`
- npm
- Python 3.11+ (or whichever runtime your `AGENT_LOOP_CMD` uses)
- `uvx` (only if using local Browser Use MCP command mode)

## First Run in <90s (smoke test)
Run these commands from repo root:

```bash
cp .env.example .env
echo "AGENT_LOOP_CMD='echo \"agent loop started\"'" >> .env
npm ci --prefix f1-stream
./scripts/run_local.sh
```

Expected result:
- stream starts on `http://127.0.0.1:5173`
- agent loop command runs and exits
- script shuts down cleanly
- no external API calls are made in this smoke test

## Full Setup

1. Copy env template:

```bash
cp .env.example .env
```

2. Edit `.env` and set required values:
- `OPENAI_API_KEY`
- `LMNR_PROJECT_API_KEY`
- `AGENT_LOOP_CMD`
- Browser Use MCP fields for either `local` or `remote` mode

3. Install stream dependencies:

```bash
npm ci --prefix f1-stream
```

4. Run sanity checks:

```bash
./scripts/checks.sh
```

5. Start local stack:

```bash
./scripts/run_local.sh
```

## Browser Use MCP Setup Note
Use one of two modes in `.env`:

- `BROWSER_USE_MCP_MODE=local`
  - `BROWSER_USE_MCP_COMMAND=uvx`
  - `BROWSER_USE_MCP_ARGS='browser-use[cli] --mcp'`
- `BROWSER_USE_MCP_MODE=remote`
  - set `BROWSER_USE_MCP_URL` to your MCP SSE endpoint

If your MCP client needs explicit server config, use this pattern:

```json
{
  "mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["browser-use[cli]", "--mcp"]
    }
  }
}
```

## OpenAI Key Setup Note
Set `OPENAI_API_KEY` in `.env`.

Your agent loop process should read it from env (do not hardcode keys).

## Laminar Env Wiring Note
Set in `.env`:
- `LMNR_PROJECT_API_KEY`
- `LMNR_BASE_URL` (default: `https://api.lmnr.ai`)
- `LMNR_ENV` (example: `local`)

Your agent loop should pass these env vars into Laminar initialization.

## Optional Overrides
- `STREAM_HOST` (default `127.0.0.1`)
- `STREAM_PORT` (default `5173`)
- `STREAM_URL` (default derived from host/port)
- `STREAM_CMD` (override full stream launch command)
