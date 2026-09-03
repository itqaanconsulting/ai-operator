# Local n8n

The AI Operator uses n8n as the integration layer for systems such as Trello.
n8n runs locally in Docker and is only exposed on `127.0.0.1:5678`.

## Start

Open PowerShell in the repository and run:

```powershell
.\scripts\start-n8n.ps1
```

The first run downloads the pinned n8n image and can take several minutes. Open
`http://127.0.0.1:5678` after the container has started and create the local n8n
owner account. This account exists only in the local persistent Docker volume.

The script creates `.env.n8n` with a random encryption key. This file is ignored
by Git. Keep it together with the Docker volume because n8n needs the same key to
decrypt stored credentials.

## Status and logs

```powershell
docker compose --env-file .env.n8n -f compose.n8n.yml ps
docker compose --env-file .env.n8n -f compose.n8n.yml logs --tail 100 n8n
```

## Stop

```powershell
.\scripts\stop-n8n.ps1
```

Stopping the container does not delete the `ai-operator-n8n-data` volume.
Never use `down --volumes` unless you intentionally want to erase the local n8n
account, workflows, execution history, and credentials.

## Import the Trello workflow

Import `n8n/ai-operator-to-trello.json` from the n8n workflow menu. The workflow
is inactive by default and cannot create a card until both credentials are set:

1. Create a Header Auth credential for the Webhook node. Use header name
   `X-AI-Operator-Secret` and the value stored in `.env.n8n` as
   `AI_OPERATOR_WEBHOOK_SECRET`.
2. Connect a Trello credential to the Trello node.
3. Select a real Trello board and list in the Trello node; never commit their IDs
   or credentials into the workflow template.
4. Publish the workflow so `POST /webhook/ai-operator-trello` remains available.

The FastAPI application reads the same secret from `.env.n8n` for local development.
For another n8n host, configure these values in the application's `.env` file:

```dotenv
N8N_TRELLO_WEBHOOK_URL=https://your-n8n-host/webhook/ai-operator-trello
N8N_TRELLO_WEBHOOK_SECRET=use-the-same-header-auth-secret
```

An approved business record can then be sent with
`POST /operational-records/{record_id}/send-to-trello`. The dispatch is persisted;
repeating a successful request returns the existing result instead of creating a
second card.

Display the generated webhook secret locally with:

```powershell
(Get-Content .env.n8n | Select-String '^AI_OPERATOR_WEBHOOK_SECRET=').Line.Split('=', 2)[1]
```

Do not paste this secret into chat, Git, screenshots, or documentation.
