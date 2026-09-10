from googleapiclient.discovery import build

from google_auth import get_google_credentials


def get_calendar_service():
    return build("calendar", "v3", credentials=get_google_credentials())


if __name__ == "__main__":
    service = get_calendar_service()
    service.events().list(calendarId="primary", maxResults=1, singleEvents=True).execute()
    print("Google Calendar API connection successful.")
