#!/usr/bin/env python3
import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

PRACTICAGEM_URL = "https://www.praticagem.org.br/asp/previstas.asp"
TZ = ZoneInfo("America/Sao_Paulo")

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.in_cell = [], [], "", False
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag in ("td","th"): self.cell, self.in_cell = "", True
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.in_cell:
            self.row.append(" ".join(self.cell.split()))
            self.cell, self.in_cell = "", False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []
    def handle_data(self, data):
        if self.in_cell: self.cell += " " + data

def get_json(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 Praticagem Monitor"})
    if token: req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_rows():
    req = urllib.request.Request(PRACTICAGEM_URL, headers={"User-Agent":"Mozilla/5.0 Praticagem Monitor"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    p = TableParser(); p.feed(html)
    return p.rows

def parse_issue(body):
    out = {}
    for line in body.splitlines():
        m = re.match(r"\s*(Navio|Data|Hora|Topic)\s*:\s*(.+?)\s*$", line, re.I)
        if m: out[m.group(1).lower()] = m.group(2).strip()
    return out

def normalize(s):
    return re.sub(r"\s+", " ", s).strip().casefold()

def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("GITHUB_TOKEN")
    issues = get_json(f"https://api.github.com/repos/{repo}/issues?state=open&per_page=20", token)
    issues = [x for x in issues if "pull_request" not in x and x.get("title","").upper().startswith("MONITORAR:")]
    if not issues:
        print("Nenhum monitoramento ativo.")
        return

    issue = sorted(issues, key=lambda x: x.get("created_at",""), reverse=True)[0]
    cfg = parse_issue(issue.get("body",""))
    ship, date_s, time_s, topic = cfg.get("navio"), cfg.get("data"), cfg.get("hora"), cfg.get("topic")
    if not all([ship, date_s, time_s, topic]):
        print("Monitoramento incompleto no issue:", issue["number"]); return

    rows = fetch_rows()
    target = normalize(ship)
    match = None
    for row in rows:
        if row and any(normalize(ship) == normalize(c) or target in normalize(c) for c in row[:3]):
            match = row; break

    now = datetime.now(TZ)
    state_path = "monitor-state.json"
    try:
        with open(state_path, "r", encoding="utf-8") as f: state = json.load(f)
    except Exception:
        state = {}

    result = {"checked_at": now.isoformat(), "ship": ship, "date": date_s, "time": time_s, "status": "NAO_ENCONTRADO"}
    if not match:
        print(json.dumps(result, ensure_ascii=False)); return

    # Expected row: Nome, Tipo, LOA, ..., Data, Hora, Manobra, Porto, Berço, Bordo, Situação.
    result["row"] = match
    status = match[-1].strip().upper() if match else ""
    result["status"] = status

    date_idx = next((i for i,v in enumerate(match) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), None)
    time_idx = date_idx + 1 if date_idx is not None and date_idx + 1 < len(match) and re.fullmatch(r"\d{2}:\d{2}", match[date_idx+1]) else None

    if status == "INICIADA" and date_idx is not None and time_idx is not None:
        start = datetime.strptime(match[date_idx] + " " + match[time_idx], "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
        alarm = start + timedelta(hours=1)
        key = f"{normalize(ship)}|{start.isoformat()}|INICIADA"
        result["alarm_at"] = alarm.isoformat()
        if state.get("last_notified_key") != key:
            payload = {
                "topic": topic,
                "title": "🚢 Manobra iniciada",
                "message": f"{ship}: manobra iniciada às {start:%H:%M} em {start:%d/%m/%Y}. Alerta programado para {alarm:%H:%M}.",
                "priority": 5,
                "tags": ["ship", "rotating_light"],
                "click": "https://leorbr27.github.io/Praticagem/"
            }
            req = urllib.request.Request("https://ntfy.sh", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r: print("ntfy:", r.status)
            state["last_notified_key"] = key
            state["last_alarm_at"] = alarm.isoformat()

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(result | state, f, ensure_ascii=False, indent=2)
    print(json.dumps(result | state, ensure_ascii=False))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print("ERRO:", repr(e)); sys.exit(1)
