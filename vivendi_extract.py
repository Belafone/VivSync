# vivendi_extract.py - Finale Version mit zuverlässiger Kalendererkennung und Headless-Modus

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException
import time
from datetime import datetime, timedelta
import re
import traceback
import json
import locale

# Config Import
try:
    from config import VIVENDI_USERNAME, VIVENDI_PASSWORD, VIVENDI_URL
except ImportError:
    print("WARNUNG: config.py nicht gefunden oder Variablen fehlen.")
    VIVENDI_USERNAME = ""
    VIVENDI_PASSWORD = ""
    VIVENDI_URL = ""

def detect_calendar_view(driver, update_status):
    """
    Erkennt die aktuelle Kalenderansicht (Woche oder Monat)
    """
    try:
        # Methode 1: URL-basierte Erkennung
        current_url = driver.current_url.lower()
        update_status(f"Aktuelle URL: {current_url}")
        
        if "/woche/" in current_url:
            update_status("Wochenansicht erkannt (via URL)")
            return "week"
        elif "/monat/" in current_url:
            update_status("Monatsansicht erkannt (via URL)")
            return "month"
        
        # Methode 2: UI-Element basierte Erkennung
        try:
            # Suche nach Wochenansicht-Button (wenn sichtbar, sind wir in Monatsansicht)
            week_buttons = driver.find_elements(By.XPATH, "//button[@aria-label='Wochenansicht']")
            for btn in week_buttons:
                if btn.is_displayed():
                    update_status("Monatsansicht erkannt (Wochenansicht-Button sichtbar)")
                    return "month"

            # Suche nach Monatsansicht-Button (wenn sichtbar, sind wir in Wochenansicht)
            month_buttons = driver.find_elements(By.XPATH, "//button[@aria-label='Monatsansicht']")
            for btn in month_buttons:
                if btn.is_displayed():
                    update_status("Wochenansicht erkannt (Monatsansicht-Button sichtbar)")
                    return "week"
                    
            # Suche nach Ansichts-Icons
            week_icons = driver.find_elements(By.XPATH, "//mat-icon[@data-mat-icon-name='calendar_view_week']")
            month_icons = driver.find_elements(By.XPATH, "//mat-icon[@data-mat-icon-name='calendar_view_month']")
            
            if any(icon.is_displayed() for icon in week_icons):
                update_status("Monatsansicht erkannt (Wochen-Icon sichtbar)")
                return "month"
            elif any(icon.is_displayed() for icon in month_icons):
                update_status("Wochenansicht erkannt (Monats-Icon sichtbar)")
                return "week"
                
        except Exception as e:
            update_status(f"Fehler bei UI-Element-Erkennung: {str(e)}")
        
        # Methode 3: Struktur-basierte Erkennung
        try:
            # Wochenansicht hat typischerweise Tagesansichten für alle Wochentage
            day_columns = driver.find_elements(By.XPATH, "//div[contains(@class, 'day-column')]")
            if len(day_columns) >= 5:  # Wochenansicht hat mindestens 5 Tagesansichten
                update_status("Wochenansicht erkannt (Tagesansichten gefunden)")
                return "week"
                
            # Prüfen auf Monatsansicht-Tabelle
            month_grid = driver.find_elements(By.XPATH, "//table[contains(@class, 'calendar')]")
            if len(month_grid) > 0:
                update_status("Monatsansicht erkannt (Monats-Grid gefunden)")
                return "month"
        except Exception as e:
            update_status(f"Fehler bei Struktur-Erkennung: {str(e)}")
            
    except Exception as e:
        update_status(f"Fehler bei Ansichtserkennung: {str(e)}")
    
    update_status("Ansicht konnte nicht eindeutig erkannt werden")
    return "unknown"

def switch_to_month_view(driver, update_status):
    """
    Wechselt zur Monatsansicht mittels verschiedener Strategien
    """
    try:
        # Strategie 1: Direkter Klick auf den Monatsansicht-Button
        month_buttons = driver.find_elements(By.XPATH, "//button[@aria-label='Monatsansicht']")
        for btn in month_buttons:
            try:
                if btn.is_displayed():
                    update_status("Klicke auf Monatsansicht-Button...")
                    btn.click()
                    time.sleep(2)
                    return True
            except Exception as e:
                update_status(f"Fehler beim Klicken des Monatsansicht-Buttons: {str(e)}")
        
        # Strategie 2: Klick auf Monatsansicht-Icon
        month_icon_buttons = driver.find_elements(By.XPATH, 
            "//button[.//mat-icon[@data-mat-icon-name='calendar_view_month']]")
        for btn in month_icon_buttons:
            try:
                if btn.is_displayed():
                    update_status("Klicke auf Monatsansicht-Icon-Button...")
                    btn.click()
                    time.sleep(2)
                    return True
            except Exception as e:
                update_status(f"Fehler beim Klicken des Monatsansicht-Icon-Buttons: {str(e)}")
        
        # Strategie 3: URL-Manipulation
        current_url = driver.current_url
        if "/woche/" in current_url:
            month_url = current_url.replace("/woche/", "/monat/")
            update_status(f"Wechsle zu Monatsansicht via URL: {month_url}")
            driver.get(month_url)
            time.sleep(2)
            return True
        
        # Strategie 4: JavaScript-Ausführung
        # Dies kann helfen, wenn der Button nicht direkt klickbar ist
        try:
            script = """
            // Finde alle Buttons und klicke den, der mit Monatsansicht zu tun hat
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var btn = buttons[i];
                if (btn.textContent.includes('Monat') || 
                    (btn.getAttribute('aria-label') && btn.getAttribute('aria-label').includes('Monat'))) {
                    btn.click();
                    return true;
                }
            }
            return false;
            """
            result = driver.execute_script(script)
            if result:
                update_status("Zu Monatsansicht gewechselt (via JavaScript)")
                time.sleep(2)
                return True
        except Exception as js_err:
            update_status(f"JavaScript-Ausführung fehlgeschlagen: {str(js_err)}")
        
        # Strategie 5: Tab-Navigation (als letzte Möglichkeit)
        try:
            update_status("Versuche Tab-Navigation...")
            # Fokus auf ein bekanntes Element setzen
            main_element = driver.find_element(By.XPATH, "//body")
            main_element.click()
            
            # 14x Tab-Taste drücken, dann Enter
            active_element = driver.switch_to.active_element
            for i in range(14):
                active_element.send_keys(Keys.TAB)
                time.sleep(0.1)
            
            driver.switch_to.active_element.send_keys(Keys.RETURN)
            update_status("Tab-Navigation durchgeführt")
            time.sleep(2)
            return True
        except Exception as tab_err:
            update_status(f"Tab-Navigation fehlgeschlagen: {str(tab_err)}")
        
        update_status("Konnte nicht zur Monatsansicht wechseln!")
        return False
        
    except Exception as e:
        update_status(f"Genereller Fehler beim Ansichtswechsel: {str(e)}")
        return False

def check_and_set_month_view(driver, update_status):
    """
    Prüft die aktuelle Kalenderansicht und wechselt bei Bedarf zur Monatsansicht.
    """
    try:
        # Längere Wartezeit für vollständiges Laden des Kalenders
        update_status("Warte auf vollständiges Laden des Kalenders...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//body")))
        time.sleep(3)  # Extra Wartezeit für Stabilität
        
        # Erkennung der aktuellen Ansicht
        update_status("Prüfe aktuelle Kalenderansicht...")
        current_view = detect_calendar_view(driver, update_status)
        
        # Wenn in Wochenansicht, zur Monatsansicht wechseln
        if current_view == "week":
            update_status("Wochenansicht erkannt, wechsle zu Monatsansicht...")
            success = switch_to_month_view(driver, update_status)
            if success:
                update_status("Erfolgreicher Wechsel zur Monatsansicht")
            else:
                update_status("Wechsel zur Monatsansicht nicht möglich, fahre mit aktueller Ansicht fort")
        elif current_view == "month":
            update_status("Bereits in Monatsansicht, keine Änderung nötig")
        else:
            update_status("Ansicht nicht erkannt, fahre mit Extraktion fort")
    
    except Exception as e:
        update_status(f"Fehler bei Kalenderansichtsprüfung: {str(e)}")
    
    # In jedem Fall mit der Extraktion fortfahren
    update_status("Fahre mit Extraktion fort...")

def extract_dienste(username=None, password=None, use_windows_login=True, status_callback=None, progress_callback=None):
    """
    Extrahiert Dienste aus Vivendi (aktueller + nächster Monat),
    führt Dienst und Position pro Tag zusammen.
    """
    def update_status(message):
        print(message)
        if status_callback:
            status_callback(message)

    def update_progress(value):
        if progress_callback:
            progress_callback(value)

    update_status("=== STARTE BROWSER ===")
    update_progress(10)

    # Chrome Optionen
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--headless')  # Headless-Modus aktiviert

    driver = None

    try:
        # WebDriver Init
        try:
            update_status("Versuche ChromeDriver automatisch zu verwalten...")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            update_status("ChromeDriver gestartet.")
        except Exception as driver_err:
            update_status(f"FEHLER beim ChromeDriver-Start: {driver_err}")
            return []

        # Credentials und URL
        vivendi_username = username if username else VIVENDI_USERNAME
        vivendi_password = password if password else VIVENDI_PASSWORD
        vivendi_url = VIVENDI_URL

        if not vivendi_url:
            update_status("FEHLER: Keine Vivendi URL!")
            return []

        if not vivendi_username:
            update_status("WARNUNG: Kein Benutzername!")

        # Login Prozess
        update_status(f"\nÖffne Vivendi-Seite: {vivendi_url}")
        driver.get(vivendi_url)
        update_status("Warte auf Seitenaufbau...")
        update_progress(20)

        update_status("\n=== BENUTZERFELD ===")
        username_xpath = "//input[contains(@aria-label, 'Benutzer') or contains(@id, 'Benutzer') or contains(@name, 'user') or @type='text'][1]"
        try:
            username_field = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, username_xpath)))
            update_status("➔ Benutzerfeld gefunden")
            username_field.clear()
            username_field.send_keys(vivendi_username)
            time.sleep(0.5)
        except Exception as user_ex:
            update_status(f"FEHLER Benutzerfeld: {user_ex}")
            traceback.print_exc()
            return []

        update_status("\n=== PASSWORTFELD ===")
        password_xpath = "//input[@type='password' or contains(@aria-label, 'Kennwort') or contains(@id, 'Kennwort') or contains(@name, 'pass')]"
        try:
            password_field = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, password_xpath)))
            update_status("➔ Passwortfeld gefunden")
            password_field.clear()
            password_field.send_keys(vivendi_password)
            time.sleep(0.5)
        except Exception as pass_ex:
            update_status(f"FEHLER Passwortfeld: {pass_ex}")
            traceback.print_exc()
            return []

        if use_windows_login:
            update_status("\n=== WINDOWS LOGIN (TAB) ===")
            password_field.send_keys(Keys.TAB)
            time.sleep(0.5)
            try:
                driver.switch_to.active_element.send_keys(Keys.TAB)
                time.sleep(0.5)
                driver.switch_to.active_element.send_keys(Keys.RETURN)
            except Exception as tab_err:
                update_status(f"WARNUNG Tab-Nav: {tab_err}. Fallback: Enter.")
                password_field.send_keys(Keys.RETURN)
        else:
            update_status("Standard-Login (Enter)...")
            password_field.send_keys(Keys.RETURN)

        update_status("\n=== LOGIN-VERSUCH ===")
        update_status("Warte auf Login (max 30s)...")
        update_progress(30)

        login_success_indicator_xpath = "//pep-calendar | //*[contains(text(),'Dienstplan')] | //*[contains(@class, 'dienstplan-container')]"
        try:
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH, login_success_indicator_xpath)))
            update_status("Login erfolgreich.")
        except Exception as login_wait_err:
            update_status(f"WARNUNG Login: {login_wait_err}")

        # Prüfen und zur Monatsansicht wechseln
        update_status("\n=== KALENDERANSICHT PRÜFEN ===")
        check_and_set_month_view(driver, update_status)
        
        # --- Dienste Aktueller Monat ---
        update_status("\n=== DIENSTE AKTUELLER MONAT ===")
        update_progress(40)
        time.sleep(5)
        dienst_elemente_aktuell = driver.find_elements(By.XPATH, "//pep-dienstliste-dienst")
        update_status(f"Elemente (Aktuell): {len(dienst_elemente_aktuell)}")
        dienste_aktuell = extract_dienste_from_elements(dienst_elemente_aktuell, driver, update_status)
        update_progress(60)

        # --- Dienste Nächster Monat ---
        update_status("\n=== NAVIGIERE ZUM FOLGEMONAT ===")
        dienste_naechster = []
        try:
            next_month_xpath = "//button[contains(@aria-label, 'Nächster Monat')] | //button[descendant::mat-icon[@data-mat-icon-name='chevron_right']]"
            next_month_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, next_month_xpath)))
            update_status("➔ Button Weiter gefunden: " + next_month_xpath)
            next_month_button.click()
            update_status("Warte auf Folgemonat...")
            time.sleep(5)
            update_progress(70)

            update_status("\n=== DIENSTE FOLGEMONAT ===")
            time.sleep(5)
            dienst_elemente_naechster = driver.find_elements(By.XPATH, "//pep-dienstliste-dienst")
            update_status(f"Elemente (Nächster): {len(dienst_elemente_naechster)}")
            dienste_naechster = extract_dienste_from_elements(dienst_elemente_naechster, driver, update_status)
            update_progress(90)
        except Exception as e:
            update_status(f"FEHLER Folgemonat: {str(e)}")
            traceback.print_exc()
            update_status("Fahre nur mit akt. Monat fort.")

        # --- NEUE LOGIK: Kombinieren und Zusammenführen pro Tag ---
        alle_dienste_roh = dienste_aktuell + dienste_naechster
        update_status("\n=== BEREINIGE UND FÜHRE ZUSAMMEN ===")
        update_status(f"Roh-Anzahl Dienste (aus beiden Monaten): {len(alle_dienste_roh)}")

        # Schritt 1: Gruppieren nach Datum
        grouped_by_date = {}
        for roh_dienst in alle_dienste_roh:
            datum = roh_dienst.get('datum')
            if not datum or datum == "DATUM_UNBEKANNT":
                continue  # Ungültige Einträge ignorieren
            if datum not in grouped_by_date:
                grouped_by_date[datum] = []
            grouped_by_date[datum].append(roh_dienst)
        update_status(f"Anzahl Tage mit Einträgen: {len(grouped_by_date)}")

        # Schritt 2: Pro Datum zusammenführen
        merged_dienste_final = []
        for datum in sorted(grouped_by_date.keys()):  # Sortiere nach Datum
            eintraege_fuer_tag = grouped_by_date[datum]
            finaler_eintrag = {
                'datum': datum,
                'dienst': '',
                'position': '',
                'dienstzeit': '',
                'username': vivendi_username  # Username gleich setzen
            }

            positionen_gefunden = []  # Liste für Positionen/Kommentare
            # Finde den Haupteintrag (mit Dienstcode und Zeit) und die Position(en)
            for eintrag in eintraege_fuer_tag:
                if eintrag.get('dienst'):  # Wenn dieser Eintrag einen Dienstcode hat
                    if finaler_eintrag['dienst']:  # Sollte nicht passieren, aber falls doch
                        update_status(f"WARNUNG: Mehrere Dienstcodes ({finaler_eintrag['dienst']}, {eintrag['dienst']}) für {datum} gefunden. Verwende ersten.")
                    else:
                        finaler_eintrag['dienst'] = eintrag['dienst']
                    if eintrag.get('dienstzeit'):  # Nimm die Zeit vom Haupteintrag
                        finaler_eintrag['dienstzeit'] = eintrag['dienstzeit']
                if eintrag.get('position'):  # Wenn dieser Eintrag eine Position hat
                    positionen_gefunden.append(eintrag['position'])

            # Füge die gefundenen Positionen zusammen (z.B. mit Komma getrennt)
            finaler_eintrag['position'] = ", ".join(filter(None, positionen_gefunden))  # Filtert leere Strings raus

            # Füge den zusammengeführten Eintrag zur finalen Liste hinzu
            if finaler_eintrag['dienst'] or finaler_eintrag['position']:
                merged_dienste_final.append(finaler_eintrag)
            else:  # Log, wenn ein Tag leer bleibt (sollte selten sein)
                update_status(f"Info: Kein Dienst oder Position für {datum} nach Zusammenführung, überspringe.")

        update_status(f"Anzahl Dienste nach Zusammenführung: {len(merged_dienste_final)}")

        # --- Ausgabe ---
        update_status("\n=== FINALE DIENSTLISTE (ZUSAMMENGEFÜHRT) ===")
        if not merged_dienste_final:
            update_status("Keine gültigen Dienste gefunden oder extrahiert.")
        else:
            for dienst in merged_dienste_final:
                dienstzeit_info = f"({dienst['dienstzeit']})" if dienst['dienstzeit'] else ""
                try:
                    display_datum = datetime.strptime(dienst['datum'], "%Y-%m-%d").strftime("%d.%m.%Y")
                except ValueError:
                    display_datum = dienst['datum']
                # Zeige Dienst und Position im Log
                update_status(f"{display_datum}: {dienst['dienst']} - {dienst['position']} {dienstzeit_info}")

            update_status(f"\nInsgesamt {len(merged_dienste_final)} finale Diensteinträge extrahiert.")
        update_progress(100)
        return merged_dienste_final  # Gib die zusammengeführte Liste zurück

    # Restliche Fehlerbehandlung und finally-Block
    except Exception as e:
        update_status(f"\n❌ SCHWERER FEHLER im Hauptprozess: {str(e)}")
        traceback.print_exc()
        update_progress(100)
        return []
    finally:
        if driver:
            try:
                driver.quit()
                update_status("Browser geschlossen.")
            except Exception as quit_err:
                update_status(f"Fehler beim Schließen: {quit_err}")

def extract_dienste_from_elements(dienst_elemente, driver, status_log_func):
    """
    Extrahiert Dienste aus den gefundenen Selenium-Elementen.
    Liefert eine Liste von Dictionaries, die *entweder* 'dienst' *oder* 'position' enthalten können.
    """
    dienste = []
    valid_positions = ["Oben", "Unten", "Angebot", "Ingebo"]
    status_log_func(f"--- Starte Extraktion aus {len(dienst_elemente)} Elementen ---")

    for i, elem in enumerate(dienst_elemente):
        status_log_func(f"\n--- Verarbeite Element {i+1}/{len(dienst_elemente)} ---")
        try:  # --- try-Block für StaleElement ---
            # --- Datum extrahieren ---
            datum_container_xpath = "./ancestor::div[contains(@aria-label, ' am ')][1]"
            datum_iso = "DATUM_UNBEKANNT"
            datum_obj = None
            try:
                parent_item = elem.find_element(By.XPATH, datum_container_xpath)
                datum_aria_label = parent_item.get_attribute('aria-label') or ""
                status_log_func(f"Eltern-Label: '{datum_aria_label}'")
                if ' am ' in datum_aria_label:
                    datum_str_raw = datum_aria_label.split(' am ')[-1].strip()
                    status_log_func(f"Roh-Datum: '{datum_str_raw}'")
                    locale_set = False
                    original_locale = locale.getlocale(locale.LC_TIME)
                    try:  # Locale setzen versuchen
                        locale.setlocale(locale.LC_TIME, 'de_DE.UTF-8')
                        locale_set = True
                    except locale.Error:
                        try:
                            locale.setlocale(locale.LC_TIME, 'German_Germany.1252')
                            locale_set = True
                        except locale.Error:
                            pass  # Ignoriere Fehler, wenn auch Windows-Locale nicht geht

                    # Formate prüfen
                    possible_formats = ["%Y-%m-%d", "%d.%m.%Y", "%d. %B %Y"]
                    for fmt in possible_formats:
                        try:
                            datum_obj = datetime.strptime(datum_str_raw, fmt)
                            status_log_func(f"Datum geparst ('{fmt}').")
                            datum_iso = datum_obj.strftime("%Y-%m-%d")
                            break
                        except:
                            continue

                    # Locale zurücksetzen
                    if locale_set:
                        try:
                            locale.setlocale(locale.LC_TIME, original_locale)
                        except:
                            pass  # Fehler beim Zurücksetzen ignorieren

                    if datum_iso == "DATUM_UNBEKANNT":
                        status_log_func(f"WARNUNG: Datum nicht geparst.")
                else:
                    status_log_func(f"WARNUNG: ' am ' fehlt.")
            except StaleElementReferenceException:
                status_log_func(f"WARNUNG: Eltern-Div {i+1} 'stale'. Überspringe.")
                continue

            # Text/Dienstcode/Position extrahieren
            dienst_text = ""
            try:
                text_element = elem.find_element(By.XPATH, ".//div[contains(@class, 'dienstliste-dienst__icon')] | .//span[contains(@class, 'dienst-text')] | .")
                dienst_text = text_element.text.strip()
            except StaleElementReferenceException:
                status_log_func(f"WARNUNG: Text {i+1} 'stale'. Fallback...")
                try:
                    dienst_text = elem.text.strip()
                except StaleElementReferenceException:
                    status_log_func(f"WARNUNG: Fallback Text {i+1} 'stale'. Überspringe.")
                    continue
            except Exception:
                try:
                    dienst_text = elem.text.strip()  # Fallback
                except StaleElementReferenceException:
                    status_log_func(f"WARNUNG: Fallback Text {i+1} 'stale'. Überspringe.")
                    continue

            status_log_func(f"Element Text: '{dienst_text}'")
            try:
                aria_label = elem.get_attribute('aria-label') or ""
                status_log_func(f"Dienst aria-label: '{aria_label}'")
            except Exception:
                status_log_func(f"WARNUNG: Konnte aria-label nicht extrahieren.")
                aria_label = ""

            dienst_code = ""
            position = ""
            dienstzeit = ""

            if dienst_text in valid_positions:
                position = dienst_text
                status_log_func(f"Als Position erkannt: {position}")
            elif dienst_text:
                dienst_code = dienst_text
                status_log_func(f"Als Dienstcode erkannt: {dienst_code}")
            else:
                # Versuche Dienstcode aus aria-label zu extrahieren
                label_match = re.search(r'Ist-Dienst:\s*(\S+)', aria_label)
                if label_match:
                    dienst_code = label_match.group(1).strip()
                    status_log_func(f"Dienstcode aus aria-label extrahiert: {dienst_code}")
                else:
                    status_log_func("WARNUNG: Kein Text im Element und kein Dienstcode im aria-label gefunden.")

            # Zeitberechnung, falls Dienstcode vorhanden und Zeit im aria-label
            if dienst_code and "Uhr" in aria_label:
                status_log_func("--- Starte Zeitberechnung ---")
                try:
                    # Startzeit extrahieren
                    start_time_match = re.search(r'(\d{1,2}:\d{2})\s*Uhr', aria_label, re.IGNORECASE)
                    if start_time_match:
                        start_time_str = start_time_match.group(1)
                        # Führende Null hinzufügen, falls nötig
                        if ':' in start_time_str and len(start_time_str.split(':')[0]) == 1:
                            start_time_str = "0" + start_time_str
                        status_log_func(f"Startzeit extrahiert: {start_time_str}")

                        # Dauer extrahieren
                        duration_match = re.search(r'(\d+([.,]\d+)?)\s*h', aria_label, re.IGNORECASE)
                        if duration_match:
                            duration_str_raw = duration_match.group(1)
                            duration_str_cleaned = duration_str_raw.replace(',', '.')
                            status_log_func(f"Dauer extrahiert (roh): '{duration_str_raw}', (bereinigt): '{duration_str_cleaned}'")
                            try:
                                duration_float = float(duration_str_cleaned)
                                status_log_func(f"Dauer als float: {duration_float}")
                                hours = int(duration_float)
                                minutes = int(round((duration_float - hours) * 60))
                                status_log_func(f"Berechnete Dauer: {hours} Stunden, {minutes} Minuten")
                                try:
                                    start_hour, start_minute = map(int, start_time_str.split(':'))
                                except ValueError as time_split_err:
                                    status_log_func(f"FEHLER beim Teilen der Startzeit '{start_time_str}': {time_split_err}")
                                    raise

                                # Verwende das geparste Datum für die Berechnung
                                if not datum_obj:
                                    status_log_func("FEHLER: Kein gültiges Datumsobjekt für Zeitberechnung vorhanden.")
                                    raise ValueError("Datumsobjekt fehlt")

                                start_dt_naive = datum_obj.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
                                status_log_func(f"Startzeit als datetime (naiv): {start_dt_naive}")
                                end_dt_naive = start_dt_naive + timedelta(hours=hours, minutes=minutes)
                                status_log_func(f"Endzeit als datetime (naiv, nach timedelta): {end_dt_naive}")
                                end_time_str = end_dt_naive.strftime("%H:%M")
                                status_log_func(f"Endzeit formatiert: {end_time_str}")
                                dienstzeit = f"{start_time_str} - {end_time_str}"
                                status_log_func(f"-> Berechnete Dienstzeit: {dienstzeit}")
                            except ValueError as float_conv_err:
                                status_log_func(f"FEHLER bei Konvertierung/Berechnung Dauer/Zeit: {float_conv_err}")
                        else:
                            status_log_func("Keine Dauer (x.xh) im aria-label gefunden.")
                    else:
                        status_log_func("Keine Startzeit (HH:MM Uhr) im aria-label gefunden.")
                except Exception as e_time:
                    status_log_func(f"FEHLER während der Zeitextraktion/-berechnung: {str(e_time)}")
                    traceback.print_exc()
                status_log_func("--- Ende Zeitberechnung ---")
            elif dienst_code:
                status_log_func("Keine 'Uhr' im aria-label gefunden, keine Zeitberechnung für diesen Dienst.")

            # Hinzufügen zur Liste
            if datum_iso != "DATUM_UNBEKANNT" and (dienst_code or position):
                dienste.append({
                    'datum': datum_iso,
                    'dienst': dienst_code,
                    'position': position,
                    'dienstzeit': dienstzeit
                })
                status_log_func("-> Eintrag zur Liste hinzugefügt.")
            elif datum_iso == "DATUM_UNBEKANNT":
                status_log_func(f"Überspringe Element {i+1}, da Datum nicht geparst werden konnte.")
            else:
                status_log_func(f"Überspringe Element {i+1}, da weder Dienstcode noch Position erkannt wurde.")

        except Exception as e_elem:
            status_log_func(f"FEHLER bei der Verarbeitung von Element {i+1}: {str(e_elem)}")
            traceback.print_exc()  # Detaillierter Fehler für dieses Element

    status_log_func(f"--- Extraktion aus Elementen beendet. {len(dienste)} Einträge erstellt. ---")
    return dienste
