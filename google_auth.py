import os
import pickle

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]
TOKEN_PATH = "token.pickle"
CREDENTIALS_PATH = "credentials.json"


def get_google_credentials():
    credentials = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as token_file:
            credentials = pickle.load(token_file)

    has_required_scopes = bool(
        credentials and credentials.has_scopes(SCOPES)
    )
    if credentials and credentials.valid and has_required_scopes:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token and has_required_scopes:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None

    if not credentials or not credentials.valid or not credentials.has_scopes(SCOPES):
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        credentials = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "wb") as token_file:
        pickle.dump(credentials, token_file)
    return credentials
