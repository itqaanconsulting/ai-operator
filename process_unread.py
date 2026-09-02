from gmail_auth import get_gmail_service
import base64
import json
import sqlite3
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- Legacy database setup ---
def init_db():
    conn = sqlite3.connect("emails.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            body TEXT,
            intent TEXT,
            order_number TEXT,
            api_response TEXT,
            gmail_msg_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_to_db(subject, body, intent, order_number, api_response, gmail_msg_id):
    conn = sqlite3.connect("emails.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO processed_emails 
        (subject, body, intent, order_number, api_response, gmail_msg_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject, body, intent, order_number, json.dumps(api_response), gmail_msg_id))
    conn.commit()
    conn.close()

# --- Legacy simulated APIs ---
def dummy_cancel(order_id: str):
    return {"action": "cancellation", "order_id": order_id, "status": "cancelled", "message": f"Order {order_id} was cancelled."}

def dummy_return(order_id: str, reason: str):
    return {"action": "return", "order_id": order_id, "reason": reason, "status": "return requested", "message": f"Return for order {order_id} was registered. Reason: {reason}"}

def dummy_status(order_id: str):
    return {"action": "status_check", "order_id": order_id, "status": "in transit", "expected_delivery": "2026-09-05", "message": f"Order {order_id} is in transit."}

def dummy_change_address(order_id: str, new_address: str):
    return {"action": "address_change", "order_id": order_id, "new_address": new_address, "status": "address updated", "message": f"The address for order {order_id} was changed to {new_address}."}

# --- Legacy AI processing ---
def process_email_content(subject: str, body: str, gmail_msg_id: str):
    full_text = f"Subject: {subject}\nBody: {body}"
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """
            You are an AI assistant that analyzes customer-service emails.
            Intents: 'cancel', 'return', 'status', and 'change_address'.
            Fields: order_number (required), reason (optional), and new_address (optional).
            Always return JSON containing these fields.
            """},
            {"role": "user", "content": full_text}
        ],
        response_format={"type": "json_object"}
    )
    
    ai_output = json.loads(response.choices[0].message.content)
    intent = ai_output.get("intent", "unknown")
    order_number = ai_output.get("order_number")
    
    if not order_number:
        raise ValueError("No order number found")
    
    if intent == "cancel":
        result = dummy_cancel(order_number)
    elif intent == "return":
        reason = ai_output.get("reason", "unknown reason")
        result = dummy_return(order_number, reason)
    elif intent == "status":
        result = dummy_status(order_number)
    elif intent == "change_address":
        new_address = ai_output.get("new_address", "unknown address")
        result = dummy_change_address(order_number, new_address)
    else:
        result = {"action": "unknown", "message": f"Intent '{intent}' is not supported."}
    
    save_to_db(subject, body, intent, order_number, result, gmail_msg_id)
    return {"intent": intent, "order_number": order_number, "action_result": result}

# --- Legacy script: process all unread emails ---
def process_unread():
    service = get_gmail_service()
    print("Fetching unread emails...")
    
    # Fetch up to 500 unread emails.
    results = service.users().messages().list(userId='me', q='is:unread', maxResults=500).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No unread emails found.")
        return
    
    print(f"Found {len(messages)} unread emails.")
    
    for msg in messages:
        msg_id = msg['id']
        print(f"Processing: {msg_id}")
        
        # Fetch the complete email.
        message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        subject = "(no subject)"
        body_text = ""
        payload = message.get('payload', {})
        headers = payload.get('headers', [])
        for header in headers:
            if header.get('name') == 'Subject':
                subject = header.get('value', '(no subject)')
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data')
                    if data:
                        body_text = base64.urlsafe_b64decode(data).decode('utf-8')
                        break
        else:
            data = payload.get('body', {}).get('data')
            if data:
                body_text = base64.urlsafe_b64decode(data).decode('utf-8')
        
        if not body_text:
            print("No text body; skipping and marking the message as read.")
            service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
            continue
        
        # Process with AI.
        try:
            result = process_email_content(subject, body_text, msg_id)
            print(f"Processed: {result['intent']} - order {result['order_number']}")
        except Exception as e:
            print(f"Processing failed: {e}")
        
        # Mark as read.
        try:
            service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
            print(f"Marked as read: {msg_id}")
        except Exception as e:
            print(f"Failed to mark as read: {e}")

if __name__ == "__main__":
    init_db()  # Ensure that the legacy database exists.
    process_unread()
