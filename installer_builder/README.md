# Simple Windows Installer Builder

Python 3.12+ und PySide6, ohne externes Installer-Framework. Der Builder läuft auch
unter Linux/macOS; Desktop-Verknüpfungen benötigen Windows und dessen mitgeliefertes
Windows PowerShell sowie `WScript.Shell`. Python und PySide6 müssen auf dem
Installationsrechner vorhanden sein. Version 1 erzeugt Datenpakete, keine Standalone-EXE.

## Schnellstart unter Windows

Im Repository-Verzeichnis, mit PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r installer_builder\requirements.txt
.\.venv\Scripts\python.exe installer_builder\build.py installer_builder\examples\example_project
.\.venv\Scripts\python.exe installer_builder\src\main.py installer_builder\packages\GameXY-1.0.installer
```

Ohne Paketargument öffnet die GUI die Paketauswahl:

```powershell
.\.venv\Scripts\python.exe installer_builder\src\main.py
```

Paket auswählen, Informationen prüfen, Zielordner und Spielername eingeben,
Installation bestätigen. Danach erscheinen Fortschritt, aktueller Kopiervorgang
und entweder eine Fehlermeldung oder die Abschlussseite mit erstellten Verknüpfungen.
Die Installation läuft in einem Hintergrundthread.

Der Beispielstarter `start.cmd` ist eine harmlose Windows-Batchdatei. Für ein echtes
Projekt durch die eigene EXE ersetzen und `link.txt` entsprechend anpassen.

## Struktur

```text
installer_builder/
  src/
    main.py
    gui/{main_window.py,widgets.py}
    installer/{engine.py,package.py,file_copy.py,shortcuts.py,generators.py}
    config/installer_schema.py
  packages/
  examples/example_project/
  tests/
  requirements.txt
  build.py
```

## Projekt konfigurieren

```text
mein_projekt/
  installer.json
  link.txt
  src/GameXY/Game.exe
  src/GameXY/data/...
  User/Documents/config.ini
  User/AppData/settings.json
  templates/config.ini.template
```

`installer.json`:

```json
{
  "name": "GameXY",
  "version": "1.0",
  "publisher": "Example",
  "default_install_path": "C:/Games/GameXY",
  "desktop_shortcut": true,
  "required_parameters": [
    {"name": "PLAYER_NAME", "description": "Spielername"}
  ]
}
```

- `name`, `version` und `default_install_path` sind Pflichtfelder.
- `publisher` ist optional, `desktop_shortcut` standardmäßig `true`.
- Parameternamen sind eindeutig und folgen dem Muster `[A-Z][A-Z0-9_]*`.
- Ein einzelner Unterordner in `src/` wird als Projektwurzel behandelt:
  `src/GameXY/Game.exe` → `<Installationsordner>/Game.exe`.
  Bei mehreren Einträgen bleibt die Struktur unter `src/` erhalten.
- `User/` wird relativ zum automatisch ermittelten Benutzerprofil kopiert:
  `User/Documents/config.ini` → `%USERPROFILE%/Documents/config.ini`.
  Diese Pfade sind bewusst profilrelativ; umgeleitete Dokumentenordner werden
  nicht separat ermittelt.
- Der tatsächliche Desktopordner wird über die Windows-Benutzerregistrierung
  ermittelt, auch bei Desktop-Umleitung zu OneDrive.
- Leere Ordner werden nicht verpackt. Dateien dürfen keine symbolischen Links sein.

### Desktop-Verknüpfungen

`link.txt` enthält pro Zeile ein Ziel und dessen unveränderte Argumente:

```text
./src/GameXY/Game.exe;-nosteam
```

Ziele müssen vorhandene Dateien unter der `src`-Projektwurzel sein. Die Verknüpfung
heißt `GameXY.lnk`; bei mehreren Zeilen `GameXY-1.lnk`, `GameXY-2.lnk` usw.
Ihr Arbeitsverzeichnis ist der Ordner der installierten Zieldatei.
Optional kann `installer.json` `"shortcut_icon": "src/GameXY/icon.ico"` enthalten.
Mit `"desktop_shortcut": false` oder ohne `link.txt` werden keine Links erstellt.
Der Installer startet die verknüpfte Anwendung nicht.

### Templates

`templates/config.ini.template`:

```ini
username={{PLAYER_NAME}}
```

Erzeugt `<Installationsordner>/config.ini` mit dem in der GUI eingegebenen Wert.
`templates/User/Documents/player.ini.template` erzeugt entsprechend eine Datei
im Benutzerprofil. Alle Dateien unter `templates/` müssen UTF-8-Textdateien mit
der Endung `.template` sein. Unterordner bleiben erhalten. Platzhalter werden
einmal ersetzt; es gibt keine Auswertung von Python oder anderen Ausdrücken.
Fehlende Parameter und doppelte Dateiziele werden vor dem Kopieren abgewiesen.
Werte werden wörtlich eingefügt; projektabhängige Formatvalidierung kann später
in einem eigenen Generator ergänzt werden.

## Builder und Paketformat

```powershell
.\.venv\Scripts\python.exe installer_builder\build.py mein_projekt --output installer_builder\packages
```

Erzeugt `<name>-<version>.installer`: ein ZIP-Container mit

```text
manifest.json   # format_version=1, config, source_root, shortcuts
payload.zip     # komprimierte Dateien aus src/, User/ und templates/
optional/       # für spätere Erweiterungen reserviert; derzeit nicht ausgewertet
```

Das Manifest entsteht aus `installer.json` und `link.txt`. Die Installationsdaten
bleiben außerhalb der kleinen Installer-Anwendung. Dateien außerhalb der drei
Quellordner werden nicht als Payload verpackt. Der Builder benötigt kein Qt,
verwendet dieselbe Paketvalidierung wie der Installer und ersetzt Ausgabepakete
erst nach erfolgreicher Erstellung.

## Sicherheit und Grenzen der ersten Version

Nur eigene oder vertrauenswürdige Pakete installieren: Pakete sind nicht signiert
und können Dateien in den freigegebenen Zielordnern überschreiben. Die GUI fragt
vorher nach Bestätigung. Bestehende Dateien werden ersetzt, andere bleiben bestehen.
Es gibt noch kein Backup, Rollback, Deinstallationsprogramm, UAC-/Admin-Modus oder
Abbruch laufender Installationen. Bei einem Laufzeitfehler können Dateien bereits
kopiert sein; die GUI weist darauf hin.

ZIP-Pfade, Manifest und Ziele werden geprüft. Absolute Payload-Pfade,
`..`, Windows-Gerätenamen, alternative Datenstreams, doppelte Archiveinträge,
symbolische Payload-Links und bestehende Ziel-Links außerhalb der Zielwurzel werden
abgewiesen. Pro Archivebene gelten maximal 1 GiB entpackte Daten und 10000 Einträge;
JSON-Dateien sind auf 1 MiB begrenzt. ZIP-Payloads werden in einem temporären Ordner
entpackt und anschließend entfernt. Verknüpfungsdaten gelangen als JSON, nicht als
eingefügter Programmcode, zu PowerShell.
Wurde das Manifest eines ausgewählten Pakets zwischenzeitlich ersetzt, muss das
Paket vor der Installation erneut geladen werden.

Zielordner müssen mit den Rechten des aktuellen Benutzers beschreibbar sein.
Fehler werden angezeigt und per Python-Logging auf der Konsole protokolliert.
Die GUI schließt nicht, solange der Installationsworker läuft.

## Tests und Erweiterung

Standardbibliothek-Tests für Builder, Engine, Windows-Aufrufdaten und Pfadprüfung:

```powershell
cd installer_builder
python -m unittest discover -s tests -v
```

Die GUI-Tests benötigen PySide6. Auf headless Linux:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Die echte Windows-COM-Verknüpfung sollte zusätzlich auf Windows geprüft werden.
Die Engine ist unabhängig von Qt und meldet `(Prozent, Vorgang)` über einen Callback.
`FileCopier`, `TemplateGenerator` und `ShortcutCreator` können gezielt erweitert
oder für Tests ersetzt werden. Neue Paketformate lassen sich über `format_version`
einführen, ohne die GUI mit Dateilogik zu koppeln.
