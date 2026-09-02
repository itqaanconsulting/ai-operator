from googleapiclient.discovery import build

from google_auth import get_google_credentials


def get_gmail_service():
    return build("gmail", "v1", credentials=get_google_credentials())


if __name__ == "__main__":
    service = get_gmail_service()
    service.users().getProfile(userId="me").execute()
    print("Gmail API connection successful.")
