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