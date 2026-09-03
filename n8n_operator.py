import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class N8nDispatchError(RuntimeError):
    pass


def dispatch_operational_record(webhook_url: str, webhook_secret: str, record: dict) -> dict:
    if not webhook_url or not webhook_secret:
        raise N8nDispatchError("The n8n Trello integration is not configured")

    payload = {
        "id": record["id"],
        "title": record["title"],
        "record_type": record["record_type"],
        "priority": record["priority"],
        "owner": record.get("owner"),
        "due_at": record.get("due_at"),
        "next_action": record["next_action"],
        "notes": record.get("notes"),
    }
    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-AI-Operator-Secret": webhook_secret,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise N8nDispatchError(f"n8n returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise N8nDispatchError(f"Could not reach n8n: {exc.reason if isinstance(exc, URLError) else exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise N8nDispatchError("n8n returned an invalid response") from exc

    if not isinstance(result, dict) or not result.get("id"):
        raise N8nDispatchError("n8n did not return the created Trello card")
    return result
