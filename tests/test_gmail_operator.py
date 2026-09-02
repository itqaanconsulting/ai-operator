import base64
import unittest

from gmail_operator import GmailOperator


class Executable:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class LabelsResource:
    def list(self, **kwargs):
        return Executable({"labels": [{"id": "label-1", "name": "AI-Operator"}]})


class MessagesResource:
    def __init__(self, message):
        self.message = message
        self.list_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return Executable({"messages": [{"id": "msg-1"}]})

    def get(self, **kwargs):
        return Executable(self.message)


class DraftsResource:
    def __init__(self):
        self.body = None

    def create(self, **kwargs):
        self.body = kwargs["body"]
        return Executable({"id": "draft-1"})


class UsersResource:
    def __init__(self, message):
        self.labels_resource = LabelsResource()
        self.messages_resource = MessagesResource(message)
        self.drafts_resource = DraftsResource()

    def labels(self):
        return self.labels_resource

    def messages(self):
        return self.messages_resource

    def drafts(self):
        return self.drafts_resource


class FakeService:
    def __init__(self, message):
        self.users_resource = UsersResource(message)

    def users(self):
        return self.users_resource


class GmailOperatorTest(unittest.TestCase):
    def setUp(self):
        body = base64.urlsafe_b64encode(b"Kun je vrijdag antwoorden?").decode()
        self.message = {
            "id": "msg-1",
            "threadId": "thread-1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Jan <jan@example.com>"},
                    {"name": "Subject", "value": "Project X"},
                    {"name": "Message-ID", "value": "<mail-1@example.com>"},
                ],
                "parts": [{"mimeType": "text/plain", "body": {"data": body}}],
            },
        }
        self.service = FakeService(self.message)
        self.operator = GmailOperator(self.service)

    def test_import_uses_label_and_does_not_modify_message(self):
        emails = self.operator.list_labeled_emails("AI-Operator", 5)

        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].gmail_msg_id, "msg-1")
        self.assertEqual(emails[0].body, "Kun je vrijdag antwoorden?")
        self.assertEqual(
            self.service.users_resource.messages_resource.list_kwargs["labelIds"],
            ["label-1"],
        )

    def test_create_reply_draft_keeps_thread_and_never_sends(self):
        result = self.operator.create_reply_draft("msg-1", "Hoi Jan, akkoord.")

        draft_body = self.service.users_resource.drafts_resource.body
        raw = base64.urlsafe_b64decode(draft_body["message"]["raw"])
        self.assertEqual(result["draft_id"], "draft-1")
        self.assertEqual(draft_body["message"]["threadId"], "thread-1")
        self.assertIn(b"Subject: Re: Project X", raw)
        self.assertIn(b"jan@example.com", raw)


if __name__ == "__main__":
    unittest.main()
