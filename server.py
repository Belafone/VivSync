import os
import time
import json
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify, Response
from cryptography.fernet import Fernet
import logging
from logging.handlers import RotatingFileHandler
from ics import Calendar, Event

app = Flask(__name__)

# Konstanten und Konfiguration
DATA_DIR = "user_data"
ICAL_EXPIRY_DAYS = 30  # Standardwert für Gültigkeitsdauer

# Sicherstellen, dass das Datenverzeichnis existiert
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# Verschlüsselungsschlüssel einrichten
SECRET_KEY_FILE = "secret.key"
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "rb") as key_file:
        SECRET_KEY = key_file.read()
else:
    # Generiere einen neuen Schlüssel, falls keiner existiert
    SECRET_KEY = Fernet.generate_key()
    with open(SECRET_KEY_FILE, "wb") as key_file:
        key_file.write(SECRET_KEY)

fernet = Fernet(SECRET_KEY)

# Logging konfigurieren
def configure_logging():
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler(
        'logs/server.log', 
        maxBytes=10485760,  # 10 MB
        backupCount=10
    )
    
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    file_handler.setFormatter(formatter)
    
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    
    # Werkzeug-Logger konfigurieren (Flask's WSGI-Bibliothek)
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(file_handler)

configure_logging()

# Hilfsfunktionen
def encrypt_data(data):
    """String mit Fernet symmetrischer Verschlüsselung verschlüsseln"""
    return fernet.encrypt(data.encode())

def decrypt_data(data):
    """Mit Fernet verschlüsselte Daten entschlüsseln"""
    return fernet.decrypt(data).decode()

def generate_token():
    """Zufälligen Token für anonyme Benutzer generieren"""
    return os.urandom(8).hex()

def generate_user_token(username):
    """Deterministischen Token basierend auf Username generieren"""
    # Hashfunktion für deterministischen, aber nicht umkehrbaren Token
    hash_obj = hashlib.sha256(username.lower().encode())
    return hash_obj.hexdigest()[:16]  # Erste 16 Zeichen des Hex-Digests verwenden

@app.route('/api/sync', methods=['POST'])
def receive_data():
    """API-Endpunkt zum Empfangen und Speichern von Dienstdaten"""
    app.logger.info("Empfange Daten unter /api/sync")
    try:
        request_data = request.json
        
        # Dienste aus dem JSON extrahieren
        if isinstance(request_data, dict) and "dienste" in request_data:
            data = request_data["dienste"]
            # Vom Client gesendete Haltbarkeitsdauer verwenden oder Standard
            expiry_days = request_data.get("expiry_days", ICAL_EXPIRY_DAYS)
        else:
            # Für Abwärtskompatibilität
            data = request_data
            expiry_days = ICAL_EXPIRY_DAYS
        
        username = None
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            username = data[0].get('username')
            
        if not username:
            username = request.headers.get('X-Username')
            
        if not username:
            app.logger.warning("Kein Username in Daten oder Header gefunden, generiere zufälligen Token.")
            user_token = generate_token()
        else:
            user_token = generate_user_token(username)
            
        app.logger.info(f"Generiere Token für User: {username} -> {user_token}")
        
        # Speichere expiry_days mit in den Daten
        if isinstance(data, list):
            # Metadaten für spätere Verwendung
            encrypted_data = encrypt_data(json.dumps({
                "dienste": data,
                "expiry_days": expiry_days,
                "created_at": time.time()
            }))
        else:
            encrypted_data = encrypt_data(json.dumps(data))
            
        token_file = os.path.join(DATA_DIR, f"{user_token}.dat")
        
        app.logger.info(f"Speichere Daten in Datei: {token_file}")
        with open(token_file, "wb") as f:
            f.write(encrypted_data)
            
        ical_url = f"https://vivsync.com/calendar/{user_token}"
        
        app.logger.info(f"Daten erfolgreich gespeichert für Token: {user_token}")
        
        # Verwende die vom Client gesendete Haltbarkeitsdauer
        return jsonify({
            "status": "success",
            "ical_url": ical_url,
            "expires_in": f"{expiry_days} Tage"
        })
    except Exception as e:
        app.logger.error(f"Fehler in /api/sync: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Interner Serverfehler bei der Datenverarbeitung"}), 500

@app.route('/calendar/<token>')
def generate_ical(token):
    """iCal-Datei für den gegebenen Token generieren und zurückgeben"""
    app.logger.info(f"Anfrage für Kalender mit Token: {token}")
    try:
        token_file = os.path.join(DATA_DIR, f"{token}.dat")
        app.logger.info(f"Prüfe Existenz von Datei: {token_file}")
        
        if not os.path.exists(token_file):
            app.logger.warning(f"Token-Datei nicht gefunden: {token_file}")
            return "Token nicht gefunden oder Zugriff verweigert", 404

        app.logger.info(f"Lese Token-Datei: {token_file}")
        with open(token_file, "rb") as f:
            encrypted_data = f.read()
        
        app.logger.info(f"Entschlüssele Daten für Token: {token}")
        decrypted_data = decrypt_data(encrypted_data)
        
        app.logger.info(f"Parse JSON für Token: {token}")
        json_data = json.loads(decrypted_data)
        
        app.logger.info(f"Generiere iCal für Token: {token}")
        
        # Prüfe und extrahiere Dienste aus dem neuen Format
        if isinstance(json_data, dict) and "dienste" in json_data:
            dienste = json_data["dienste"]
            # Verwende die benutzerdefinierte Haltbarkeitsdauer oder Standard
            expiry_days = json_data.get("expiry_days", ICAL_EXPIRY_DAYS)
            created_at = json_data.get("created_at", os.path.getmtime(token_file))
        else:
            # Abwärtskompatibilität für altes Datenformat
            dienste = json_data
            expiry_days = ICAL_EXPIRY_DAYS
            created_at = os.path.getmtime(token_file)
        
        # Prüfe, ob der Link abgelaufen ist
        if (time.time() - created_at) > (expiry_days * 24 * 60 * 60):
            app.logger.warning(f"Token abgelaufen: {token} (Erstellt: {datetime.fromtimestamp(created_at)})")
            return "Dieser Link ist abgelaufen. Bitte synchronisieren Sie Ihren Dienstplan erneut.", 410
        
        # Stellen Sie sicher, dass dienste eine Liste ist
        if not isinstance(dienste, list):
            app.logger.error(f"Datenformatfehler: Dienste ist keine Liste für Token {token}, Typ: {type(dienste)}")
            return "Fehler bei der Datenverarbeitung: Ungültiges Dienstplanformat", 500
        
        # iCal-Kalender erstellen
        cal = Calendar()
        
        for dienst in dienste:
            event = Event()
            
            # Titel setzen
            title = dienst.get('dienst', '')
            position = dienst.get('position', '')
            if position:
                title = f"{title} - {position}"
            event.name = title
            
            # Beschreibung
            description = "Automatisch synchronisiert mit VivSync"
            dienstzeit = dienst.get('dienstzeit', '')
            if dienstzeit:
                description += f"\nDienstzeit: {dienstzeit}"
            event.description = description
            
            # Datum/Zeit setzen
            try:
                event_date = datetime.strptime(dienst.get('datum', ''), "%Y-%m-%d")
                event.begin = event_date
                
                # Wenn Dienstzeit vorhanden, Start- und Endzeit setzen
                if dienstzeit:
                    try:
                        start_time, end_time = dienstzeit.split(' - ')
                        start_hour, start_minute = map(int, start_time.split(':'))
                        end_hour, end_minute = map(int, end_time.split(':'))
                        
                        event.begin = event.begin.replace(hour=start_hour, minute=start_minute)
                        event.end = event.begin.replace(hour=end_hour, minute=end_minute)
                        
                        # Falls Endzeit vor Startzeit (z.B. bei Nachtdienst)
                        if event.end < event.begin:
                            event.end = event.end.replace(day=event.end.day + 1)
                    except Exception as time_err:
                        app.logger.warning(f"Fehler beim Parsen der Dienstzeit für {dienst.get('datum')}: {time_err}")
                        event.make_all_day()
                else:
                    # Ganztägiger Termin, wenn keine Dienstzeit angegeben
                    event.make_all_day()
                
                cal.events.add(event)
            except Exception as date_err:
                app.logger.warning(f"Fehler beim Parsen des Datums {dienst.get('datum')}: {date_err}")
                continue
        
        # iCal-Datei zurückgeben
        ical_data = cal.serialize()
        response = Response(ical_data, mimetype='text/calendar')
        response.headers['Content-Disposition'] = f'attachment; filename=vivsync-{token}.ics'
        return response
        
    except Exception as e:
        app.logger.error(f"Fehler bei der Kalendergenerierung für Token {token}: {str(e)}", exc_info=True)
        return "Interner Serverfehler bei der Kalendergenerierung", 500

@app.route('/')
def index():
    """Einfache Homepage"""
    return """
    <html>
        <head>
            <title>VivSync - Vivendi Kalender-Synchronisation</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 2em; line-height: 1.6; }
                h1 { color: #333; }
            </style>
        </head>
        <body>
            <h1>VivSync - Server</h1>
            <p>Dies ist der VivSync-Server für die Kalender-Synchronisation.</p>
            <p>Benutzen Sie die VivSync-App, um Ihren Vivendi-Dienstplan zu synchronisieren.</p>
            <hr>
            <p><small>&copy; 2025 VivSync</small></p>
        </body>
    </html>
    """

@app.errorhandler(404)
def not_found(e):
    """Handler für 404-Fehler"""
    return jsonify({
        "status": "error",
        "message": "Ressource nicht gefunden",
        "error_code": 404
    }), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Handler für 500-Fehler"""
    app.logger.error(f"500 Fehler: {str(e)}")
    return jsonify({
        "status": "error",
        "message": "Interner Serverfehler",
        "error_code": 500
    }), 500

# API-Endpunkt für Versionsüberprüfung (Update-Funktionalität)
@app.route('/api/version', methods=['GET'])
def get_version():
    """Gibt aktuelle Versionsinformationen für den Client zurück"""
    return jsonify({
        "version": "1.0.0",
        "download_url": "https://vivsync.com/download/vivsync-1.0.0.exe",
        "release_notes": "Erste stabile Version mit automatischer Dienstplanerkennung und variabler Gültigkeitsdauer für Links."
    })

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)
