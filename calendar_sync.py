from googleapiclient.discovery import build
from google.oauth2 import service_account
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os

# Konfiguration für Service Account
P12_FILE = r"C:\Users\mrhal\Documents\Projekt Pep\viv-pep-key.p12"
SERVICE_ACCOUNT_EMAIL = "viv-pep-syc@dienstplan-halbautomatisch.iam.gserviceaccount.com"

def sync_to_calendar(dienste, calendar_id):
    """
    Synchronisiert die extrahierten Dienste mit dem Google Kalender
    
    Args:
        dienste: Liste von Dienst-Dictionaries mit Datum, Dienst, Position und Dienstzeit
        calendar_id: ID des Google Kalenders
    
    Returns:
        Dictionary mit Ergebnissen (erstellt, aktualisiert, gelöscht)
    """
    print(f"Starte Synchronisation mit Kalender: {calendar_id}")
    
    try:
        # Google Calendar API initialisieren
        credentials = ServiceAccountCredentials.from_p12_keyfile(
            SERVICE_ACCOUNT_EMAIL,
            P12_FILE,
            scopes=['https://www.googleapis.com/auth/calendar'],
            private_key_password='notasecret'
        )
        
        service = build('calendar', 'v3', credentials=credentials)
        
        # Bestehende Einträge mit [AutoSync] Tag abrufen
        existing_events = get_existing_events(service, calendar_id)
        print(f"Gefundene bestehende Einträge: {len(existing_events)}")
        
        # Zähler für Statistik
        created = 0
        updated = 0
        deleted = 0
        
        # Dienste synchronisieren
        for dienst in dienste:
            event_id = find_matching_event(existing_events, dienst)
            
            if event_id:
                # Eintrag existiert bereits, prüfen ob Update nötig
                if update_needed(existing_events[event_id], dienst):
                    update_event(service, calendar_id, event_id, dienst)
                    updated += 1
                # Eintrag aus der Liste entfernen, da er bearbeitet wurde
                existing_events.pop(event_id, None)
            else:
                # Neuen Eintrag erstellen
                create_event(service, calendar_id, dienst)
                created += 1
        
        # Verbleibende Einträge löschen (nicht mehr im Dienstplan)
        for event_id in existing_events:
            delete_event(service, calendar_id, event_id)
            deleted += 1
        
        return {
            "status": "success",
            "created": created,
            "updated": updated,
            "deleted": deleted
        }
    
    except Exception as e:
        print(f"Fehler bei der Kalendersynchronisation: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

def get_existing_events(service, calendar_id):
    """Ruft alle bestehenden Einträge mit [AutoSync] Tag ab"""
    events = {}
    page_token = None
    
    # Zeitraum: 1 Monat vor und nach heute
    now = datetime.now()
    time_min = datetime(now.year, now.month, 1).isoformat() + 'Z'
    if now.month == 12:
        time_max = datetime(now.year + 1, 1, 31).isoformat() + 'Z'
    else:
        time_max = datetime(now.year, now.month + 1, 31).isoformat() + 'Z'
    
    while True:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            pageToken=page_token,
            q="[AutoSync]"  # Suche nach Tag im Titel
        ).execute()
        
        for event in events_result.get('items', []):
            events[event['id']] = event
        
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break
    
    return events

def find_matching_event(existing_events, dienst):
    """Findet einen passenden Eintrag für den Dienst"""
    for event_id, event in existing_events.items():
        event_date = event.get('start', {}).get('date', '')
        if event_date == dienst['datum']:
            return event_id
    return None

def update_needed(event, dienst):
    """Prüft, ob ein Update nötig ist"""
    # Extrahiere Dienstcode und Position aus dem Titel
    title = event.get('summary', '')
    
    # Erstelle erwarteten Titel
    expected_title = f"[AutoSync] {dienst['dienst']}"
    if dienst['position']:
        expected_title += f" - {dienst['position']}"
    
    # Prüfe, ob sich etwas geändert hat
    if title != expected_title:
        return True
    
    # Prüfe Dienstzeit in der Beschreibung
    description = event.get('description', '')
    if dienst['dienstzeit'] and dienst['dienstzeit'] not in description:
        return True
    
    return False

def create_event(service, calendar_id, dienst):
    """Erstellt einen neuen Kalendereintrag"""
    summary = f"[AutoSync] {dienst['dienst']}"
    if dienst['position']:
        summary += f" - {dienst['position']}"
    
    description = f"Automatisch synchronisierter Dienst\n"
    if dienst['dienstzeit']:
        description += f"Dienstzeit: {dienst['dienstzeit']}"
    
    event = {
        'summary': summary,
        'description': description,
        'start': {
            'date': dienst['datum'],
        },
        'end': {
            'date': dienst['datum'],
        },
        'transparency': 'transparent'  # Zeigt als "Frei" im Kalender
    }
    
    service.events().insert(calendarId=calendar_id, body=event).execute()
    print(f"Neuer Eintrag erstellt: {dienst['datum']} - {summary}")

def update_event(service, calendar_id, event_id, dienst):
    """Aktualisiert einen bestehenden Kalendereintrag"""
    summary = f"[AutoSync] {dienst['dienst']}"
    if dienst['position']:
        summary += f" - {dienst['position']}"
    
    description = f"Automatisch synchronisierter Dienst\n"
    if dienst['dienstzeit']:
        description += f"Dienstzeit: {dienst['dienstzeit']}"
    
    event = {
        'summary': summary,
        'description': description,
    }
    
    service.events().patch(calendarId=calendar_id, eventId=event_id, body=event).execute()
    print(f"Eintrag aktualisiert: {dienst['datum']} - {summary}")

def delete_event(service, calendar_id, event_id):
    """Löscht einen Kalendereintrag"""
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    print(f"Eintrag gelöscht: {event_id}")

# Für Testzwecke
if __name__ == "__main__":
    # Beispiel-Dienste
    test_dienste = [
        {
            'datum': '2025-04-02',
            'dienst': 'D33',
            'position': 'Oben',
            'dienstzeit': '07:00 - 14:00'
        },
        {
            'datum': '2025-04-03',
            'dienst': 'A102',
            'position': 'Unten',
            'dienstzeit': '06:00 - 11:30'
        }
    ]
    
    # Test-Kalender-ID
    test_calendar_id = "primary"  # "primary" ist der Hauptkalender des Nutzers
    
    # Synchronisation testen
    result = sync_to_calendar(test_dienste, test_calendar_id)
    print(result)
