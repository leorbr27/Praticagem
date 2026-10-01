#!/usr/bin/env python3
"""Coleta as manobras previstas da Praticagem ES e mantém somente os berços monitorados."""
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
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")

def find_data_header(rows):
    for row in rows:
        words = {normalize(cell) for cell in row}
        if {"nome", "data", "hora", "manobra", "porto", "berco"}.issubset(words):
            return row
    return None

def find_index(header, names):
    for index, value in enumerate(header):
        normalized = normalize(value)
        if any(name in normalized for name in names):
            return index
    return None

def parse():
    parser = TableParser()
    parser.feed(fetch_source())
    rows = [row for row in parser.rows if row]
    header = find_data_header(rows)
    if header is None:
        raise RuntimeError("Não foi possível localizar a tabela de manobras na fonte.")

    start = rows.index(header) + 1

    # Estrutura atual da tabela: Nome(0), Tipo(1), ..., Data(6), Hora(7),
    # Manobra(8), Porto(9), Berço(10), ..., Situação(13).
    indexes = {
        "navio": find_index(header, ("nome", "navio")),
        "data": find_index(header, ("data",)),
        "hora": find_index(header, ("hora", "horario")),
        "tipo": 8,
        "porto": 9,
        "berco": 10,
        "situacao": 13,
    }
    fallbacks = {
        "navio": 0, "data": 6, "hora": 7,
        "tipo": 8, "porto": 9, "berco": 10, "situacao": 13,
    }
    for key, fallback in fallbacks.items():
        if indexes[key] is None:
            indexes[key] = fallback

    result = []
    for row in rows[start:]:
        if len(row) <= max(indexes.values()):
            continue
        item = {
            key: row[indexes[key]].strip()
            for key in ("navio", "data", "hora", "tipo", "porto", "berco", "situacao")
        }
        if not item["navio"] or not item["berco"]:
            continue
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
