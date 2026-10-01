#!/usr/bin/env python3
"""Coleta e filtra as manobras previstas da Praticagem Espírito Santo."""
import json,re,urllib.request
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

SOURCE_URL="https://www.praticagem.org.br/asp/previstas.asp"
PUBLIC_SOURCE_URL="https://www.praticagem.org.br/manobras-previstas.html"
OUTPUT_FILE="manobras.json"
TIMEZONE=ZoneInfo("America/Sao_Paulo")
MONITORED_BERCOS={"VIX101","VIX201","VIX202","VIX203","VIX204","VIX206","VIX207","VIX905","VIX906","PRMPS1","PRMPS2","PRMPS3"}

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=""; self.in_cell=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="tr": self.row=[]
        elif tag in ("td","th"): self.cell=""; self.in_cell=True
        elif self.in_cell and tag in ("input","option","img"):
            value=attrs.get("value") or attrs.get("title") or attrs.get("alt") or ""
            if value: self.cell+=" "+value
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.in_cell:
            self.row.append(" ".join(self.cell.split())); self.cell=""; self.in_cell=False
        elif tag=="tr" and self.row:
            self.rows.append(self.row); self.row=[]
    def handle_data(self,data):
        if self.in_cell: self.cell+=" "+data

def norm(value):
    value=value.lower()
    for old,new in (("ç","c"),("ã","a"),("á","a"),("à","a"),("â","a"),("é","e"),("ê","e"),("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u")):
        value=value.replace(old,new)
    return re.sub(r"[^a-z0-9]+"," ",value).strip()

def find_header(rows):
    keys=("navio","data","hora","porto","berco","situacao")
    for row in rows:
        joined=" ".join(norm(value) for value in row)
        if sum(key in joined for key in keys)>=3: return row
    return None

def find_index(header,names):
    for index,value in enumerate(header):
        normalized=norm(value)
        if any(name in normalized for name in names): return index
    return None

def fetch_html():
    request=urllib.request.Request(SOURCE_URL,headers={"User-Agent":"Mozilla/5.0 (compatible; PraticagemMonitor/1.0)","Accept":"text/html,application/xhtml+xml"})
    with urllib.request.urlopen(request,timeout=30) as response:
        return response.read().decode("utf-8","replace")

def parse():
    parser=TableParser(); parser.feed(fetch_html())
    rows=[row for row in parser.rows if row]
    header=find_header(rows)
    if not header: raise RuntimeError("Não foi possível localizar a tabela de manobras na fonte.")
    start=rows.index(header)+1
    indexes={
        "navio":find_index(header,("navio","nome")),
        "data":find_index(header,("data",)),
        "hora":find_index(header,("hora","horario")),
        "tipo":find_index(header,("tipo","movimento","operacao","operação","entrada","saida","saída","manobra")),
        "porto":find_index(header,("porto","terminal")),
        "berco":find_index(header,("berco","ber")),
        "situacao":find_index(header,("situacao","situa","status"))
    }
    if indexes["situacao"] is None: indexes["situacao"]=13
    result=[]
    for row in rows[start:]:
        item={key:row[index] if index is not None and index<len(row) else "" for key,index in indexes.items()}
        if "tipo" not in item: item["tipo"]=""
        if not item["navio"] or not item["berco"]: continue
        result.append(item)
    if not result: raise RuntimeError("A fonte foi acessada, mas nenhuma manobra foi encontrada.")
    return result

def monitored_berco(berco):
    value=berco.strip().upper()
    return value in MONITORED_BERCOS or value.startswith("RCH")

def clean_item(item):
    return {key:item.get(key,"").strip() for key in ("navio","data","hora","tipo","porto","berco","situacao")}

def main():
    all_rows=parse()
    monitored=[clean_item(row) for row in all_rows if monitored_berco(row.get("berco",""))]
    monitored.sort(key=lambda row:(row["data"],row["hora"],row["berco"],row["navio"]))
    payload={"atualizado_em":datetime.now(TIMEZONE).isoformat(),"fonte":PUBLIC_SOURCE_URL,"manobras":monitored}
    with open(OUTPUT_FILE,"w",encoding="utf-8") as file:
        json.dump(payload,file,ensure_ascii=False,indent=2); file.write("\n")
    print(f"Fonte: {SOURCE_URL}")
    print(f"Manobras encontradas: {len(all_rows)}")
    print(f"Manobras monitoradas: {len(monitored)}")
    print("Berços monitorados:",", ".join(sorted({row["berco"] for row in monitored})))

if __name__=="__main__": main()
