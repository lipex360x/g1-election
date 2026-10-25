import json
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = "https://g1.globo.com/mundo/noticia/2026/10/25/votacao-no-exterior-confira-os-resultados-do-2o-turno-entre-lula-e-flavio-bolsonaro.ghtml"
OUT = Path("output")
OUT.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "Accept-Language": "pt-BR,pt;q=0.9"}

def votes(value):
    s = str(value).strip().replace("\u00a0", "")
    if re.fullmatch(r"\\d{1,3}(?:\\.\\d{3})+|\\d+", s):
        return int(s.replace(".", ""))
    return None

def clean(value):
    return re.sub(r"\\s+", " ", str(value)).strip()

def parse_tables(html):
    found = []
    try:
        tables = pd.read_html(StringIO(html))
    except (ValueError, ImportError):
        return found
    for table in tables:
        columns = [clean(" ".join(map(str, c)) if isinstance(c, tuple) else c).lower() for c in table.columns]
        def col(words):
            return next((i for i,c in enumerate(columns) if any(w in c for w in words)), None)
        ci, li, fi = col(["país", "pais", "território", "territorio"]), col(["lula"]), col(["flávio", "flavio"])
        if None in (ci,li,fi):
            continue
        for row in table.itertuples(index=False, name=None):
            l, f = votes(row[li]), votes(row[fi])
            if l is not None and f is not None and clean(row[ci]):
                found.append({"País": clean(row[ci]), "Lula": l, "Flávio": f})
    return found

def parse_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    article = soup.select_one("article") or soup.select_one("main") or soup
    text = article.get_text("\n", strip=True)
    (OUT / "article_text.txt").write_text(text, encoding="utf-8")
    pattern = re.compile(r"^(.{3,80}?)\\s*[-|:]\\s*Lula\\s*:?\\s*([\\d.]+)\\s*(?:votos)?\\s*[,;|/-]\\s*Fl[aá]vio(?: Bolsonaro)?\\s*:?\\s*([\\d.]+)", re.I)
    found = []
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            country, l, f = match.groups()
            l, f = votes(l), votes(f)
            if l is not None and f is not None:
                found.append({"País": clean(country), "Lula": l, "Flávio": f})
    return found

def main():
    info = {"url": URL, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "status": "started"}
    try:
        response = requests.get(URL, headers=HEADERS, timeout=35)
        info["http_status"] = response.status_code
        info["final_url"] = response.url
        html = response.text
        (OUT / "debug.html").write_text(html, encoding="utf-8")
        response.raise_for_status()
        records = parse_tables(html) + parse_lines(html)
        unique = {}
        for row in records:
            key = row["País"].casefold()
            if key in unique and unique[key] != row:
                raise ValueError("Conflicting counts for " + row["País"])
            unique[key] = row
        if not unique:
            info["status"] = "no_structured_results"
            print("No structured country results found; inspect debug.html and article_text.txt")
        else:
            df = pd.DataFrame(unique.values())
            df["Total"] = df["Lula"] + df["Flávio"]
            df["Diferença Lula-Flávio"] = df["Lula"] - df["Flávio"]
            df["Fonte"] = URL
            df.sort_values("Total", ascending=False, inplace=True)
            df.to_csv(OUT / "ranking.csv", index=False, encoding="utf-8-sig")
            df.to_excel(OUT / "ranking.xlsx", index=False)
            info.update(status="success", countries=len(df), lula=int(df["Lula"].sum()), flavio=int(df["Flávio"].sum()))
            print(df.to_string(index=False))
    except Exception as exc:
        info.update(status="error", error=str(exc))
        print("Scraping failed:", repr(exc))
    finally:
        (OUT / "status.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
