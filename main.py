import sys
import os
from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt5.QtCore import QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from gui import MainWindow
from vivendi_extract import extract_dienste
import config
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta

class ExtractionThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)
    
    def __init__(self, username, password):
        super().__init__()
        self.username = username
        self.password = password
    
    def run(self):
        try:
            self.update_signal.emit("Starte Extraktion...")
            self.progress_signal.emit(10)
            
            dienste = extract_dienste(
                self.username,
                self.password,
                use_windows_login=True,
                status_callback=self.update_signal.emit,
                progress_callback=self.progress_signal.emit
            )
            
            if not dienste:
                self.error_signal.emit("Keine Dienste gefunden oder Fehler bei der Extraktion.")
                return
            
            self.update_signal.emit(f"{len(dienste)} Dienste erfolgreich extrahiert.")
            self.progress_signal.emit(100)
            self.finished_signal.emit(dienste)
        except Exception as e:
            self.error_signal.emit(f"Fehler: {str(e)}")

class SyncThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str, str)
    error_signal = pyqtSignal(str)
    
    def __init__(self, credentials):
        super().__init__()
        self.credentials = credentials
    
    def run(self):
        try:
            self.update_signal.emit("Starte Extraktion für Online-Synchronisation...")
            self.progress_signal.emit(10)
            
            dienste = extract_dienste(
                self.credentials["username"],
                self.credentials["password"],
                use_windows_login=True,
                status_callback=self.update_signal.emit,
                progress_callback=self.progress_signal.emit
            )
            
            if not dienste:
                self.error_signal.emit("Keine Dienste gefunden oder Fehler bei der Extraktion.")
                return
            
            self.update_signal.emit(f"{len(dienste)} Dienste extrahiert. Sende an Server...")
            self.progress_signal.emit(70)
            
            for dienst in dienste:
                dienst['username'] = self.credentials["username"]
            
            # Neue Struktur für die Server-Anfrage mit expiry_days
            payload = {
                "dienste": dienste,
                "expiry_days": self.credentials["expiry_days"]
            }
            
            response = requests.post(
                config.API_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json", 
                    "X-Username": self.credentials["username"]
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    ical_url = result.get("ical_url")
                    expires_in = result.get("expires_in", f"{self.credentials['expiry_days']} Tage")
                    self.update_signal.emit(f"Synchronisation erfolgreich! Der Link ist gültig für {expires_in}.")
                    self.progress_signal.emit(100)
                    self.finished_signal.emit(ical_url, expires_in)
                else:
                    self.error_signal.emit(f"Serverfehler: {result.get('message', 'Unbekannter Fehler')}")
            else:
                self.error_signal.emit(f"HTTP-Fehler: {response.status_code} - {response.text}")
        except Exception as e:
            self.error_signal.emit(f"Verbindungsfehler: {str(e)}")

def create_ics_file(dienste, filepath):
    cal = Calendar()
    for dienst in dienste:
        event = Event()
        event.name = f"{dienst['dienst']} - {dienst['position']}"
        event.begin = datetime.strptime(dienst['datum'], "%Y-%m-%d")
        
        if dienst['dienstzeit']:
            start_time, end_time = dienst['dienstzeit'].split(' - ')
            start_hour, start_minute = map(int, start_time.split(':'))
            event.begin = event.begin.replace(hour=start_hour, minute=start_minute)
            
            end_hour, end_minute = map(int, end_time.split(':'))
            if end_hour < start_hour:
                end_hour += 12
            
            event.end = event.begin.replace(hour=end_hour, minute=end_minute)
            if event.end < event.begin:
                event.end += timedelta(days=1)
        else:
            event.make_all_day()
        
        cal.events.add(event)
    
    with open(filepath, 'w') as f:
        f.writelines(cal.serialize_iter())
    
    return True

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    extraction_thread = None
    sync_thread = None
    
    def start_local_extraction():
        credentials = window.get_credentials()
        if not credentials["username"] or not credentials["password"]:
            QMessageBox.warning(window, "Fehlende Eingaben", "Bitte geben Sie Benutzername und Passwort ein.")
            return
        
        window.extract_button.setEnabled(False)
        window.sync_button.setEnabled(False)
        window.progress_bar.setValue(0)
        window.status_display.clear()
        
        nonlocal extraction_thread
        extraction_thread = ExtractionThread(
            credentials["username"],
            credentials["password"]
        )
        
        extraction_thread.update_signal.connect(window.update_status)
        extraction_thread.progress_signal.connect(window.update_progress)
        extraction_thread.finished_signal.connect(local_extraction_finished)
        extraction_thread.error_signal.connect(show_error)
        extraction_thread.start()
    
    def local_extraction_finished(dienste):
        window.extracted_dienste = dienste
        window.extract_button.setEnabled(True)
        window.sync_button.setEnabled(True)
        window.statusBar().showMessage(f"{len(dienste)} Dienste extrahiert")
        
        default_filename = f"Dienstplan_{datetime.now().strftime('%Y-%m-%d')}.ics"
        filepath, _ = QFileDialog.getSaveFileName(
            window,
            "Dienstplan speichern",
            default_filename,
            "iCalendar Dateien (*.ics)"
        )
        
        if filepath:
            if create_ics_file(dienste, filepath):
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText("Dienstplan erfolgreich gespeichert")
                msg.setInformativeText(f"Die Datei wurde unter {filepath} gespeichert.\nMöchten Sie die Datei jetzt öffnen?")
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                if msg.exec_() == QMessageBox.Yes:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(filepath))
    
    def start_online_sync():
        credentials = window.get_credentials()
        if not credentials["username"] or not credentials["password"]:
            QMessageBox.warning(window, "Fehlende Eingaben", "Bitte geben Sie Benutzername und Passwort ein.")
            return
        
        window.extract_button.setEnabled(False)
        window.sync_button.setEnabled(False)
        window.progress_bar.setValue(0)
        window.status_display.clear()
        
        nonlocal sync_thread
        sync_thread = SyncThread(credentials)  # Übergabe aller Anmeldedaten inkl. expiry_days
        
        sync_thread.update_signal.connect(window.update_status)
        sync_thread.progress_signal.connect(window.update_progress)
        sync_thread.finished_signal.connect(sync_finished)
        sync_thread.error_signal.connect(show_error)
        sync_thread.start()
    
    def sync_finished(ical_url, expires_in):
        window.set_ical_url(ical_url, expires_in)
        window.extract_button.setEnabled(True)
        window.sync_button.setEnabled(True)
        window.statusBar().showMessage(f"Online-Synchronisation abgeschlossen. Link gültig für {expires_in}")
        
        QMessageBox.information(window, "Synchronisation erfolgreich",
            f"Ihr Dienstplan wurde erfolgreich synchronisiert!\n\n"
            f"Verwenden Sie den folgenden Link, um Ihren Kalender zu abonnieren:\n"
            f"{ical_url}\n\n"
            f"Dieser Link ist für {expires_in} gültig und nur für Sie bestimmt.")
    
    def show_error(message):
        window.update_status(f"FEHLER: {message}")
        window.extract_button.setEnabled(True)
        window.sync_button.setEnabled(True)
        QMessageBox.critical(window, "Fehler", message)
    
    def copy_ical_link():
        if window.ical_url:
            clipboard = app.clipboard()
            clipboard.setText(window.ical_url)
            window.statusBar().showMessage("Link in die Zwischenablage kopiert", 3000)
    
    def open_ical_link():
        if window.ical_url:
            QDesktopServices.openUrl(QUrl(window.ical_url))
    
    def open_donation_page():
        donation_url = config.DONATION_URL
        QDesktopServices.openUrl(QUrl(donation_url))
    
    window.extract_button.clicked.connect(start_local_extraction)
    window.sync_button.clicked.connect(start_online_sync)
    window.copy_link_button.clicked.connect(copy_ical_link)
    window.open_link_button.clicked.connect(open_ical_link)
    window.donate_button.clicked.connect(open_donation_page)
    
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
