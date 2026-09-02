import base64
import json
from email.mime.text import MIMEText

from models import EmailRequest


class GmailOperator:
    def __init__(self, service):
        self.service = service

    def _label_id(self, label_name: str) -> str:
        response = self.service.users().labels().list(userId="me").execute()
        for label in response.get("labels", []):
            if label.get("name", "").casefold() == label_name.casefold():
                return label["id"]
        raise ValueError(f"Gmail label '{label_name}' does not exist")

    def list_labeled_emails(self, label_name: str, max_results: int):
        label_id = self._label_id(label_name)
        response = self.service.users().messages().list(
            userId="me", labelIds=[label_id], maxResults=max_results
        ).execute()
        emails = []
        for item in response.get("messages", []):
            message = self.service.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
            emails.append(self._to_email_request(message))
        return emails

    def _to_email_request(self, message: dict) -> EmailRequest:
        payload = message.get("payload", {})
        headers = {
            header.get("name", "").casefold(): header.get("value", "")
            for header in payload.get("headers", [])
        }
        body = self._extract_body(payload)
        if not body.strip():
            raise ValueError(f"Gmail message {message.get('id')} has no readable text body")
        return EmailRequest(
            subject=headers.get("subject") or "(no subject)",
            body=body,
            sender=headers.get("from") or None,
            gmail_msg_id=message.get("id"),
        )

    def _extract_body(self, part: dict) -> str:
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime_type == "text/plain" and data:
            return self._decode(data)
        for child in part.get("parts", []):
            text = self._extract_body(child)
            if text:
                return text
        if data and not part.get("parts"):
            return self._decode(data)
        return ""

    @staticmethod
    def _decode(data: str) -> str:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")

    def create_reply_draft(self, gmail_msg_id: str, reply_text: str):
        original = self.service.users().messages().get(
            userId="me", id=gmail_msg_id, format="metadata",
            metadataHeaders=["From", "Subject", "Message-ID"],
        ).execute()
        headers = {
            header.get("name", "").casefold(): header.get("value", "")
            for header in original.get("payload", {}).get("headers", [])
        }
        recipient = headers.get("from")
        if not recipient:
            raise ValueError("Original email has no From header")
        subject = headers.get("subject") or "(no subject)"
        if not subject.casefold().startswith("re:"):
            subject = f"Re: {subject}"
        draft = MIMEText(reply_text, "plain", "utf-8")
        draft["To"] = recipient
        draft["Subject"] = subject
        if headers.get("message-id"):
            draft["In-Reply-To"] = headers["message-id"]
            draft["References"] = headers["message-id"]
        raw = base64.urlsafe_b64encode(draft.as_bytes()).decode("ascii")
        created = self.service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw, "threadId": original.get("threadId")}},
        ).execute()
        return {"provider": "gmail", "draft_id": created.get("id")}


def action_reply_text(action: dict) -> str:
    payload = json.loads(action.get("payload_json") or "{}")
    reply = payload.get("suggested_reply")
    if not reply:
        raise ValueError("Approved action has no suggested reply")
    return reply
