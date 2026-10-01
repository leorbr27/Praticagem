#!/usr/bin/env python3
"""Coleta as manobras previstas da Praticagem ES e mantém somente os berços monitorados."""
import html
import json
import re
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

SOURCE_PAGE_URL = "https://www.praticagem.org.br/manobras-previstas.html"
DATA_SOURCE_URL = "https://www.praticagem.org.br/asp/previstas.asp"
OUTPUT_FILE = "manobras.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")

MONITORED_BERCOS = {
    "VIX101", "VIX201", "VIX202", "VIX203", "VIX204", "VIX206", "VIX207",
    "VIX905", "VIX906", "PRMPS1", "PRMPS2", "PRMPS3",
    "RCH101", "RCH102", "RCH103", "RCH501", "RCH502", "RCH503",
}

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = ""
            self.in_cell = True
        elif self.in_cell and tag in ("input", "option", "img"):
            value = attrs.get("value") or attrs.get("title") or attrs.get("alt") or ""
            if value:
                self.cell += " " + value

    def handle_data(self, data):
        if self.in_cell and self.cell is not None:
            self.cell += " " + data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join((self.cell or "").split()))
            self.cell = None
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None

def normalize(value):
    value = str(value).lower()
    replacements = {
        "ç":"c","ã":"a","á":"a","à":"a","â":"a","é":"e","ê":"e",
        "í":"i","ó":"o","ô":"o","õ":"o","ú":"u"
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def fetch_source():
    request = urllib.request.Request(
        DATA_SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PraticagemMonitor/2.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": SOURCE_PAGE_URL,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return raw.decode("utf-8", "replace")

def parse():
    source = fetch_source()

    # A fonte usa HTML/XHTML antigo. Extrair TR/TD por regex é mais tolerante
    # que depender da estrutura do HTMLParser quando há células/BRs irregulares.
    result = []
    date_pattern = re.compile(r"^\\d{2}/\\d{2}/\\d{4}$")
    time_pattern = re.compile(r"^\\d{2}:\\d{2}$")

    for raw_row in re.findall(r"<tr\\b[^>]*>(.*?)</tr\\s*>", source, flags=re.I | re.S):
        cells = []
        for raw_cell in re.findall(r"<t[dh]\\b[^>]*>(.*?)</t[dh]\\s*>", raw_row, flags=re.I | re.S):
            text_value = re.sub(r"<[^>]+>", " ", raw_cell)
            text_value = html.unescape(text_value)
            cells.append(" ".join(text_value.split()))

        date_index = next(
            (i for i, value in enumerate(cells) if date_pattern.match(value)),
            None,
        )
        if date_index is None or date_index + 4 >= len(cells):
            continue
        if not time_pattern.match(cells[date_index + 1]):
            continue

        item = {
            "navio": cells[0],
            "data": cells[date_index],
            "hora": cells[date_index + 1],
            "tipo": cells[date_index + 2],
            "porto": cells[date_index + 3],
            "berco": cells[date_index + 4],
            "situacao": cells[-1],
        }
        if item["navio"] and item["berco"] and item["situacao"]:
            result.append(item)

    if not result:
        raise RuntimeError("A fonte foi acessada, mas nenhuma manobra foi encontrada.")
    return result

def monitored_berco(berco):
    tokens = re.findall(r"[A-Za-z0-9]+", berco.upper())
    return any(token in MONITORED_BERCOS for token in tokens)

def main():
    all_rows = parse()
    monitored = [
        row for row in all_rows
        if monitored_berco(row["berco"])
    ]
    monitored.sort(key=lambda row: (row["data"], row["hora"], row["berco"], row["navio"]))

    payload = {
        "atualizado_em": datetime.now(TIMEZONE).isoformat(),
        "fonte": SOURCE_PAGE_URL,
        "manobras": monitored,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print("Fonte:", DATA_SOURCE_URL)
    print("Manobras encontradas:", len(all_rows))
    print("Manobras monitoradas:", len(monitored))
    print("Berços monitorados:", ", ".join(sorted({row["berco"].upper() for row in monitored})))

if __name__ == "__main__":
    main()
