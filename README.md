# Agent Handoff Middleware

Serverless middleware for AI agent handoffs with built-in Stripe metered billing. Clean, enrich, and route messages between AI agents in one API call.

## Live API

```bash
https://agent-handoff-production-573c.up.railway.app
```bash

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| /handoff | POST | Process and route a message to the next agent |
| /health | GET | Service health check |
| /stats | GET | Usage statistics (requires API key) |
| /mcp | POST | Model Context Protocol server (`handoff` + `get_usage_stats` tools) — same auth/billing path as REST |

## Quick Start

```bash
curl -X POST https://agent-handoff-production-573c.up.railway.app/handoff -H 'x-api-key: your-key' -H 'Content-Type: application/json' -d '{"message": {"task": "Summarize this"}, "next_agent": "summarizer"}'
```bash

## PowerShell Module

```powershell
Install-Module AgentHandoff
$env:HANDOFF_API_KEY = 'your-key'
$result = Invoke-AgentHandoff -Message @{ task = 'Summarize this' } -NextAgent 'summarizer' -VerboseOutput
```powershell

## Pricing

- Pay-per-use: $0.001 per handoff via Stripe
- Pro tier: $29/month for unlimited handoffs

## Tech Stack

- FastAPI + Python
- Railway deployment
- Stripe metered billing
- Slowapi rate limiting

## Links

- [PowerShell Gallery](https://www.powershellgallery.com/packages/AgentHandoff)
- [Live API](https://agent-handoff-production-573c.up.railway.app/health)

## Recent changes (2026-07-27)

- **MCP server added** at `POST /mcp` — exposes `handoff` and `get_usage_stats` as MCP tools over JSON-RPC 2.0, discoverable via `tools/list`. Runs through the exact same auth → usage → billing path as the REST `/handoff` endpoint, so it can't become an unmetered bypass. `server.json` added for the official MCP registry (schema-validated); publishing via `mcp-publisher` is still pending.
- **Durable billing-failure audit trail** — failures now persist to Supabase (`public.billing_failures`) instead of only an ephemeral local file that reset on every redeploy.
