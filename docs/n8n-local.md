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
