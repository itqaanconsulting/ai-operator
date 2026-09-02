from gmail_auth import get_gmail_service
import time

def mark_all_as_read():
    service = get_gmail_service()
    print("Starting: marking all unread emails as read...")
    
    total_marked = 0
    while True:
        # Fetch up to 500 unread emails per batch.
        results = service.users().messages().list(
            userId='me',
            q='is:unread',
            maxResults=500
        ).execute()
        
        messages = results.get('messages', [])
        if not messages:
            print(f"Done. Marked {total_marked} emails as read.")
            break
        
        msg_ids = [msg['id'] for msg in messages]
        
        # Mark every message in this batch as read.
        for msg_id in msg_ids:
            try:
                service.users().messages().modify(
                    userId='me',
                    id=msg_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                total_marked += 1
                print(f"{total_marked} - Marked as read: {msg_id}")
            except Exception as e:
                print(f"Failed for {msg_id}: {e}")
        
        print(f"Processed {len(msg_ids)} emails; continuing...")
        time.sleep(0.5)  # Brief pause to avoid rate limiting.

if __name__ == "__main__":
    mark_all_as_read()
