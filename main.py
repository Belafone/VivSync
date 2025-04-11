import sys
import os
from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtCore import QThread, pyqtSignal, QUrl, QTimer, QTime
from PyQt5.QtGui import QDesktopServices, QIcon
from gui import MainWindow
from vivendi_extract import extract_dienste
import config
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta
import argparse
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Konfiguration des Loggings
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("vivsync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("VivSync")

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

class AutoSyncManager:
    """Verwaltet die automatische Synchronisation im Hintergrund"""
    
    def __init__(self, parent=None):
        self.parent = parent
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.job = None
        logger.info("AutoSyncManager initialisiert")
    
    def setup_job(self, credentials, sync_time):
        """Richtet einen automatischen Synchronisationsjob ein"""
        if self.job:
            self.job.remove()
            logger.info("Bestehender Job entfernt")
        
        # Parse sync_time im HH:MM Format
        try:
            hour, minute = map(int, sync_time.split(':'))
            
            # Job einrichten (täglich zur festgelegten Zeit)
            self.job = self.scheduler.add_job(
                self.perform_sync,
                trigger=CronTrigger(hour=hour, minute=minute),
                args=[credentials],
                id='auto_sync',
                replace_existing=True
            )
            
            logger.info(f"Automatischer Sync eingerichtet für {sync_time} Uhr")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Einrichten des Jobs: {str(e)}")
            return False
    
    def perform_sync(self, credentials):
        """Führt die automatische Synchronisation durch"""
        logger.info("Starte automatische Synchronisation...")
        
        try:
            # Dienste extrahieren
            dienste = extract_dienste(
                credentials["username"],
                credentials["password"],
                use_windows_login=True,
                status_callback=logger.info,
                progress_callback=lambda x: None  # Kein UI-Update nötig
            )
            
            if not dienste:
                logger.error("Keine Dienste gefunden oder Fehler bei der Extraktion.")
                return False
            
            logger.info(f"{len(dienste)} Dienste extrahiert. Sende an Server...")
            
            for dienst in dienste:
                dienst['username'] = credentials["username"]
            
            # Neue Struktur für die Server-Anfrage mit expiry_days
            payload = {
                "dienste": dienste,
                "expiry_days": credentials["expiry_days"]
            }
            
            response = requests.post(
                config.API_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Username": credentials["username"]
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    ical_url = result.get("ical_url")
                    expires_in = result.get("expires_in", f"{credentials['expiry_days']} Tage")
                    logger.info(f"Automatische Synchronisation erfolgreich! Link gültig für {expires_in}.")
                    
                    # Wenn UI vorhanden, URL aktualisieren
                    if self.parent and hasattr(self.parent, 'set_ical_url'):
                        self.parent.set_ical_url(ical_url, expires_in)
                    
                    # Systembenachrichtigung anzeigen
                    if self.parent and hasattr(self.parent, 'tray_icon'):
                        self.parent.tray_icon.showMessage(
                            "VivSync - Automatische Synchronisation",
                            f"Ihr Dienstplan wurde erfolgreich synchronisiert. Der Link ist gültig für {expires_in}.",
                            QSystemTrayIcon.Information,
                            5000
                        )
                    
                    return True
                else:
                    error_msg = f"Serverfehler: {result.get('message', 'Unbekannter Fehler')}"
                    logger.error(error_msg)
                    # Systembenachrichtigung anzeigen
                    if self.parent and hasattr(self.parent, 'tray_icon'):
                        self.parent.tray_icon.showMessage(
                            "VivSync - Fehler",
                            error_msg,
                            QSystemTrayIcon.Critical,
                            5000
                        )
                    return False
            else:
                error_msg = f"HTTP-Fehler: {response.status_code} - {response.text}"
                logger.error(error_msg)
                # Systembenachrichtigung anzeigen
                if self.parent and hasattr(self.parent, 'tray_icon'):
                    self.parent.tray_icon.showMessage(
                        "VivSync - Fehler",
                        error_msg,
                        QSystemTrayIcon.Critical,
                        5000
                    )
                return False
        except Exception as e:
            error_msg = f"Fehler bei automatischer Synchronisation: {str(e)}"
            logger.error(error_msg)
            # Systembenachrichtigung anzeigen
            if self.parent and hasattr(self.parent, 'tray_icon'):
                self.parent.tray_icon.showMessage(
                    "VivSync - Fehler",
                    error_msg,
                    QSystemTrayIcon.Critical,
                    5000
                )
            return False
    
    def shutdown(self):
        """Beendet den Scheduler sauber"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler beendet")

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

def parse_arguments():
    """Kommandozeilenargumente verarbeiten"""
    parser = argparse.ArgumentParser(description='VivSync - Vivendi Dienstplan Synchronisation')
    parser.add_argument('--autostart', action='store_true', help='Im Hintergrund starten')
    parser.add_argument('--sync-now', action='store_true', help='Sofort synchronisieren und beenden')
    return parser.parse_args()

def main():
    # Kommandozeilenargumente parsen
    args = parse_arguments()
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Verhindert Beenden beim Schließen des Hauptfensters
    
    # Fenster erstellen
    window = MainWindow()
    
    # Tray-Icon erstellen
    tray_icon = QSystemTrayIcon(QIcon("icon.ico") if os.path.exists("icon.ico") else QIcon())
    window.tray_icon = tray_icon
    
    tray_menu = QMenu()
    action_show = QAction("VivSync anzeigen", app)
    action_sync = QAction("Jetzt synchronisieren", app)
    action_quit = QAction("Beenden", app)
    
    tray_menu.addAction(action_show)
    tray_menu.addAction(action_sync)
    tray_menu.addSeparator()
    tray_menu.addAction(action_quit)
    
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    
    # Manager für automatische Synchronisation
    auto_sync_manager = AutoSyncManager(window)
    window.auto_sync_manager = auto_sync_manager
    
    extraction_thread = None
    sync_thread = None
    
    def toggle_window():
        if window.isVisible():
            window.hide()
        else:
            window.show()
            window.activateWindow()
    
    def start_local_extraction():
        credentials = window.get_credentials()
        if not credentials["username"] or not credentials["password"]:
            QMessageBox.warning(window, "Fehlende Eingaben", "Bitte geben Sie E-Mail-Adresse und Passwort ein.")
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
            QMessageBox.warning(window, "Fehlende Eingaben", "Bitte geben Sie E-Mail-Adresse und Passwort ein.")
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
    
    def setup_automation():
        """Richtet die automatische Synchronisation ein"""
        try:
            # Einstellungen aus UI abrufen
            credentials = window.get_credentials()
            if not credentials["username"] or not credentials["password"]:
                QMessageBox.warning(window, "Fehlende Eingaben", "Bitte geben Sie E-Mail-Adresse und Passwort ein.")
                return
            
            # Automatisierung aktiviert?
            if not window.auto_sync_checkbox.isChecked():
                QMessageBox.information(window, "Automatisierung", 
                    "Die automatische Synchronisation ist deaktiviert.\n"
                    "Aktivieren Sie die Option, um die Automatisierung einzurichten.")
                return
            
            # Zeiten für Automatisierung abrufen
            sync_time = window.sync_time_edit.time().toString("HH:mm")
            
            # Job im Scheduler einrichten
            success = auto_sync_manager.setup_job(credentials, sync_time)
            
            # Einstellungen speichern
            window.save_settings()
            
            if success:
                QMessageBox.information(window, "Automatisierung eingerichtet", 
                    f"Die automatische Synchronisation wurde für täglich {sync_time} Uhr eingerichtet.\n\n"
                    f"E-Mail: {credentials['username']}\n"
                    f"Gültigkeitsdauer: {credentials['expiry_days']} Tage\n\n"
                    "Bei aktiviertem Autostart wird VivSync im Hintergrund ausgeführt.")
                
                window.update_status(f"Automatisierung eingerichtet: Tägliche Synchronisation um {sync_time} Uhr")
            else:
                QMessageBox.warning(window, "Fehler", 
                    "Die Automatisierung konnte nicht eingerichtet werden.\n"
                    "Bitte prüfen Sie die Protokolldatei für weitere Informationen.")
        
        except Exception as e:
            logger.error(f"Fehler beim Einrichten der Automatisierung: {str(e)}")
            QMessageBox.critical(window, "Fehler", f"Automatisierung konnte nicht eingerichtet werden: {str(e)}")
    
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
    
    def perform_tray_sync():
        """Startet eine Synchronisation aus dem Tray-Menü heraus"""
        credentials = window.get_credentials()
        if not credentials["username"] or not credentials["password"]:
            tray_icon.showMessage(
                "VivSync - Fehler",
                "Keine Anmeldedaten gespeichert. Bitte starten Sie VivSync und geben Sie die Anmeldedaten ein.",
                QSystemTrayIcon.Critical,
                5000
            )
            window.show()
            return
        
        # Direktaufruf des Sync-Managers
        result = auto_sync_manager.perform_sync(credentials)
        if result:
            tray_icon.showMessage(
                "VivSync - Synchronisation",
                "Ihr Dienstplan wurde erfolgreich synchronisiert.",
                QSystemTrayIcon.Information,
                5000
            )
        # Bei Fehlern zeigt der Manager bereits eigene Benachrichtigungen
    
    def exit_application():
        """Beendet die Anwendung sauber"""
        try:
            # Scheduler beenden
            auto_sync_manager.shutdown()
            
            # Anwendung beenden
            app.quit()
        except Exception as e:
            logger.error(f"Fehler beim Beenden: {str(e)}")
            app.quit()
    
    # Event-Handler verbinden
    window.extract_button.clicked.connect(start_local_extraction)
    window.sync_button.clicked.connect(start_online_sync)
    window.copy_link_button.clicked.connect(copy_ical_link)
    window.open_link_button.clicked.connect(open_ical_link)
    window.donate_button.clicked.connect(open_donation_page)
    window.auto_button.clicked.connect(setup_automation)  # Neue Verbindung für Automatisierung
    
    # Tray-Icon Event-Handler
    action_show.triggered.connect(toggle_window)
    action_sync.triggered.connect(perform_tray_sync)
    action_quit.triggered.connect(exit_application)
    tray_icon.activated.connect(lambda reason: toggle_window() if reason == QSystemTrayIcon.DoubleClick else None)
    
    # Anwendungslogik je nach Kommandozeilenargumenten
    if args.autostart:
        # Im Hintergrund starten (nur in Tray anzeigen)
        logger.info("Anwendung im Hintergrund gestartet (Autostart)")
        
        # Automatisierung aus gespeicherten Einstellungen konfigurieren
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings("VivSync", "KalenderSync")
            
            auto_sync = settings.value("auto_sync", False, type=bool)
            if auto_sync:
                username = settings.value("username", "")
                sync_time = settings.value("sync_time", "06:00")
                expiry_days = settings.value("expiry_days", 30, type=int)
                
                if username:
                    # Passwort aus Keyring holen
                    try:
                        import keyring
                        password = keyring.get_password("VivSync", username)
                        
                        if password:
                            credentials = {
                                "username": username,
                                "password": password,
                                "expiry_days": expiry_days
                            }
                            
                            # Job einrichten
                            auto_sync_manager.setup_job(credentials, sync_time)
                            
                            logger.info(f"Automatische Synchronisation für {sync_time} Uhr konfiguriert")
                            
                            # Benachrichtigung anzeigen
                            tray_icon.showMessage(
                                "VivSync",
                                f"VivSync läuft im Hintergrund und synchronisiert täglich um {sync_time} Uhr.",
                                QSystemTrayIcon.Information,
                                5000
                            )
                    except Exception as e:
                        logger.error(f"Fehler beim Abrufen des Passworts: {str(e)}")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Automatisierungseinstellungen: {str(e)}")
    
    elif args.sync_now:
        # Sofortige Synchronisation und Beenden
        logger.info("Sofortige Synchronisation angefordert")
        
        # Anmeldedaten aus gespeicherten Einstellungen laden
        try:
            from PyQt5.QtCore import QSettings
            settings = QSettings("VivSync", "KalenderSync")
            
            username = settings.value("username", "")
            expiry_days = settings.value("expiry_days", 30, type=int)
            
            if username:
                # Passwort aus Keyring holen
                try:
                    import keyring
                    password = keyring.get_password("VivSync", username)
                    
                    if password:
                        credentials = {
                            "username": username,
                            "password": password,
                            "expiry_days": expiry_days
                        }
                        
                        # Synchronisation durchführen
                        success = auto_sync_manager.perform_sync(credentials)
                        
                        if success:
                            logger.info("Sofortige Synchronisation erfolgreich")
                        else:
                            logger.error("Sofortige Synchronisation fehlgeschlagen")
                        
                        # Kurz warten, damit Nachrichten angezeigt werden können
                        QTimer.singleShot(5000, exit_application)
                    else:
                        logger.error("Kein Passwort gespeichert")
                        exit_application()
                except Exception as e:
                    logger.error(f"Fehler beim Abrufen des Passworts: {str(e)}")
                    exit_application()
            else:
                logger.error("Kein Benutzername gespeichert")
                exit_application()
        except Exception as e:
            logger.error(f"Fehler beim Laden der Einstellungen: {str(e)}")
            exit_application()
    else:
        # Normaler Start mit sichtbarem Fenster
        window.show()
    
    # Shutdown-Handler für sauberes Beenden
    app.aboutToQuit.connect(auto_sync_manager.shutdown)
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
