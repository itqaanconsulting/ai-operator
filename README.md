# AI Commitment Operator

Een veilige eerste stap richting een AI executive operator. De applicatie analyseert
e-mails, herkent commitments en deadlines, stelt een vervolgactie voor en plaatst
die actie in een approval queue. Er wordt nooit automatisch iets extern uitgevoerd.

## Huidige pilot

- Analyseert handmatig aangeleverde e-mails met OpenAI.
- Herkent informatie, taken, afspraken, beslissingen en follow-ups.
- Slaat e-mails, commitments en voorgestelde acties op in SQLite.
- Ondersteunt menselijke goedkeuring of afwijzing.
- Houdt beslissingen bij in een audit log.
- Voorkomt dubbele opslag wanneer een Gmail message ID wordt meegegeven.
- Importeert handmatig uitsluitend e-mails met een gekozen Gmail-label.
- Maakt na expliciete goedkeuring een Gmail-concept in dezelfde thread.

De Gmail-poller start niet automatisch. Import verandert geen labels en markeert
geen berichten als gelezen. De operator kan alleen een concept maken; er bestaat
geen endpoint dat e-mail verzendt.

## Installatie

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Maak daarna lokaal een `.env` met minimaal:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
DATABASE_PATH=operator.db
```

Start de API:

```powershell
uvicorn main:app --reload
```

Open vervolgens `http://127.0.0.1:8000/docs` voor de interactieve API.

## Voorbeeld

`POST /analyze-email`

```json
{
  "sender": "jan@example.com",
  "subject": "Besluit over Project X",
  "body": "Kun je uiterlijk vrijdag bevestigen of we akkoord gaan?",
  "gmail_msg_id": "optional-unique-id"
}
```

Bekijk de queues via:

- `GET /commitments?status=open`
- `GET /actions?status=pending_approval`

Keur een actie goed zonder deze al uit te voeren:

`POST /actions/{id}/approve`

```json
{
  "note": "Voorstel gecontroleerd; concept mag worden voorbereid."
}
```

Een tweede beslissing over dezelfde actie retourneert HTTP 409. Dit voorkomt dat
een actie per ongeluk tweemaal wordt behandeld.

## Veilige Gmail-flow

Maak in Gmail eerst het label `AI-Operator` aan en hang dit label alleen aan een
testbericht. Importeer daarna maximaal tien gelabelde berichten met:

`POST /gmail/import`

```json
{
  "label": "AI-Operator",
  "max_results": 10
}
```

Controleer vervolgens `GET /actions?status=pending_approval` en keur de gewenste
actie goed. Goedkeuren voert nog niets extern uit. Maak pas daarna het concept met:

`POST /actions/{id}/execute`

Alleen een actie van het type `draft_reply` met status `approved` en een gekoppeld
Gmail-message-ID kan worden uitgevoerd. Het resultaat is een Gmail-draft; de mail
wordt niet verzonden. Dubbel uitvoeren wordt door een atomaire statusovergang
voorkomen.

## Testen

```powershell
python -m unittest discover -s tests -v
```

## Veiligheid

`.env`, `credentials.json`, `token.pickle` en lokale databases worden door Git
genegeerd. Deel deze bestanden nooit. Als een credential eerder in een publieke
repository heeft gestaan, trek hem dan in en maak een nieuwe aan.

## Logische volgende stappen

1. De veilige Gmail-flow met één speciaal testbericht doorlopen.
2. Open commitments op deadline bewaken en follow-ups voorstellen.
3. Een klein dashboard bouwen voor inbox, approvals en open loops.
