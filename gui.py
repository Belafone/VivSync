import sys
import keyring  # Neue Bibliothek für sichere Anmeldedatenspeicherung
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QLabel, QLineEdit, QPushButton,
                            QTextEdit, QMessageBox, QProgressBar, QCheckBox,
                            QGroupBox, QFileDialog, QSpinBox)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtCore import QUrl
import config

# Name des Keyring-Services für die Kennwortspeicherung
KEYRING_SERVICE = "VivSync"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.extracted_dienste = []
        self.ical_url = None
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("Vivendi Kalender-Synchronisation")
        self.setMinimumSize(600, 600)  # Etwas größer für zusätzliche Elemente

        # Hauptlayout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Vivendi-Anmeldedaten
        credentials_group = QGroupBox("Vivendi Anmeldedaten")
        credentials_layout = QVBoxLayout()
        
        username_layout = QHBoxLayout()
        username_layout.addWidget(QLabel("Benutzername:"))
        self.username_input = QLineEdit()
        username_layout.addWidget(self.username_input)
        credentials_layout.addLayout(username_layout)

        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Passwort:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(self.password_input)
        credentials_layout.addLayout(password_layout)

        # Gültigkeitsdauer für iCal-Links
        expiry_layout = QHBoxLayout()
        expiry_layout.addWidget(QLabel("Gültigkeitsdauer des Links (Tage):"))
        self.expiry_input = QSpinBox()
        self.expiry_input.setRange(1, 365)
        self.expiry_input.setValue(30)  # Standardwert: 30 Tage
        self.expiry_input.setToolTip("Anzahl der Tage, für die der iCal-Link gültig sein soll")
        expiry_layout.addWidget(self.expiry_input)
        credentials_layout.addLayout(expiry_layout)

        # Anmeldedaten speichern
        save_layout = QHBoxLayout()
        self.save_credentials = QCheckBox("Anmeldedaten sicher speichern")
        self.save_credentials.setToolTip("Speichert Anmeldedaten verschlüsselt im System-Keyring")
        save_layout.addWidget(self.save_credentials)
        credentials_layout.addLayout(save_layout)

        credentials_group.setLayout(credentials_layout)
        main_layout.addWidget(credentials_group)

        # Aktionsbuttons
        button_layout = QHBoxLayout()
        self.extract_button = QPushButton("Kalender speichern")
        button_layout.addWidget(self.extract_button)
        
        self.sync_button = QPushButton("Mit Online-Kalender synchronisieren")
        button_layout.addWidget(self.sync_button)
        
        main_layout.addLayout(button_layout)

        # Fortschrittsanzeige
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Statusanzeige
        self.status_display = QTextEdit()
        self.status_display.setReadOnly(True)
        main_layout.addWidget(self.status_display)

        # iCal-Link Anzeige
        ical_group = QGroupBox("iCal-Link (Online-Synchronisation)")
        ical_layout = QVBoxLayout()
        
        self.ical_link_display = QLineEdit()
        self.ical_link_display.setReadOnly(True)
        ical_layout.addWidget(self.ical_link_display)
        
        ical_buttons = QHBoxLayout()
        self.copy_link_button = QPushButton("Link kopieren")
        self.copy_link_button.setEnabled(False)
        ical_buttons.addWidget(self.copy_link_button)
        
        self.open_link_button = QPushButton("Im Browser öffnen")
        self.open_link_button.setEnabled(False)
        ical_buttons.addWidget(self.open_link_button)
        
        ical_layout.addLayout(ical_buttons)
        ical_group.setLayout(ical_layout)
        main_layout.addWidget(ical_group)

        # PayPal Spendenbutton
        donation_layout = QHBoxLayout()
        donation_layout.addStretch()
        
        self.donate_button = QPushButton("Unterstützen Sie dieses Projekt")
        self.donate_button.setStyleSheet("background-color: #0070BA; color: white; padding: 5px 10px;")
        try:
            # Versuche, ein PayPal-Icon zu laden, falls vorhanden
            self.donate_button.setIcon(QIcon("paypal_icon.png"))
        except:
            pass
        
        donation_layout.addWidget(self.donate_button)
        donation_layout.addStretch()
        main_layout.addLayout(donation_layout)

        # Statuszeile
        self.statusBar().showMessage("Bereit")

    def load_settings(self):
        """Lädt Einstellungen und Anmeldedaten (sicher über keyring)"""
        try:
            settings = QSettings("VivSync", "KalenderSync")
            
            # Username aus QSettings laden
            username = settings.value("username", "")
            self.username_input.setText(username)
            
            # Passwort sicher aus dem Keyring laden
            if username:
                try:
                    password = keyring.get_password(KEYRING_SERVICE, username)
                    if password:
                        self.password_input.setText(password)
                except Exception as e:
                    self.update_status(f"Hinweis: Gespeichertes Passwort konnte nicht geladen werden: {str(e)}")
            
            # Andere Einstellungen laden
            self.save_credentials.setChecked(settings.value("save_credentials", False, type=bool))
            self.expiry_input.setValue(settings.value("expiry_days", 30, type=int))
        
        except Exception as e:
            self.update_status(f"Fehler beim Laden der Einstellungen: {str(e)}")
            # Fallback auf Standardwerte
            self.save_credentials.setChecked(False)
            self.expiry_input.setValue(30)

    def save_settings(self):
        """Speichert Einstellungen und Anmeldedaten (sicher über keyring)"""
        try:
            settings = QSettings("VivSync", "KalenderSync")
            
            # Speichern der Anmeldedaten je nach Checkbox-Status
            if self.save_credentials.isChecked():
                username = self.username_input.text()
                password = self.password_input.text()
                
                # Username in QSettings speichern (nicht sensitiv)
                settings.setValue("username", username)
                
                # Passwort sicher im Keyring speichern
                if username and password:
                    try:
                        keyring.set_password(KEYRING_SERVICE, username, password)
                    except Exception as e:
                        QMessageBox.warning(self, "Sicherheitswarnung",
                                           f"Das Passwort konnte nicht sicher gespeichert werden: {str(e)}\n"
                                           "Ihre Anmeldedaten wurden nicht gespeichert.")
                        self.save_credentials.setChecked(False)
            else:
                # Beim Deaktivieren der Option den Username aus QSettings entfernen
                settings.remove("username")
                
                # Optional: Passwort aus dem Keyring entfernen
                old_username = settings.value("username", "")
                if old_username:
                    try:
                        keyring.delete_password(KEYRING_SERVICE, old_username)
                    except:
                        # Ignorieren falls kein Passwort gespeichert war
                        pass
            
            # Andere Einstellungen speichern
            settings.setValue("save_credentials", self.save_credentials.isChecked())
            settings.setValue("expiry_days", self.expiry_input.value())
        
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Einstellungen konnten nicht gespeichert werden: {str(e)}")

    def update_status(self, message):
        self.status_display.append(message)
        # Scroll to bottom
        scrollbar = self.status_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def set_ical_url(self, url, expires_in=None):
        self.ical_url = url
        self.ical_link_display.setText(url)
        self.copy_link_button.setEnabled(True)
        self.open_link_button.setEnabled(True)
        if expires_in:
            self.statusBar().showMessage(f"Link gültig für {expires_in}")

    def get_credentials(self):
        return {
            "username": self.username_input.text(),
            "password": self.password_input.text(),
            "expiry_days": self.expiry_input.value()
        }

    def closeEvent(self, event):
        self.save_settings()
        event.accept()
