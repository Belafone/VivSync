# VivSync

<img src="logo.png" width="200" alt="VivSync Logo" style="margin: 20px auto; display: block;">

VivSync ist ein Open-Source-Tool zur automatischen Synchronisation von Vivendi-Dienstplänen mit gängigen Kalender-Apps. Die Anwendung wurde entwickelt, weil die integrierte Kalenderfunktion in Vivendi PEP derzeit deaktiviert ist.

## ✨ Features

- 🔄 **Automatische Extraktion** der Dienstpläne direkt aus dem Vivendi-Portal
- 💾 **Lokaler Export** als iCal-Datei für den Import in Outlook, Google Kalender, etc.
- 🌐 **Online-Synchronisation** über abonnierbare Kalender-Links
- 🔒 **Sichere Speicherung** der Anmeldedaten (verschlüsselt mit Systemkeyring)
- ⏱️ **Konfigurierbare Gültigkeitsdauer** für Kalender-Links (1-365 Tage)
- 🔔 **Automatische Updates** durch integrierte Update-Prüfung

## 🚀 Schnellstart

1. [VivSync herunterladen](https://vivsync.com/downloads/VivSync.exe)
2. Anwendung starten (keine Installation erforderlich)
3. Vivendi-Anmeldedaten eingeben
4. Synchronisationsmethode wählen:
   - "Kalender speichern" für lokale iCal-Datei
   - "Mit Online-Kalender synchronisieren" für kontinuierliche Updates

## 📋 Voraussetzungen

- Windows 10/11
- Google Chrome (wird für die Extraktion verwendet)
- Internetverbindung
- Gültige Vivendi-Zugangsdaten

## 🔧 Technischer Hintergrund

VivSync nutzt:
- Python mit Selenium für die Extraktion
- PyQt5 für die Benutzeroberfläche
- Flask für den Synchronisationsserver
- Keyring für die sichere Anmeldedatenspeicherung

Das Projekt besteht aus zwei Hauptkomponenten:
1. **Client**: Windows-Anwendung zur Dienstplan-Extraktion
2. **Server**: Flask-Anwendung zur Bereitstellung der Kalender-Feeds

## 📱 Kalender-Apps Kompatibilität

VivSync funktioniert mit allen gängigen Kalender-Anwendungen:
- Google Kalender
- Apple Kalender
- Microsoft Outlook
- Thunderbird Lightning
- Und allen anderen Apps, die iCal/ICS unterstützen

## ⚠️ Hinweis

VivSync ist ein Community-Projekt und steht in keiner Verbindung zum Hersteller der Vivendi-Software. Die Anwendung wurde entwickelt, um Mitarbeitern die Arbeit zu erleichtern, bis die integrierte Kalenderfunktion wieder verfügbar ist.

## 📄 Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE).

## 🤝 Unterstützung & Kontakt

Für Fragen, Problemmeldungen oder Verbesserungsvorschläge:
- [GitHub Issue erstellen](https://github.com/IhrUsername/VivSync/issues)
- Server- und Domain-Kosten werden durch freiwillige Unterstützung gedeckt
