import os

import speech_recognition as sr 
import sqlite3
import requests
import geocoder
from geopy.geocoders import Nominatim
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import threading
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def query_llama(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    return f"Error: {response.status_code}"


def get_location():
    try:
        ip_response = requests.get("https://api64.ipify.org?format=json")
        if ip_response.status_code == 200:
            user_ip = ip_response.json().get("ip")
            g = geocoder.ip(user_ip)
            if g.ok and g.latlng:
                geolocator = Nominatim(user_agent="womens_safety_bot")
                location = geolocator.reverse(g.latlng, exactly_one=True)
                if location:
                    address = location.address
                    lat, lon = g.latlng
                    map_link = f"https://maps.google.com/?q={lat},{lon}"
                    return address, user_ip, map_link
        return "Location not found", "IP not found", ""
    except Exception as e:
        return f"Error: {str(e)}", "IP Error", ""

def send_sms_alert(location, ip, map_url):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    emergency_numbers = get_contacts()
    for number in emergency_numbers:
        try:
            message_body = f"Emergency Alert! Location: {location}\nIP Address Info: {ip}\nMap: {map_url}"
            if len(message_body) > 1600:
                message_body = message_body[:1599]
            message = client.messages.create(
                body=message_body,
                from_=TWILIO_PHONE_NUMBER,
                to=number
            )
        except Exception as e:
            print(f"Error sending SMS to {number}: {e}")

def get_contacts():
    conn = sqlite3.connect("emergency_contacts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT number FROM contacts")
    contacts = [row[0] for row in cursor.fetchall()]
    conn.close()
    return contacts

def add_contact(number):
    conn = sqlite3.connect("emergency_contacts.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO contacts (number) VALUES (?)", (number,))
    conn.commit()
    conn.close()

def remove_contact(number):
    conn = sqlite3.connect("emergency_contacts.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM contacts WHERE number = ?", (number,))
    conn.commit()
    conn.close()

@app.route("/trigger_emergency", methods=["POST"])
def trigger_emergency():
    # Automatically trigger the emergency process
    location, ip, map_url = get_location()
    send_sms_alert(location, ip, map_url)
    
    # Return a response for confirmation
    return {"response": f"Emergency alert sent! Location: {location}\nMap: {map_url}"}


@app.route("/incoming_sms", methods=["POST"])
def incoming_sms():
    message_body = request.form['Body']
    from_number = request.form['From']
    print(f"Received message: {message_body} from {from_number}")
    response = MessagingResponse()
    response.message(f"Thank you for your message: {message_body}")
    return str(response)

@app.route("/ask", methods=["POST"])
def ask():
    user_message = request.form.get("message")
    if user_message.lower() == "yes":
        location, ip, map_url = get_location()
        send_sms_alert(location, ip, map_url)
        bot_response = f"Emergency request sent.\nLocation: {location}\nMap: {map_url}"
    elif user_message.lower() == "no":
        bot_response = "How can I assist you?"
    else:
        bot_response = query_llama(user_message)
    return {"response": bot_response}

@app.route("/contacts")
def view_contacts():
    contacts = get_contacts()
    return {"contacts": contacts}

@app.route("/add_contact", methods=["POST"])
def add():
    number = request.form.get("number")
    add_contact(number)
    return redirect(url_for('index'))

@app.route("/remove_contact", methods=["POST"])
def remove():
    number = request.form.get("number")
    remove_contact(number)
    return redirect(url_for('index'))

@app.route("/")
def index():
    return render_template("index.html")

# Function to handle voice recognition for "help"
def listen_for_help():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Listening for 'help'...")

        while True:
            try:
                audio = recognizer.listen(source)
                text = recognizer.recognize_google(audio).lower()
                print(f"Recognized: {text}")
                if "help" in text:
                    print("Detected 'help'!")
                    location, ip, map_url = get_location()
                    send_sms_alert(location, ip, map_url)
                    break  # Stop listening after detecting 'help'
            except sr.UnknownValueError:
                pass  # Ignore unknown speech
            except sr.RequestError:
                print("Could not request results from Google Speech Recognition service.")
                break

# Start voice recognition in a separate thread
def start_voice_thread():
    thread = threading.Thread(target=listen_for_help)
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    start_voice_thread()  # Start the voice recognition thread
    app.run(debug=True)
