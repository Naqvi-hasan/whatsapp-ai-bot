import os
import psycopg2
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai
from dotenv import load_dotenv

# .env file se keys ko load karna
load_dotenv()

app = Flask(__name__)

# GitHub par yeh secure rahega kyunki key ab .env file se aa rahi hai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-2.5-flash')

# Supabase Database URL ko .env se nikalna
DB_URL = os.getenv("DATABASE_URL")

# --- DATABASE SETUP (Yeh automatic table bana dega) ---
def init_db():
    """Supabase me chat history save karne ke liye table banana"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_chat_history (
            id SERIAL PRIMARY KEY,
            whatsapp_number TEXT,
            role TEXT,
            message_text TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# Server start hote hi table check/create karein
init_db()

def get_chat_history(whatsapp_number, limit=10):
    """Database se us number ki purani chat nikalna"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT role, message_text FROM whatsapp_chat_history 
        WHERE whatsapp_number = %s 
        ORDER BY timestamp DESC LIMIT %s;
    """, (whatsapp_number, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    # Gemini ke format me convert karna (Purani chat pehle aayegi, isliye reversed)
    history = []
    for role, text in reversed(rows):
        history.append({"role": role, "parts": [text]})
    return history

def save_message(whatsapp_number, role, text):
    """Database me naya message ya reply save karna"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO whatsapp_chat_history (whatsapp_number, role, message_text) 
        VALUES (%s, %s, %s);
    """, (whatsapp_number, role, text))
    conn.commit()
    cur.close()
    conn.close()

# --- FLASK ROUTE ---
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip()
    sender_number = request.values.get('From', '')
    print(f"User ({sender_number}) ne bheja: {incoming_msg}") 
    
    # 1. User ka message database me save karein
    save_message(sender_number, "user", incoming_msg)

    # 2. Database se is user ki purani chat history fetch karein
    history = get_chat_history(sender_number, limit=10)

    try:
        # 3. Gemini ke sath history session start karein aur system prompt dein
        chat = model.start_chat(history=history)
        
        # Naya message bhej kar reply lein
        response = chat.send_message(
            f"Aap ek helpful marketing assistant hain. User ke is message ka short aur badiya jawab dein: {incoming_msg}"
        )
        reply_text = response.text
    except Exception as e:
        print(f"Error aaya: {e}")
        reply_text = "Sorry, thoda technical error hai, dobara try karein!"

    # 4. Bot ka reply database me save karein
    save_message(sender_number, "model", reply_text)

    # Twilio ko reply bhejna
    twilio_resp = MessagingResponse()
    twilio_resp.message(reply_text)
    
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(port=5000, debug=True)