**Überarbeitung nach Feedback vom 18.10.2026:** Blau = neu oder ergänzt

# 1. Projektübersicht

Wir entwickeln eine Cloud-Anwendung, die Kassenzettel aus Schweizer
Supermärkten (Migros, Coop, Aldi, Lidl) automatisch digitalisiert, die
Artikel kategorisiert und daraus eine strukturierte Ausgabenübersicht
erstellt.

**Ausgangslage und Problemstellung:** Kassenzettel landen meist direkt
im Papierkorb, und herkömmliche Budget-Apps erfordern ein manuelles
Erfassen der einzelnen Ausgaben. Eine händlerübergreifende,
automatisierte Auswertung für gemeinsame Haushalte ist uns in dieser
Form nicht bekannt.

**Lösung und Ziel:** Unsere Anwendung transformiert hochgeladene Fotos
oder PDFs automatisiert in strukturierte Daten. Dadurch sehen Haushalte
auf einen Blick, wie viel sie pro Monat, Kategorie und Laden ausgeben.

**Zielgruppe:** Privathaushalte, Familien und WGs, die ihr
Haushaltsbudget im Blick behalten und ihre Einkäufe in einem gemeinsamen
Account erfassen möchten.

**Fokus und Systemgrenzen (MVP):** Der Schwerpunkt dieses Projekts liegt
auf der Konzeption und Umsetzung einer ereignisgesteuerten
Cloud-Architektur. Im Zentrum steht dabei die asynchrone Verarbeitung
der Belege im Hintergrund. Um diese Infrastruktur aufzubauen, haben wir
den Funktionsumfang des Minimum Viable Products (MVP) auf das
Wesentliche reduziert. Auf komplexe fachliche Logiken wie selbstlernende
Modelle, NLP für Chat-Anfragen, Rezeptvorschläge oder eine
produktübergreifende Wiedererkennung über verschiedene Händler hinweg
wird im MVP verzichtet. So stellen wir sicher, dass die Cloud-Ressourcen
und der Verarbeitungsprozess stabil implementiert werden können.

**Rahmenbedingungen:** Das Projekt wird von fünf Personen umgesetzt.
Jedes Teammitglied verfügt über einen eigenen AWS-Learner-Lab-Account
mit 50 USD Guthaben. Die Dokumentation wird am 14. Dezember 2026
abgegeben, am selben Tag findet der Vortrag statt.

# 2. Technologie- und Dienstebeschreibung

Wir setzen auf eine serverlose, ereignisgesteuerte Architektur im AWS
Learner Lab. Für die Texterkennung nutzen wir primär den nativen
AWS-Dienst Amazon Textract. Falls dieser im Learner Lab nicht verfügbar
ist oder die Erkennungsqualität bei Schweizer Kassenzetteln nicht
genügt, binden wir stattdessen eine externe KI-API an. Der Entscheid
fällt bis Ende SW5 auf Basis eines Tests. Ein erster Test in SW5 hat
bestätigt, dass Textract im Learner Lab verfügbar ist. Textract bleibt
damit primär (siehe «Texterkennung mit AnalyzeExpense»).

  ---------------------------------------------------------------------------
  Bereich             Dienst / Technologie   Aufgabe
  ------------------- ---------------------- --------------------------------
  Frontend-Hosting    Amazon S3 + CloudFront Auslieferung der Web-App (React)

  Authentifizierung   Amazon Cognito User    Registrierung, Login, JWT für
                      Pool                   die API,
                                             Post-Confirmation-Trigger für
                                             das SNS-Abo

  API                 Amazon API Gateway     Endpunkte für Upload, Belege,
                      (REST)                 Korrektur, Dashboard, Haushalte

  Geschäftslogik      AWS Lambda (Python)    API-Funktionen und
                                             Verarbeitungs-Worker

  Dateispeicher       Amazon S3 (privater    Originalbilder und PDFs, Upload
                      Bucket)                per Presigned URL, Lifecycle
                                             nach 30 Tagen in Glacier Instant
                                             Retrieval

  Entkopplung         Amazon SQS (+          Warteschlange für die
                      Dead-Letter-Queue)     Hintergrundverarbeitung,
                                             Retries, separate Queue für
                                             Löschaufträge

  Datenbank           Amazon DynamoDB (+     Haushalte, Mitglieder, Belege,
                      Streams, TTL)          Artikel, Kategorien,
                                             vorberechnete Monatswerte,
                                             Einladungscodes

  Benachrichtigung    Amazon SNS (E-Mail,    Meldung, wenn die Auswertung
                      Filter pro Benutzer) + fertig oder fehlgeschlagen ist
                      Status in der App

  Secrets             AWS Systems Manager    API-Key der externen KI-API (nur
                      Parameter Store        falls Fallback genutzt wird)

  Monitoring          Amazon CloudWatch      Fehler- und Laufzeitüberwachung
                      (Logs, Alarme)

  Infrastruktur als   AWS SAM /              Reproduzierbares Deployment mit
  Code                CloudFormation         der vorgegebenen LabRole

  Extraktion          Amazon Textract        Liest Händler, Datum, Artikel
  (Texterkennung)     AnalyzeExpense         und Preise als strukturierte
                      (primär) / externe     Daten (JSON)
                      KI-API (Fallback)

  Versionierung / CI  GitHub + GitHub        Code, Reviews, automatisches
                      Actions                Deployment
  ---------------------------------------------------------------------------

![](media/image1.png){width="4.864583333333333in"
height="3.1729166666666666in"}

AWS-Dienste und externe KI-API

**Grundprinzip der Entkopplung:** Der Upload der Kassenzettel endet beim
Speichern im S3-Bucket. Alles Weitere läuft entkoppelt über SQS. Dies
stellt sicher, dass Verzögerungen oder Ausfälle bei der Texterkennung
die Web-App nicht blockieren.

**Ablauf eines Uploads:** Das Frontend holt eine Presigned URL und lädt
die Datei direkt in S3. Das S3-Event legt eine Nachricht in die
SQS-Warteschlange. Ein Worker-Lambda ruft die Nachrichten ab und startet
die Texterkennung, primär über Amazon Textract, im Fallback über die
externe KI-API. Das Lambda validiert die strukturierten JSON-Daten,
speichert Beleg sowie Artikel in DynamoDB und setzt den Status auf
«fertig». Abschliessend wird über SNS eine Benachrichtigung ausgelöst.

**Texterkennung mit AnalyzeExpense:** Wir nutzen die Textract-API
AnalyzeExpense, die auf Rechnungen und Quittungen spezialisiert ist. Sie
liefert Händler, Datum und Total als normalisierte Kopffelder
(SummaryFields) und jede Position mit Bezeichnung, Menge und Preis als
LineItems. Dadurch entfällt ein grosser Teil des eigenen Parsings. Fotos
und einseitige PDFs verarbeitet der Worker synchron in einem Aufruf
direkt aus S3. Mehrseitige PDFs würden die asynchrone Variante
(StartExpenseAnalysis / GetExpenseAnalysis) und damit einen zweistufigen
Worker erfordern. Da Kassenzettel praktisch immer einseitig sind, lassen
wir nur einseitige PDFs zu und prüfen die Seitenzahl beim Upload. So
bleibt es bei einem einzigen, synchronen Verarbeitungspfad.

**Ergebnis des Textract-Tests (SW5):** AnalyzeExpense ist im Learner Lab
mit der LabRole verfügbar. Kopffelder wie Händler, Total und MwSt wurden
auch bei einem schrägen Foto mit Schattenwurf korrekt erkannt, ebenso
alle Preise, Mengen und Artikelnummern. Bei zweizeiligen Positionen
(Bezeichnung unter der Preiszeile) erkennt Textract die Bezeichnung
nicht immer als eigenes Feld, liefert sie aber im Rohtext der Zeile
(EXPENSE_ROW) mit. Der Worker übernimmt in diesem Fall die letzte Zeile
des Rohtexts als Artikelname. Ein Aufruf dauerte rund 3.3 Sekunden. Die
Erkennungsqualität bei Supermarktbelegen prüfen wir mit dem Testset von
rund 20 Belegen.

**Benachrichtigung per E-Mail:** Ein Test im Learner Lab (SW5) hat
gezeigt, dass SNS E-Mails gezielt an einzelne Benutzer zustellen kann.
Alle Benutzer abonnieren dasselbe Topic, jedes Abo erhält eine Filter
Policy auf die eigene Benutzer-ID, und der Worker gibt diese ID beim
Publizieren als Attribut mit. Das Abo legt ein Cognito-Trigger nach der
Registrierung an. Die Person muss es einmal per Link bestätigen, bis
dahin erhält sie keine E-Mails. Absender, Sprache und Fusszeile der
Mails sind durch SNS vorgegeben und lassen sich nicht anpassen. Die
Statusanzeige in der App bleibt deshalb der primäre Kanal, E-Mail ist
eine Ergänzung. In einer produktiven Umgebung würden wir für persönliche
Benachrichtigungen Amazon SES einsetzen.

**Kategorisierung:** Zuerst greift eine Regeltabelle mit
Schlüsselwörtern (z.B. «Vollmilch» → Milchprodukte). Artikel ohne
Treffer erhalten bei Textract die Kategorie «Sonstiges» und können
manuell korrigiert werden. Im Fallback ordnet die externe KI-API sie
zusätzlich einer festen Kategorienliste zu. Manuelle Korrekturen werden
nur in der Datenbank gespeichert und nicht zum Training eines Modells
verwendet.

**Umgang mit Rate Limits & Fehlern:** Sollte die Texterkennung (z.B.
aufgrund von Rate Limits oder Service-Limits) temporär fehlschlagen,
sorgt SQS für automatische Neuversuche. Permanente Fehler landen zur
späteren Analyse in der Dead-Letter-Queue. Das Visibility Timeout der
Queue beträgt mindestens das Sechsfache des Lambda-Timeouts, nach drei
Fehlversuchen wird eine Nachricht in die Dead-Letter-Queue verschoben.

**Mehrfachverarbeitung und Duplikate:** S3-Events und SQS-Nachrichten
können mehrfach zugestellt werden. Der Worker ist deshalb idempotent:
Die Beleg-ID wird bereits beim Ausstellen der Presigned URL erzeugt und
ist Teil des S3-Keys. Der Worker setzt den Status nur über eine bedingte
Schreiboperation von «hochgeladen» auf «in Bearbeitung», sodass eine
zweite Zustellung verworfen wird. Bleibt ein Beleg nach einem Absturz
länger als das Lambda-Timeout in Bearbeitung, darf ein Retry ihn
übernehmen. Artikel werden mit festen Schlüsseln überschrieben statt
angehängt, und die Benachrichtigung wird nur beim erfolgreichen Wechsel
auf «fertig» ausgelöst. Eine FIFO-Queue kommt nicht in Frage, da
S3-Events keine FIFO-Queues als Ziel unterstützen. Wird derselbe
Kassenzettel zweimal hochgeladen, erkennen wir das über einen Hash der
Datei, der pro Haushalt nur einmal vorkommen darf. Bei identischem
Händler, Datum und Total weisen wir zusätzlich auf ein mögliches
Duplikat hin. Duplikate fliessen nicht in die Auswertungen ein.

**Begründung DynamoDB statt relationaler Datenbank:** Für unsere
Auswertungen (Summen pro Monat, Kategorie und Laden) wäre eine
relationale Datenbank fachlich naheliegend. Wir haben deshalb Aurora
Serverless v2 geprüft, das inzwischen bei Inaktivität auf null skaliert
und über die Data API ohne VPC aus Lambda erreichbar ist. Ein Test in
SW5 hat gezeigt, dass das Anlegen von Serverless-Instanzen im Learner
Lab durch eine Richtlinie explizit gesperrt ist. Provisionierte
Alternativen wie Aurora oder RDS laufen dauerhaft und verursachen auch
ohne Nutzung Kosten, was bei 50 USD Guthaben pro Account nicht tragbar
ist. DynamoDB im On-Demand-Modus kostet im Leerlauf nichts und benötigt
kein VPC. Den Nachteil bei Aggregationen gleichen wir mit vorberechneten
Monatswerten aus (siehe Datenmodell). In einer produktiven Umgebung
ausserhalb des Learner Labs wäre Aurora Serverless v2 eine valide
Alternative.

**Datenmodell und Auswertungen:** Wir verwenden eine einzige
DynamoDB-Tabelle. Haushalt, Mitglieder, Belege, Artikel und Monatswerte
liegen unter dem Partitionsschlüssel des Haushalts (HH#\<id\>). Damit
sind alle Daten eines Haushalts mit einer Abfrage erreichbar und
technisch von anderen Haushalten getrennt. Ein Sekundärindex nach
Belegdatum liefert die Belegliste pro Monat. Jeder Beleg speichert
zusätzlich seine Summe pro Kategorie. Die Monatswerte (Total, pro
Kategorie, pro Laden) werden vorberechnet: Jede Änderung an einem Beleg
löst über DynamoDB Streams eine Lambda-Funktion aus, die den betroffenen
Monat aus den Belegsummen vollständig neu berechnet, bei einer
Datumskorrektur auch den bisherigen Monat. Weil neu berechnet statt
hoch- oder heruntergezählt wird, bleiben die Werte auch bei Korrekturen,
Löschungen und doppelt zugestellten Ereignissen korrekt. Die Monatswerte
sind wenige Sekunden nach einer Änderung aktuell.

**Skalierbarkeit und Verfügbarkeit:** Alle Komponenten sind serverlos
bzw. verwaltet und skalieren automatisch mit der Last. Lambda startet
bei Bedarf parallele Instanzen, SQS puffert Lastspitzen, DynamoDB läuft
im On-Demand-Modus, und S3 mit CloudFront liefert Dateien und Web-App
ohne eigene Server aus. Die Verarbeitungsrate gegenüber der
Texterkennung begrenzen wir über die maximale Lambda-Nebenläufigkeit
(Reserved Concurrency 10), damit Rate Limits nicht überschritten werden.

**Speicherklassen und Lifecycle:** Belegbilder werden vor allem in den
ersten Tagen für Korrektur und Detailansicht benötigt, danach nur noch
selten. Eine Lifecycle-Regel verschiebt sie deshalb nach 30 Tagen von S3
Standard nach S3 Glacier Instant Retrieval. Diese Klasse kostet rund 80
% weniger Speicher und erlaubt weiterhin einen Zugriff in Millisekunden.
Archivklassen mit Wartezeiten von Stunden schliessen wir aus, weil die
Detailansicht jederzeit verfügbar sein muss. Auf Standard-IA und
Intelligent-Tiering verzichten wir: Glacier IR ist bei seltenem Zugriff
günstiger, und das Zugriffsmuster ist vorhersehbar, sodass sich die
Überwachungsgebühr nicht lohnt. Das Frontend verkleinert Bilder vor dem
Upload auf etwa 300--500 KB. Nie verarbeitete Uploads (Tag
status=pending) werden nach 7 Tagen gelöscht, unvollständige
Multipart-Uploads nach einem Tag. Bei 100 Haushalten mit je 20 Belegen
pro Monat sinken die Speicherkosten nach einem Jahr um rund 75 %. Im
Learner Lab ist der Effekt wegen der geringen Datenmenge
vernachlässigbar.

**Sicherheit:** Die Kommunikation läuft ausschliesslich über HTTPS.
Cognito übernimmt die Authentifizierung, API Gateway prüft das JWT, und
jede Lambda-Funktion prüft zusätzlich die Haushaltszugehörigkeit. Belege
liegen in einem privaten, verschlüsselten S3-Bucket und sind nur über
kurzlebige Presigned URLs erreichbar. Auch DynamoDB ist verschlüsselt.
Uploads werden auf Dateityp und Grösse begrenzt, und der API-Key der
externen KI-API liegt im Parameter Store statt im Code. Da im Learner
Lab nur die LabRole verfügbar ist, können wir Berechtigungen nicht pro
Funktion einschränken und dokumentieren das als bewusste Einschränkung.

**Haushalte und Zugriffsschutz:** Der Beitritt erfolgt über einen
zufälligen Einladungscode, der 48 Stunden gültig und nur einmal
verwendbar ist. Wir speichern nur einen Hash des Codes. Abgelaufene
Codes entfernt die TTL-Funktion von DynamoDB automatisch. Der Beitritt
wird in einer Transaktion ausgeführt, die das Mitglied anlegt und den
Code gleichzeitig entwertet. Fehlversuche werden pro Benutzer begrenzt,
und API Gateway drosselt die Anfragen zusätzlich. Jede Lambda-Funktion
liest die Benutzer-ID aus dem JWT und prüft die Mitgliedschaft bei jedem
Zugriff in der Datenbank. Dadurch wirkt ein Austritt sofort. Belege
gehören dem Haushalt und bleiben nach einem Austritt erhalten, da sie
gemeinsame Ausgaben abbilden. Der Owner überträgt vor einem Austritt
seine Rolle. Verlässt das letzte Mitglied den Haushalt, werden Haushalt,
Belege und Bilder gelöscht. Eine Absicherung pro Haushalt auf IAM-Ebene
ist mit der LabRole nicht möglich und wäre in einer produktiven Umgebung
eine sinnvolle Ergänzung.

**Kontolöschung:** Nutzerinnen und Nutzer können ihr Konto in der App
schliessen. Vorher zeigt die App pro Haushalt, was geschieht, und
verlangt eine erneute Anmeldung. Die API sperrt das Cognito-Konto sofort
und legt einen Löschauftrag in eine eigene SQS-Queue. Ein Worker löscht
asynchron alle Haushalte, in denen die Person einziges Mitglied ist,
samt Belegen, Monatswerten und Bildern in S3. In gemeinsam genutzten
Haushalten wird sie wie bei einem Austritt entfernt: Die Belege bleiben
für die übrigen Mitglieder erhalten, der Bezug zur Person wird entfernt,
und eine allfällige Owner-Rolle geht an das am längsten beteiligte
Mitglied über. Als letzter Schritt wird das Cognito-Konto gelöscht. Alle
Schritte sind wiederholbar. Fehlgeschlagene Löschaufträge landen in der
Dead-Letter-Queue und lösen einen CloudWatch-Alarm aus.

**Einschränkungen Learner Lab:** Da wir keine eigenen IAM-Rollen
erstellen können, nutzen wir für alle Dienste die vorgegebene LabRole.
Um Budgetüberschreitungen zu vermeiden, wird die externe KI-API, falls
sie als Fallback zum Einsatz kommt, mit einem strikten Kostenlimit
betrieben.

**Hauptrisiko:** Die grösste Unsicherheit liegt in der
Erkennungsqualität bei Schweizer Kassenzetteln mit ihren abgekürzten
Artikelnamen. Wir testen deshalb früh mit echten Belegen und halten mit
der externen KI-API einen Fallback bereit.

# 3. Wichtige Funktionalitäten (MVP)

Das Projekt gilt als erfolgreich, wenn die folgenden fünf Kernfunktionen
inklusive Zugriffsschutz lauffähig in AWS implementiert und
bereitgestellt sind.

+----+-------------------------+-------------------------------------------+
| \# | Funktion                | Muss erfüllt sein (Akzeptanzkriterien)    |
+====+=========================+===========================================+
| 1  | Upload und asynchrone   | - Foto (JPG/PNG) oder einseitiges PDF     |
|    | Hintergrundverarbeitung |   (optional) hochladen                    |
|    |                         |                                           |
|    |                         | - Asynchrone Verarbeitung über die Kette  |
|    |                         |   S3 → SQS → Lambda                       |
|    |                         |                                           |
|    |                         | - Statusanzeige in der App (in            |
|    |                         |   Bearbeitung / fertig / fehlgeschlagen / |
|    |                         |   Duplikat)                               |
|    |                         |                                           |
|    |                         | - Benachrichtigung (E-Mail (optional)     |
|    |                         |   oder In App) bei Abschluss              |
|    |                         |                                           |
|    |                         | - Fehlerhafte Belege werden in der        |
|    |                         |   Dead-Letter-Queue abgefangen.           |
+----+-------------------------+-------------------------------------------+
| 2  | Extraktion und          | - Extraktion von Händler, Datum, Artikel, |
|    | Kategorisierung         |   Einzelpreisen und Total                 |
|    | (inklusive Korrektur)   |                                           |
|    |                         | - Zuweisung jedes Artikels zu einer       |
|    |                         |   Kategorie                               |
|    |                         |                                           |
|    |                         | - Manuelle Korrekturmöglichkeit für       |
|    |                         |   erkannte Artikel, Preise und Kategorien |
|    |                         |   (optional nur eingeschränkt)            |
+----+-------------------------+-------------------------------------------+
| 3  | Dashboard und           | - Aggregierte Darstellung der Ausgaben    |
|    | Auswertung              |   pro Monat, pro Kategorie und pro Laden  |
|    |                         |                                           |
|    |                         | - Visueller Vergleich mit dem Vormonat    |
|    |                         |   (optional)                              |
|    |                         |                                           |
|    |                         | - Historische Liste aller Belege mit      |
|    |                         |   Detailansicht                           |
+----+-------------------------+-------------------------------------------+
| 4  | Gemeinsame Haushalte    | - Erstellung eines Haushalts und          |
|    |                         |   Einladung weiterer Mitglieder per Code  |
|    |                         |   (48 h gültig, einmalig verwendbar)      |
|    |                         |   (optional ohne Code)                    |
|    |                         |                                           |
|    |                         | - Feste Zuordnung hochgeladener Belege zu |
|    |                         |   einem spezifischen Haushalt             |
|    |                         |                                           |
|    |                         | - Auswertungen basieren auf den           |
|    |                         |   Gesamtdaten des jeweiligen Haushalts    |
|    |                         |                                           |
|    |                         | - Mitglieder können den Haushalt          |
|    |                         |   verlassen bzw. vom Owner entfernt       |
|    |                         |   werden, der Zugriff endet sofort        |
+----+-------------------------+-------------------------------------------+
| 5  | Kontolöschung           | - Konto inklusive aller eigenen Daten in  |
|    |                         |   DynamoDB und S3 löschbar                |
|    |                         |                                           |
|    |                         | - In gemeinsamen Haushalten bleiben die   |
|    |                         |   Belege erhalten, die Owner-Rolle wird   |
|    |                         |   übertragen                              |
|    |                         |                                           |
|    |                         | - Sofortige Sperre des Kontos, Löschung   |
|    |                         |   innerhalb weniger Minuten abgeschlossen |
+----+-------------------------+-------------------------------------------+
| -- | Querschnitt: Sicherheit | - Authentifizierung über Amazon Cognito   |
|    |                         |                                           |
|    |                         | - Strikte Datenisolierung (Belege und     |
|    |                         |   Bilder sind nur für berechtigte         |
|    |                         |   Haushaltsmitglieder abrufbar)           |
|    |                         |                                           |
|    |                         | - Autorisierungsprüfung in jeder          |
|    |                         |   Lambda-Funktion                         |
|    |                         |                                           |
|    |                         | - Absicherung durch privaten S3-Bucket    |
|    |                         |   und kurzlebige Presigned URLs           |
+----+-------------------------+-------------------------------------------+

**Priorisierung innerhalb des MVP:** Zwingend ist alles, was die
Kernarchitektur zeigt: Login mit Cognito, Upload per Presigned URL, die
asynchrone Kette S3 → SQS → Lambda → Texterkennung → DynamoDB mit
Dead-Letter-Queue, Statusanzeige, Haushalte mit Datenisolierung,
Kategorisierung sowie ein Dashboard mit Ausgaben pro Monat, Kategorie
und Laden samt Beleg-Liste. Die folgenden fünf Punkte gelten als
Kann-Kriterien. Wir setzen sie um, soweit es die Zeit erlaubt. Bei
Zeitnot reduzieren wir sie in dieser Reihenfolge, die Entscheidung fällt
rechtzeitig vor M3 und wird in der Dokumentation festgehalten:

1.  Der Vormonatsvergleich im Dashboard entfällt.

2.  Die Benachrichtigung erfolgt nur noch in der App, nicht per E-Mail.

3.  Es werden nur Fotos (JPG/PNG) unterstützt, kein PDF-Upload.

4.  Die Korrekturansicht beschränkt sich auf Kategorien statt auf alle
    Felder.

5.  Haushalte werden ohne Einladungscode umgesetzt, z.B. Beitritt über
    eine geteilte Haushalts-ID (mit geringerer Sicherheit, siehe Kapitel
    2).

Nicht Teil des MVP sind die in Kapitel 1 genannten fachlichen
Erweiterungen sowie Preisverlauf und Datenexport. Soweit sinnvoll, sind
sie in Kapitel 4 als optionale Erweiterungen vorgesehen.

Wir testen mit einem Set von rund 20 echten Belegen aus allen vier
Händlern und streben an, dass mindestens 90% der Artikel korrekt erkannt
werden. Die Lambda-Funktionen erhalten Unit-Tests, die
Verarbeitungskette (S3 → SQS → Lambda → DynamoDB) wird durchgängig
getestet. Fehler stufen wir nach Auswirkung ein: Kritisch sind Fehler im
Upload, in der Verarbeitung oder im Zugriffsschutz, nicht kritisch sind
Darstellungsfehler im Dashboard.

**Qualitätsziele:** Bei normaler Last ist ein Beleg in 95 % der Fälle
spätestens 10 Sekunden nach dem Upload ausgewertet (p95 ≤ 10 s). Eine
Lastspitze von 200 Uploads innerhalb einer Minute wird vollständig
angenommen, kein Beleg geht verloren, und alle sind nach höchstens 3
Minuten verarbeitet. Die API antwortet auch während der Lastspitze in 95
% der Fälle in unter einer Sekunde, und kein Beleg landet wegen
Drosselung durch Textract in der Dead-Letter-Queue. Grundlage ist ein
Test im Learner Lab (SW5): Textract AnalyzeExpense benötigt rund 3.3
Sekunden pro Beleg und ist auf 5 Aufrufe pro Sekunde begrenzt, Lambda
erlaubt 400 parallele Ausführungen. Ohne Begrenzung würde eine
Lastspitze also zu Drosselungsfehlern bei Textract führen. Wir begrenzen
den Worker deshalb auf 10 parallele Ausführungen, was etwa 3 Belegen pro
Sekunde entspricht, und lassen SQS den Rest puffern. Den Nachweis
erbringen wir mit einem Lasttest-Skript, das Belege mit jeweils
eindeutigem Hash parallel über Presigned URLs hochlädt. Für grosse Läufe
simuliert ein Mock-Modus Textract mit realistischer Dauer und
Ratenbegrenzung. Gemessen wird über die Zeitstempel in DynamoDB sowie
über die CloudWatch-Metriken zur Länge und Wartezeit der Queue, zur
Nebenläufigkeit und zu Drosselungen von Lambda und zur Latenz von API
Gateway. Den Verlauf zeigen wir als CloudWatch-Dashboard.

# 4. Zusätzliche Erweiterungen

Optionale Erweiterungen werden erst nach der vollständigen und
lauffähigen Implementierung des MVP in Betracht gezogen. Die Umsetzung
erfolgt streng nach Priorität: Cloud-Infrastruktur-Features haben
Vorrang vor reiner Anwendungs- und Fachlogik.

1.  **Datenexport:** Export aller Haushaltsdaten (CSV/JSON) (die
    Kontolöschung ist neu Teil des MVP).

2.  **Budgetwarnung:** Definition eines Monatsbudgets pro Kategorie mit
    automatischer Benachrichtigung bei Überschreitung (ausgelöst durch
    zeitgesteuerte EventBridge-Regeln).

3.  **Monatsbericht:** Generierung und Versand einer automatischen
    Haushalts-Zusammenfassung per E-Mail am Monatsanfang.

4.  **Preisverlauf:** Darstellung der Preisentwicklung für exakt gleiche
    Artikelbezeichnungen innerhalb desselben Ladens.

5.  **Fragen in natürlicher Sprache:** Übersetzung einer Nutzereingabe
    via externer API in eine strukturierte Datenbankabfrage. Die
    Auswertung erfolgt auf der eigenen Datenbank.

6.  **Rezeptvorschläge:** KI-gestützte Generierung von passenden
    Rezepten basierend auf den eingekauften Artikeln der letzten sieben
    Tage.

# 5. Meilensteine und Zeitplan

Die Projektplanung basiert auf einem 14-wöchigen Semester. Um technische
Risiken frühzeitig zu minimieren, ist die Umsetzung so strukturiert,
dass die Cloud-Kernarchitektur schnellstmöglich getestet werden kann.

![Zeitplan 5 Phasen, 5
Meilensteine](media/image2.png){width="6.086456692913385in"
height="4.410115923009624in"}

**Kritischer Meilenstein (M2 Ende SW7):** Zur Semesterhälfte muss die
Basisversion stehen. Ab diesem Zeitpunkt wird ein Beleg vom Upload bis
zum Eintrag in DynamoDB durchgängig asynchron verarbeitet.

**Vollständiges MVP (M3 Ende SW10):** Das komplette MVP, inklusive
Dashboard und der Verwaltung gemeinsamer Haushalte, ist deployt und
lauffähig.

**Priorisierung:** Optionale Erweiterungen werden erst begonnen, wenn M3
erfolgreich abgeschlossen ist. Die verbleibenden drei Wochen dienen der
Implementierung dieser Erweiterungen sowie dem Testing, der
Dokumentation und der Vorbereitung der Präsentation.

# 6. Teamorganisation

Wir teilen die Arbeit entlang der Architektur und fachlichen Domänen
auf. Bei fünf Personen lässt sich das Projekt ideal strukturieren, indem
insbesondere das Backend in einen synchronen und einen asynchronen Teil
aufgespalten wird. Jedes Teammitglied fokussiert sich auf einen
spezialisierten Bereich und vertritt einen definierten zweiten, um
Engpässe zu vermeiden.

  ------------------------------------------------------------------------------
  Person   Hauptverantwortung                              Stellvertretung
  -------- ----------------------------------------------- ---------------------
  Person 1 **Cloud-Infrastruktur & CI/CD:**                Backend (Async & KI)
           SAM/CloudFormation, S3 (Buckets & Policies),
           Cognito, IAM (LabRole), GitHub Actions

  Person 2 **Backend (Core API & Datenmodell):** API       Cloud-Infrastruktur &
           Gateway, synchrone Lambda-Funktionen            CI/CD
           (Dashboard, Haushalte), DynamoDB-Design und
           Aggregation der Monatswerte (DynamoDB Streams)

  Person 3 **Backend (Async & KI):** SQS, Worker-Lambdas,  Backend (Core API)
           Anbindung Amazon Textract / externe KI-API,
           SNS-Benachrichtigungen, Lösch-Worker für die
           Kontolöschung

  Person 4 **Frontend (Basis & Upload):** React-App Setup, Frontend (Dashboard)
           Authentifizierungs-UI, Datei-Upload per
           Presigned URL, Korrekturansicht, Dialog zur
           Kontolöschung

  Person 5 **Frontend (Dashboard) & QS:**                  Frontend (Basis)
           Haushaltsverwaltung, Dashboard-Logik,
           CloudWatch-Monitoring, Lasttest und Nachweis
           der Qualitätsziele, übergreifendes Testing &
           Dokumentation
  ------------------------------------------------------------------------------

**Zusammenarbeit:**

- Wöchentliches Kurzmeeting, Aufgabenverwaltung als GitHub Issues auf
  einem Projektboard.

- Jede Änderung erfolgt über einen Pull Request mit Code-Review durch
  eine zweite Person aus dem Team.

- Das verbleibende Budget in den Learner-Lab-Accounts sowie, falls der
  Fallback genutzt wird, die Kosten der externen API werden wöchentlich
  geprüft.
