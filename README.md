# AI Task Fallback Chain für Home Assistant

Eine Custom Integration, die mehrere **AI-Task-Entitäten in Reihe schaltet**.
Sie stellt eine eigene AI-Task-Entität bereit (z. B.
`ai_task.ai_task_fallback_kette`). Diese reicht jede Aufgabe an die
eingerichteten AI-Task-Dienste weiter, der Reihe nach, und nimmt die erste
Antwort, die funktioniert.

Das Gegenstück für Sprachausgabe ist die
[TTS Fallback Chain](https://github.com/EmilyMoonstone/ha_tts_fallback_chain).

Typisches Beispiel:

| Stufe | Dienst                                                                   |
| ----- | ------------------------------------------------------------------------ |
| 1     | Google Gemini, **Free Tier** (`ai_task.backend_google_ai_task_free`)     |
| 2     | Google Gemini, **bezahlter API-Key** (`ai_task.google_ai_task`)          |
| 3     | optional ein anderer Anbieter oder ein lokales Modell (Ollama, …)        |

Ist das Modell gerade überlastet (HTTP 503 `UNAVAILABLE`), versucht die Kette
es nach ein paar Sekunden erneut. Klappt das nicht oder ist das kostenlose
Kontingent aufgebraucht (HTTP 429 `RESOURCE_EXHAUSTED`), springt sie auf den
bezahlten Key.

## Funktionen

- **Beliebig viele Stufen** in fester Reihenfolge. Jede AI-Task-Entität in
  Home Assistant kann eine Stufe sein.
- Funktioniert für **Daten erzeugen** (`ai_task.generate_data`, auch mit
  `structure` und Anhängen) und **Bilder erzeugen** (`ai_task.generate_image`).
  Die Kette bietet an, was mindestens eine ihrer Stufen kann. Stufen, die eine
  Aufgabe nicht können (z. B. keine Anhänge), werden dafür einfach übergangen.
- **Wiederholen bei Überlastung:** Bei 500/502/503/504 oder „model overloaded“
  wird dieselbe Stufe sofort noch einmal versucht (Standard: 2 Wiederholungen,
  Wartezeit 3 s, 6 s). Das ist meist schneller und günstiger als der Wechsel
  auf die nächste Stufe.
- **Timeout pro Versuch:** Hängt ein Dienst, geht es nach X Sekunden mit der
  nächsten Stufe weiter. Das gilt auch dann, wenn die Stufe den Abbruch
  ignoriert (z. B. weil eine Client-Bibliothek intern weiter wiederholt).
- **Pausen (Cooldown):** Eine fehlgeschlagene Stufe wird eine Zeit lang
  übersprungen, damit nicht jede Aufgabe erst in den Fehler läuft.
  * nach einem normalen Fehler, Timeout oder Überlastung: Standard 5 Minuten
  * nach einem Kontingent- oder Rate-Limit-Fehler (429): Standard 60 Minuten
  * **Tageskontingent** (z. B. `GenerateRequestsPerDay…-FreeTier`): bis zum
    Reset um Mitternacht Pacific Time (bei uns 9 Uhr). Abschaltbar.
  * Pausierte Stufen werden als **letzte Möglichkeit** trotzdem versucht, wenn
    alle anderen Stufen gescheitert sind. Eine Aufgabe fällt also nie nur
    wegen einer Pause aus.
- **Sensor „Zuletzt genutzter AI-Dienst“:** Zeigt, welche Stufe zuletzt
  geantwortet hat. Als Attribute gibt es pro Stufe Erfolge, Fehler, den letzten
  Fehler mit Fehlerart und das Ende der Pause.
- **Button „Pausen zurücksetzen“:** Alle Stufen werden sofort wieder normal
  versucht.
- **Events** für eigene Automationen:
  * `ai_task_fallback_chain_stage_failed` enthält `stage`, `entity_id`,
    `task_name`, `error`, `error_kind` (`daily_quota`, `quota`, `transient`,
    `timeout`, `other`), `quota_error`, `attempts`, `cooldown_until` und
    `message`.
  * `ai_task_fallback_chain_all_stages_failed` enthält `task_name`, `message`
    und `errors`.

## Installation über HACS

1. HACS → oben rechts **⋮** → **Benutzerdefinierte Repositories**.
2. Repository: `https://github.com/EmilyMoonstone/ha_ai_fallback_chain`,
   Typ: **Integration** → Hinzufügen.
3. In HACS nach **AI Task Fallback Chain** suchen → **Herunterladen**.
4. Home Assistant **neu starten**.

Manuell geht es auch: Kopiere den Ordner
`custom_components/ai_task_fallback_chain` nach `config/custom_components/` und
starte Home Assistant neu.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „AI Task
   Fallback Chain“**.
2. Allgemeine Einstellungen: Name, Timeout, Wiederholungen und Pausen.
3. **Stufe 1:** z. B. `ai_task.backend_google_ai_task_free`.
4. **Weitere Stufe hinzufügen** → z. B. `ai_task.google_ai_task`.
5. **Fertig, speichern.**

Die neue Entität `ai_task.<name>` kannst du überall auswählen, wo eine
AI-Task-Entität gebraucht wird: `ai_task.generate_data`, Automationen,
Music Assistant (AI Radio), …

Später ändern: Integration → **Konfigurieren**. Timeout, Wiederholungen und
Pausen änderst du direkt. Für neue Stufen oder eine andere Reihenfolge setzt du
den Haken **„Stufen neu festlegen“**. Die bisherigen Stufen werden dabei als
Vorschlag übernommen.

## Beispiel

```yaml
action: ai_task.generate_data
data:
  entity_id: ai_task.ai_task_fallback_kette
  task_name: Wetter-Ansage
  instructions: >-
    Formuliere eine kurze, lockere Wetteransage für heute:
    {{ states('weather.forecast_home') }}
response_variable: result
```

Benachrichtigung, wenn das Free-Tageskontingent aufgebraucht ist:

```yaml
triggers:
  - trigger: event
    event_type: ai_task_fallback_chain_stage_failed
    event_data:
      stage: 1
      error_kind: daily_quota
actions:
  - action: persistent_notification.create
    data:
      title: AI Task
      message: >-
        Gemini-Free-Kontingent aufgebraucht, nutze bis
        {{ as_local(as_datetime(trigger.event.data.cooldown_until)).strftime('%H:%M') }}
        den bezahlten Key.
```

## Hinweise

- Jede Stufe bekommt eine eigene, frische Chat-Sitzung. Ein halb
  fehlgeschlagener Versuch landet also nicht im Verlauf der nächsten Stufe.
- Fehler einzelner Stufen erscheinen weiterhin im Log des jeweiligen Dienstes.
  Die Kette schreibt zusätzlich eine Warnung, welche Stufe übersprungen wurde
  und warum.
- Eine Fallback-Kette kann nicht selbst Stufe einer Kette sein, weil das eine
  Endlosschleife ergeben würde.
- Welche Fähigkeiten (Anhänge, Bilder) die Kette anbietet, wird beim Start aus
  den Stufen gelesen. Nach dem Ändern der Stufen lädt die Integration neu.

## Entwicklung

```bash
pip install -r requirements_test.txt
python -m pytest
```

Die Tests prüfen die Fehlererkennung und die Pausen und brauchen kein Home
Assistant.
