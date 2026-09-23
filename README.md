### Bildanalyse & Bereinigung – Bildarchiv-Workflow & HTML-Dokumentation

Dieses Projekt bietet eine hocheffiziente, ressourcenschonende Pipeline zur Bereinigung, Strukturierung und interaktiven visuellen Aufbereitung umfangreicher Bildarchive. Durch gezielte Filterung werden redundante Systemdateien sowie Konvertierungsduplikate eliminiert, Speicherplatz geschont und der Bildbestand über eine leichtgewichtige, offlinefähige Web-Applikation inklusive Metadaten-Inspektor durchsuchbar gemacht.

---

### Inhaltsverzeichnis
- [Kernfunktionen](#kernfunktionen)
- [Systemarchitektur & Komponenten](#systemarchitektur--komponenten)
- [Voraussetzungen & Installation](#voraussetzungen--installation)
- [Bedienung & CLI-Referenz](#bedienung--cli-referenz)
  - [1. Bereinigtes Kopieren (`main.py`)](#1-bereinigtes-kopieren-mainpy)
  - [2. HTML-Dokumentation generieren (`generate_doc.py`)](#2-html-dokumentation-generieren-generate_docpy)
  - [3. Kombinierter Gesamtlauf](#3-kombinierter-gesamtlauf)
- [Web-Dokumentation (`CleanedImagesHTML`)](#web-dokumentation-cleanedimageshtml)
- [Automatisierte Tests & Qualitätssicherung](#automatisierte-tests--qualit%C3%A4tssicherung)
- [Praktischer Nutzen & Performance-Optimierung](#praktischer-nutzen--performance-optimierung)

---

### Kernfunktionen

#### 1. Bereinigtes & strukturerhaltendes Kopieren
- **Strikte Pfadtreue:** Rekonstruiert die gesamte relative Verzeichnisstruktur 1:1 im Zielverzeichnis.
- **Rausch- und Müllfilter:**
  - Schließt automatisch alle Dateien und Ordner aus, die mit einem Punkt (`.`) beginnen (z. B. macOS `.DS_Store`, AppleDouble-Dateien `._*`, temporäre Systemordner).
  - Ignoriert sämtliche `Converted`-Unterverzeichnisse (z. B. `Converted`, `Converted PS`, `converted PS`).
- **Dateityp-Prüfung:** Standardmäßig werden gezielt Bilddateien (`.jpg`, `.jpeg`, `.png`, `.tiff`, `.webp`, `.raw`, `.dng` etc.) erfasst.
- **Sicherheits- & Kontrollmodi:** Trockenlauf (`--dry-run`) zur risikofreien Vorabprüfung sowie intelligente Duplikaterkennung bei gleicher Dateigröße.

#### 2. Interaktive HTML-Bildergalerie & Metadaten-Dokumentation
- **Autonome Web-Applikation:** Funktioniert direkt per Doppelklick im Browser ohne Webserver (`file://`-kompatibel).
- **Vollständige EXIF-Extraktion:** Liest Kamerahersteller, Kameramodell, Objektiv, Belichtungszeit, Blende, ISO, Brennweite, Blitz, Weißabgleich, Farbraum, Copyright sowie EXIF-Rohdaten aus.
- **Strukturierte Navigation:**
  - Aufklappbarer Verzeichnisbaum mit Bildzählern für jeden Knoten.
  - Interaktive Galerieansicht (Raster- und Tabellenmodus).
  - Volltextsuche über Dateinamen und Metadaten sowie Filter nach Kamera und Aufnahmejahr.
- **Optimierte Vorschau (Thumbnails):** Multiprocessing-Erzeugung skalierter Web-Thumbnails (LANCZOS, 480 px, EXIF-Ausrichtungskorrektur). Reduziert das Ladevolumen typischerweise von mehreren Gigabyte auf wenige Megabyte für flüssiges Durchsuchen.
- **Detail-Modal & Export:** Großansicht mit Zoom, aufbereiteter Metadatenanzeige und JSON-Export.

---

### Systemarchitektur & Komponenten

```
AnalyzeImages/
├── main.py               # Zentraler CLI-Einstiegspunkt für Kopiervorgang & Pipeline
├── generate_doc.py       # Engine für Metadaten-Extraktion, Thumbnails & Web-Assets
├── test_main.py          # Automatisierte Unit-Tests für Kopiermechanik & Filter
├── test_generate_doc.py  # Automatisierte Tests für Metadaten, Baumstruktur & Thumbnails
├── README.md             # Projektdokumentation und Betriebshandbuch
└── .venv/                # Python Virtual Environment
```

---

### Voraussetzungen & Installation

- **Python:** Version 3.10 oder neuer
- **Erforderliche Pakete:** `Pillow` (PIL) zur Bild- und Metadatenverarbeitung

#### Installation der Abhängigkeiten
```powershell
pip install pillow
```

---

### Bedienung & CLI-Referenz

#### 1. Bereinigtes Kopieren (`main.py`)
Kopiert Bilddateien aus der Quelle in das Zielverzeichnis unter Anwendung sämtlicher Filterregeln.

Standardpfade:
- Quelle: `D:\AnalyzeImages`
- Ziel: `D:\CleanedImages`

```powershell
# Standardlauf mit Standardpfaden ausführen
python main.py

# Simulation / Trockenlauf ohne Schreiboperationen
python main.py --dry-run

# Benutzerdefinierte Quell- und Zielpfade angeben
python main.py --source "C:\Fotos\Quelle" --target "C:\Fotos\Bereinigt"

# Alle Dateien kopieren (nicht nur bekannte Bildformate)
python main.py --all-files

# Vorhandene Dateien bei gleicher Größe überschreiben
python main.py --overwrite

# Konsolenausgabe auf Zusammenfassung minimieren
python main.py --quiet
```

#### CLI-Parameter im Detail:
| Parameter | Typ | Standardwert | Beschreibung |
|---|---|---|---|
| `--source` | String | `D:\AnalyzeImages` | Pfad zum Quellverzeichnis |
| `--target` | String | `D:\CleanedImages` | Pfad zum Zielverzeichnis |
| `--dry-run` | Flag | `False` | Führt einen Trockenlauf aus (keine Schreibzugriffe) |
| `--overwrite`| Flag | `False` | Überschreibt bereits vorhandene Zieldateien gleicher Größe |
| `--all-files`| Flag | `False` | Erfasst alle gefilterten Dateien unabhängig von der Endung |
| `--quiet` | Flag | `False` | Reduziert den Konsolen-Output auf das Wesentliche |
| `--generate-doc` | Flag | `False` | Startet direkt im Anschluss die HTML-Dokumentation |
| `--doc-target` | String | `D:\CleanedImagesHTML` | Zielverzeichnis der generierten HTML-Dokumentation |

---

#### 2. HTML-Dokumentation generieren (`generate_doc.py`)
Erzeugt die vollständige Web-Dokumentation ausgehend von einem bereinigten Bildbestand.

```powershell
# Standardlauf für D:\CleanedImages -> D:\CleanedImagesHTML
python generate_doc.py

# Benutzerdefinierte Pfade
python generate_doc.py --source "C:\Fotos\Bereinigt" --target "C:\Fotos\WebDoc"

# Thumbnail-Größe (Standard: 480 px) und JPEG-Qualität (Standard: 82) anpassen
python generate_doc.py --thumb-size 600 --thumb-quality 85

# Parallele Prozesse konfigurieren (Standard: CPU-Kerne des Systems)
python generate_doc.py --workers 8
```

---

#### 3. Kombinierter Gesamtlauf
Bereinigung und Dokumentationserstellung in einem einzigen, automatisierten Durchlauf:

```powershell
python main.py --generate-doc
```

---

### Web-Dokumentation (`CleanedImagesHTML`)

Die erzeugte Dokumentation besteht aus kompakten, standardkonformen Webdateien:

- `index.html`: Responsives Anwendungsgerüst mit Sidebar, Verzeichnisbaum, Toolbar und Galerie.
- `styles.css`: Modernes, dunkles High-Contrast-Theme mit CSS Grid, Flexbox und optimierten Animationen.
- `app.js`: Dynamische Navigation, Pagination (96 Bilder pro Seite für verzögerungsfreies Rendering), Breadcrumbs, Volltextsuche und Lightbox-Steuerung.
- `data.js`: Kompaktes JSON-Datenmodell aller Bilder, Verzeichnisse und EXIF-Attribute.
- `thumbnails/`: Struktursynchron angelegte Web-Thumbnails im JPEG-Format zur schnellen Anzeige.

#### Bedienfunktionen der Benutzeroberfläche:
1. **Ordner-Navigation:** Auswahl über den Sidebar-Baum oder direkte Klicks auf Ordnerpfade in den Bildkarten.
2. **Kompaktheitsstufen:** Umschalten zwischen kleinen, mittleren und großen Kacheln oder Tabellenansicht.
3. **Filterleiste:** Sofortige Filterung nach Kamerahersteller/-modell oder Aufnahmejahr.
4. **Metadaten-Modal:** Tastaturnavigation (Pfeiltasten, Escape), EXIF-Detailtabelle und 1-Klick-Download des Rohdaten-JSON.

---

### Automatisierte Tests & Qualitätssicherung

Das Projekt verfügt über eine umfassende Testsuite mit `unittest`, die Filterregeln, Pfaddekodierungen, EXIF-Parsing und Verzeichnisberechnungen abdeckt.

#### Tests ausführen:
```powershell
python -m unittest discover
```

#### Testabdeckung:
- `test_main.py`:
  - Ausschluss von AppleDouble-Dateien (`._*`) und `.DS_Store`.
  - Erkennung und Ausschluss diverser `Converted`-Ordnerkonstellationen.
  - Wahrung verschachtelter Ordnerpfade.
  - Trockenlauf-Validierung und CLI-Parser-Prüfung.
- `test_generate_doc.py`:
  - Sichere URL-Enkodierung bei Umlauten, Sonderzeichen und Leerzeichen.
  - Korrekte Bruch- und Zahlenformatierung für Belichtungszeiten, Blenden und Brennweiten.
  - Hierarchische Baumaggregationslogik für Verzeichnispfade.
  - Multiprocessing-Thumbnail-Erstellung und EXIF-Tag-Serialisierung.

---

### Praktischer Nutzen & Performance-Optimierung

- **Minimale Ladezeiten:** Statt mehrfacher Gigabyte an Originalaufnahmen werden im Web-Viewer lediglich optimierte Vorschaudateien (ca. 40–60 kB pro Bild) geladen; das Originalbild wird erst bei expliziter Großansicht angefordert.
- **Ressourceneffiziente Parallelisierung:** Automatische Auslastung aller verfügbaren CPU-Kerne über `ProcessPoolExecutor` bei der Bildverarbeitung.
- **Autark & Zukunftsfest:** Keine externen Cloud- oder CDN-Abhängigkeiten – die Dokumentation bleibt ohne Internetverbindung uneingeschränkt nutzbar.
