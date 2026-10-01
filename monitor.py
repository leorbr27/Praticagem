#!/usr/bin/env python3
import json,re,urllib.request
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
URL="https://www.praticagem.org.br/asp/previstas.asp";OUT="manobras.json";TZ=ZoneInfo("America/Sao_Paulo")
class TableParser(HTMLParser):
 def __init__(self): super().__init__();self.rows=[];self.row=[];self.cell="";self.in_cell=False
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag=="tr":self.row=[]
  elif tag in ("td","th"):self.cell="";self.in_cell=True
  elif self.in_cell and tag in ("input","option","img"):
   v=attrs.get("value") or attrs.get("title") or attrs.get("alt") or ""
   if v:self.cell+=" "+v
 def handle_endtag(self,tag):
  if tag in ("td","th") and self.in_cell:self.row.append(" ".join(self.cell.split()));self.cell="";self.in_cell=False
  elif tag=="tr" and self.row:self.rows.append(self.row);self.row=[]
 def handle_data(self,data):
  if self.in_cell:self.cell+=" "+data
def norm(s):
 s=s.lower()
 for a,b in (("ç","c"),("ã","a"),("á","a"),("à","a"),("â","a"),("é","e"),("ê","e"),("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u")):s=s.replace(a,b)
 return re.sub(r"[^a-z0-9]+"," ",s).strip()
def header_row(rows):
 for row in rows:
  joined=" ".join(norm(x) for x in row)
  if sum(k in joined for k in ("navio","data","hora","porto","berco","situacao"))>=3:return row
 return None
def idx(header,names):
 for i,v in enumerate(header):
  if any(x in norm(v) for x in names):return i
 return None
def parse():
 req=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0 Praticagem ES"})
 with urllib.request.urlopen(req,timeout=30) as r:html=r.read().decode("utf-8","replace")
 with open("debug-source.html","w",encoding="utf-8") as f:f.write(html)
 p=TableParser();p.feed(html);rows=[r for r in p.rows if r];h=header_row(rows);data=[]
 if h:
  start=rows.index(h)+1
  ix={"navio":idx(h,("navio","nome","nome do navio")),"data":idx(h,("data",)),"hora":idx(h,("hora","horario","horário")),"porto":idx(h,("porto","terminal")),"berco":idx(h,("berco","ber","berço")),"situacao":idx(h,("situacao","situa","situação","status"))}
  for row in rows[start:]:
   if len(row)<2:continue
   item={k:(row[i] if i is not None and i<len(row) else "") for k,i in ix.items()}
   if any(item.values()):data.append(item)
 else:
  for row in rows:
   if len(row)>=6:data.append({"navio":row[0],"data":row[1],"hora":row[2],"porto":row[3],"berco":row[4],"situacao":row[-1]})
 return data
def main():
 data=parse()
 with open(OUT,"w",encoding="utf-8") as f:json.dump({"atualizado_em":datetime.now(TZ).isoformat(),"fonte":URL,"manobras":data},f,ensure_ascii=False,indent=2)
 print(f"{len(data)} manobras salvas")
if __name__=="__main__":main()
