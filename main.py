import sys
import os
import atexit
import subprocess
from PyQt5.QtWidgets import (QApplication, QMessageBox, QFileDialog, QSystemTrayIcon,
                            QMenu, QAction, QInputDialog, QLineEdit, QDialog, QLabel,
                            QVBoxLayout, QPushButton, QHBoxLayout)
from PyQt5.QtCore import QThread, pyqtSignal, QUrl, QTimer, QTime, QSettings
from PyQt5.QtGui import QDesktopServices, QIcon
from gui import MainWindow
import config
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta
import argparse
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import threading
import signal
from playwright.sync_api import sync_playwright

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

# Globale Variablen für bessere Prozessverwaltung
active_threads = []
scheduler = None
tray_icon = None
app = None

# Importiere die Playwright-basierte extract_dienste Funktion
from vivendi_extract import extract_dienste

# Open-Source-Informationen
OPEN_SOURCE_INFO = {
    "name": "VivSync",
    "license": "GPL-3.0",
    "description": "Freie Open-Source-Software zur Synchronisation von Vivendi-Dienstplänen",
    "repository": "https://github.com/Belafone/VivSync",
    "version": config.VERSION
}

# Update-Checker (Angepasst für GitHub)
def check_for_updates(silent=False):
    """
    Prüft, ob eine neue Version auf GitHub verfügbar ist
    
    Args:
        silent (bool): Wenn True, wird kein Popup angezeigt wenn keine Updates verfügbar sind
    
    Returns:
        bool: True wenn Updates verfügbar sind, sonst False
    """
    try:
        logger.info("Prüfe auf Updates bei GitHub...")
        
        # Direkte Abfrage der GitHub API
        response = requests.get(
            "https://api.github.com/repos/Belafone/VivSync/releases/latest",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            server_version = data.get("tag_name", "v0.0.0").lstrip("v")
            download_url = data.get("html_url", "")  # Link zur Release-Seite
            release_notes = data.get("body", "")
            
            # Vergleiche Versionen
            current_version = config.VERSION
            logger.info(f"Aktuelle Version: {current_version}, GitHub-Version: {server_version}")
            
            if server_version > current_version:
                logger.info(f"Neue Version verfügbar: {server_version}")
                
                # Zeige Popup nur wenn nicht im silent-Modus
                if not silent and app:
                    msg = QMessageBox()
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Update verfügbar")
                    msg.setText(f"Eine neue Version von VivSync ist verfügbar: {server_version}")
                    msg.setInformativeText(f"Aktuelle Version: {current_version}\n\nNeuerungen:\n{release_notes}")
                    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                    msg.setDefaultButton(QMessageBox.Yes)
                    msg.setButtonText(QMessageBox.Yes, "Auf GitHub anzeigen")
                    msg.setButtonText(QMessageBox.No, "Später")
                    
                    if msg.exec_() == QMessageBox.Yes:
                        QDesktopServices.openUrl(QUrl(download_url))
                
                return True
            else:
                logger.info("Keine Updates verfügbar.")
                if not silent and app:
                    QMessageBox.information(None, "Keine Updates", 
                                           f"Sie verwenden bereits die neueste Version ({current_version}).")
                return False
        else:
            raise Exception(f"GitHub API-Fehler: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Fehler beim Prüfen auf Updates: {str(e)}")
        if not silent:
            QMessageBox.warning(None, "Update-Fehler", 
                               f"Beim Prüfen auf Updates ist ein Fehler aufgetreten:\n{str(e)}")
        return False

# Infodialog für Open Source
def show_open_source_info():
    """Zeigt Informationen zur Open-Source-Software an"""
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle("Über VivSync")
    msg.setText(f"VivSync {OPEN_SOURCE_INFO['version']}")
    msg.setInformativeText(
        f"{OPEN_SOURCE_INFO['description']}\n\n"
        f"Die Windows-Sicherheitswarnung erscheint, weil die Software nicht mit einem\n"
        f"kommerziellen Code-Signing-Zertifikat signiert ist.\n\n"
        f"Der Quellcode ist öffentlich verfügbar unter:\n"
        f"{OPEN_SOURCE_INFO['repository']}\n\n"
        f"Lizenz: {OPEN_SOURCE_INFO['license']}"
    )
    msg.setStandardButtons(QMessageBox.Ok)
    msg.addButton("GitHub öffnen", QMessageBox.ActionRole)
    
    result = msg.exec_()
    if result == 0:  # "GitHub öffnen" Button
        QDesktopServices.openUrl(QUrl(OPEN_SOURCE_INFO['repository']))

class ExtractionThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, username, password):
        super().__init__()
        self.username = username
        self.password = password
        
        # Thread registrieren
        global active_threads
        active_threads.append(self)

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
        finally:
            # Thread aus Liste entfernen wenn beendet
            global active_threads
            if self in active_threads:
                active_threads.remove(self)

class SyncThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str, str)
    error_signal = pyqtSignal(str)

    def __init__(self, credentials):
        super().__init__()
        self.credentials = credentials
        
        # Thread registrieren
        global active_threads
        active_threads.append(self)

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
        finally:
            # Thread aus Liste entfernen wenn beendet
            global active_threads
            if self in active_threads:
                active_threads.remove(self)

class AutoSyncManager:
    """Verwaltet die automatische Synchronisation im Hintergrund"""
    
    def __init__(self, parent=None):
        self.parent = parent
        global scheduler
        scheduler = BackgroundScheduler()
        scheduler.start()
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
            self.job = scheduler.add_job(
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
                    global tray_icon
                    if tray_icon:
                        tray_icon.showMessage(
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
                    if tray_icon:
                        tray_icon.showMessage(
                            "VivSync - Fehler",
                            error_msg,
                            QSystemTrayIcon.Critical,
                            5000
                        )
                    return False
            else:
                error_msg = f"HTTP-Fehler: {response.status_code} - {response.text}"
                logger.error(error_msg)
                if tray_icon:
                    tray_icon.showMessage(
                        "VivSync - Fehler",
                        error_msg,
                        QSystemTrayIcon.Critical,
                        5000
                    )
                return False
        except Exception as e:
            error_msg = f"Fehler bei automatischer Synchronisation: {str(e)}"
            logger.error(error_msg)
            if tray_icon:
                tray_icon.showMessage(
                    "VivSync - Fehler",
                    error_msg,
                    QSystemTrayIcon.Critical,
                    5000
                )
            return False
    
    def shutdown(self):
        """Beendet den Scheduler sauber"""
        global scheduler
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
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
    parser.add_argument('--check-updates', action='store_true', help='Nach Updates suchen')
    parser.add_argument('--skip-updates', action='store_true', help='Updateprüfung überspringen')
    return parser.parse_args()

def ensure_browser_installed():
    """
    Stellt sicher, dass der Playwright Chromium-Browser installiert ist.
    Versucht ihn automatisch zu installieren, falls er fehlt.
    """
    try:
        # Logging initialisieren
        log_handler = logging.StreamHandler()
        log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        setup_logger = logging.getLogger("VivSync.Setup")
        setup_logger.setLevel(logging.INFO)
        if not setup_logger.handlers:
            setup_logger.addHandler(log_handler)
        
        setup_logger.info("Prüfe Playwright-Installation...")
        
        # Prüfe, ob Browser gestartet werden kann
        try:
            with sync_playwright() as p:
                try:
                    # Versuche, einen Browser zu starten
                    browser = p.chromium.launch()
                    browser.close()
                    setup_logger.info("Playwright Chromium-Browser ist korrekt installiert.")
                    return True
                except Exception as launch_error:
                    setup_logger.warning(f"Browser konnte nicht gestartet werden: {launch_error}")
                    setup_logger.info("Versuche, Chromium-Browser zu installieren...")
                    
                    try:
                        # Browser automatisch installieren
                        result = subprocess.run(
                            ["playwright", "install", "chromium"],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if result.returncode == 0:
                            setup_logger.info("Chromium-Browser erfolgreich installiert.")
                            return True
                        else:
                            setup_logger.error(f"Browser-Installation fehlgeschlagen: {result.stderr}")
                            return False
                    except Exception as install_error:
                        setup_logger.error(f"Fehler bei der Browser-Installation: {install_error}")
                        return False
        except ImportError:
            # Playwright ist nicht installiert
            setup_logger.error("Playwright ist nicht installiert. Versuche Installation...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "playwright"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    setup_logger.info("Playwright erfolgreich installiert. Installiere nun Browser...")
                    # Installiere Browser
                    result = subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if result.returncode == 0:
                        setup_logger.info("Chromium-Browser erfolgreich installiert.")
                        return True
                    else:
                        setup_logger.error(f"Browser-Installation fehlgeschlagen: {result.stderr}")
                        return False
                else:
                    setup_logger.error(f"Playwright-Installation fehlgeschlagen: {result.stderr}")
                    return False
            except Exception as install_error:
                setup_logger.error(f"Fehler bei der Playwright-Installation: {install_error}")
                return False
    except Exception as e:
        print(f"Unerwarteter Fehler bei der Browser-Installation: {e}")
        return False

def cleanup_resources():
    """Bereinigt alle Ressourcen vor dem Beenden"""
    global active_threads, scheduler, tray_icon
    
    # Threads beenden
    logger.info(f"Beende {len(active_threads)} aktive Threads...")
    for thread in active_threads[:]:  # Kopie der Liste verwenden
        try:
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)  # 1 Sekunde warten
                if thread.isRunning():
                    logger.warning(f"Thread konnte nicht sauber beendet werden, erzwinge Abbruch")
        except Exception as e:
            logger.error(f"Fehler beim Beenden eines Threads: {str(e)}")
    active_threads.clear()
    
    # Scheduler beenden
    if scheduler:
        try:
            if scheduler.running:
                scheduler.shutdown(wait=False)
                logger.info("Scheduler beendet")
        except Exception as e:
            logger.error(f"Fehler beim Beenden des Schedulers: {str(e)}")
    
    # Tray-Icon entfernen
    if tray_icon:
        try:
            tray_icon.hide()
            logger.info("Tray-Icon entfernt")
        except Exception as e:
            logger.error(f"Fehler beim Entfernen des Tray-Icons: {str(e)}")
    
    logger.info("Ressourcenbereinigung abgeschlossen")

def exit_application():
    """Beendet die Anwendung vollständig und sauber"""
    logger.info("Beende Anwendung...")
    
    # GUI-Elemente entfernen und Events verarbeiten
    if app:
        QApplication.processEvents()
    
    # Ressourcen bereinigen
    cleanup_resources()
    
    # Anwendung beenden
    if app:
        app.quit()
    
    # Falls das nicht ausreicht, drastischere Maßnahmen ergreifen
    try:
        import os
        logger.info("Erzwinge Beenden über os._exit(0)")
        os._exit(0)
    except:
        pass

def signal_handler(signum, frame):
    """Handler für Betriebssystem-Signale (SIGINT, SIGTERM)"""
    logger.info(f"Signal {signum} empfangen, beende Anwendung...")
    exit_application()

def main():
    # Kommandozeilenargumente parsen
    args = parse_arguments()
    
    # Signal-Handler für sauberes Beenden
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Aufräumen bei Programmende registrieren
    atexit.register(cleanup_resources)
    
    global app, tray_icon
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Verhindert Beenden beim Schließen des Hauptfensters
    
    # App-Version setzen
    app.setApplicationVersion(config.VERSION)
    app.setApplicationName("VivSync")
    
    # Nach Updates suchen, außer wenn explizit deaktiviert
    if not args.skip_updates:
        # Verwende silent=True bei Autostart
        check_for_updates(silent=args.autostart)
    
    # Fenster erstellen
    window = MainWindow()
    
    # Tray-Icon erstellen
    tray_icon = QSystemTrayIcon(QIcon("icon.ico") if os.path.exists("icon.ico") else QIcon())
    window.tray_icon = tray_icon
    
    tray_menu = QMenu()
    action_show = QAction("VivSync anzeigen", app)
    action_sync = QAction("Jetzt synchronisieren", app)
    action_update = QAction("Nach Updates suchen", app)
    action_about = QAction("Über VivSync", app)
    action_quit = QAction("Beenden", app)
    
    tray_menu.addAction(action_show)
    tray_menu.addAction(action_sync)
    tray_menu.addSeparator()
    tray_menu.addAction(action_update)
    tray_menu.addAction(action_about)
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
        sync_thread = SyncThread(credentials)
        sync_thread.update_signal.connect(window.update_status)
        sync_thread.progress_signal.connect(window.update_progress)
        sync_thread.finished_signal.connect(sync_finished)
        sync_thread.error_signal.connect(show_error)
        sync_thread.start()
    
    def setup_automation():
        """Richtet die Automatisierung ein"""
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
    
    # Custom close event für MainWindow
    original_close_event = window.closeEvent
    
    def custom_close_event(event):
        """Erweitert das Close-Event um saubere Prozessbeendigung"""
        # Original close event aufrufen (speichert Einstellungen)
        original_close_event(event)
        
        # Prüfen, ob die App im Tray bleiben soll
        if window.auto_sync_checkbox.isChecked() and window.auto_start_checkbox.isChecked():
            window.hide()
            tray_icon.showMessage(
                "VivSync",
                "VivSync läuft weiter im Hintergrund. Klicken Sie auf das Symbol, um das Fenster anzuzeigen.",
                QSystemTrayIcon.Information,
                3000
            )
            event.ignore()  # Event ignorieren, damit App weiterläuft
        else:
            # App wirklich beenden
            QTimer.singleShot(100, exit_application)
            event.accept()
    
    # Original close event mit erweitertem ersetzen
    window.closeEvent = custom_close_event
    
    # Event-Handler verbinden
    window.extract_button.clicked.connect(start_local_extraction)
    window.sync_button.clicked.connect(start_online_sync)
    window.copy_link_button.clicked.connect(copy_ical_link)
    window.open_link_button.clicked.connect(open_ical_link)
    window.donate_button.clicked.connect(open_donation_page)
    window.auto_button.clicked.connect(setup_automation)
    
    # Tray-Icon Event-Handler
    action_show.triggered.connect(toggle_window)
    action_sync.triggered.connect(perform_tray_sync)
    action_update.triggered.connect(lambda: check_for_updates(silent=False))
    action_about.triggered.connect(show_open_source_info)
    action_quit.triggered.connect(exit_application)
    tray_icon.activated.connect(lambda reason: toggle_window() if reason == QSystemTrayIcon.DoubleClick else None)
    
    # Anwendungslogik je nach Kommandozeilenargumenten
    if args.check_updates:
        # Nur nach Updates suchen und beenden
        logger.info("Update-Prüfung angefordert")
        check_for_updates(silent=False)
        exit_application()
        return
    
    elif args.autostart:
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
        
        # Open-Source-Status in der Statuszeile anzeigen
        window.statusBar().showMessage(f"VivSync {config.VERSION} - Open Source (GPL-3.0)")
    
    # Shutdown-Handler für sauberes Beenden
    app.aboutToQuit.connect(cleanup_resources)
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    # Stellen Sie sicher, dass Playwright und der Browser korrekt installiert sind
    if not ensure_browser_installed():
        print("FEHLER: Playwright-Browser konnte nicht installiert werden.")
        
        # Zeige Fehlermeldung in GUI, falls möglich
        try:
            app = QApplication(sys.argv)
            QMessageBox.critical(
                None, 
                "VivSync - Fehler",
                "Der benötigte Browser für die Automatisierung konnte nicht installiert werden.\n\n"
                "Bitte führen Sie in der Kommandozeile diese Befehle aus:\n"
                "pip install playwright\n"
                "playwright install chromium"
            )
            sys.exit(1)
        except Exception:
            print("Bitte installieren Sie Playwright manuell mit:\n"
                  "pip install playwright\n"
                  "playwright install chromium")
            sys.exit(1)
    
    main()
