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
    # Also handle country headings followed by candidate vote counts on separate lines.
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    for i, line in enumerate(lines):
        if not re.fullmatch(r"[A-ZÀ-Ý][A-Za-zÀ-ÿ .()'-]{2,65}", line):
            continue
        nearby = " | ".join(lines[i+1:i+9])
        lm = re.search(r"Lula[^|]{0,70}?(\\d{1,3}(?:\\.\\d{3})+|\\d+)\\s*(?:votos)?", nearby, re.I)
        fm = re.search(r"Fl[aá]vio(?: Bolsonaro)?[^|]{0,70}?(\\d{1,3}(?:\\.\\d{3})+|\\d+)\\s*(?:votos)?", nearby, re.I)
        if lm and fm:
            l, f = votes(lm.group(1)), votes(fm.group(1))
            if l is not None and f is not None:
                found.append({"País": line, "Lula": l, "Flávio": f})
    return found

def parse_country_sections(html):
    """Extract second-round votes from country headings and their adjacent blocks."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article") or soup.select_one("main") or soup
    lines = [clean(x) for x in article.get_text("\\n", strip=True).splitlines()]
    lines = [x for x in lines if x]
    rows = []
    number = r"(\\d{1,3}(?:\\.\\d{3})+|\\d+)"
    candidate = re.compile(r"^(Lula|Fl[aá]vio(?: Bolsonaro)?)\\s*,\\s*" + number + r"\\s*(?:votos?)?\\s*(?:\\(|$)", re.I)
    for i, country in enumerate(lines):
        if not re.fullmatch(r"[A-ZÀ-Ý][A-Za-zÀ-ÿ .()'-]{2,55}", country):
            continue
        # Country heading must be immediately followed by a 2nd-round label.
        if not re.match(r"^2[ºo°]\\s*turno\\s*:?", " ".join(lines[i+1:i+3]), re.I):
            continue
        block = []
        for item in lines[i+1:i+16]:
            if re.match(r"^1[ºo°]\\s*turno", item, re.I):
                break
            block.append(item)
        if not block or not any(re.match(r"^2[ºo°]\\s*turno", x, re.I) for x in block):
            continue
        found = {}
        for item in block:
            match = candidate.match(item)
            if match:
                name = "Lula" if match.group(1).lower().startswith("lula") else "Flávio"
                found[name] = votes(match.group(2))
        if len(found) == 2 and all(v is not None for v in found.values()):
            rows.append({"País":country, "Lula":found["Lula"], "Flávio":found["Flávio"]})
    return rows

def parse_embedded_json(html):
    # Embedded JSON sometimes holds election rows instead of an HTML table.
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for script in soup.select('script[type="application/json"], script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        def walk(obj):
            if isinstance(obj, dict):
                keys = {str(k).lower(): k for k in obj}
                country = next((obj[k] for name,k in keys.items() if name in ("pais","país","country")), None)
                lula = next((obj[k] for name,k in keys.items() if "lula" in name), None)
                flavio = next((obj[k] for name,k in keys.items() if "flavio" in name or "flávio" in name), None)
                if isinstance(country, str) and votes(lula) is not None and votes(flavio) is not None:
                    found.append({"País":clean(country),"Lula":votes(lula),"Flávio":votes(flavio)})
                for v in obj.values(): walk(v)
            elif isinstance(obj, list):
                for v in obj: walk(v)
        walk(data)
    return found

def main():
    info = {"url": URL, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "status": "started"}
    try:
        response = requests.get(URL, headers=HEADERS, timeout=35)
        info["http_status"] = response.status_code
        info["final_url"] = response.url
        html = response.text
        (OUT / "debug.html").write_text(html, encoding="utf-8")
        soup_diag = BeautifulSoup(html, "html.parser")
        info["page_title"] = soup_diag.title.get_text(" ", strip=True) if soup_diag.title else None
        info["html_bytes"] = len(response.content)
        info["html_text_preview"] = soup_diag.get_text(" ", strip=True)[:1200]
        info["article_count"] = len(soup_diag.select("article"))
        info["table_count"] = len(soup_diag.select("table"))
        info["script_count"] = len(soup_diag.select("script"))
        info["contains_lula"] = "lula" in html.lower()
        info["contains_flavio"] = "flávio" in html.lower() or "flavio" in html.lower()
        response.raise_for_status()
        records = parse_country_sections(html) + parse_tables(html) + parse_embedded_json(html)
        article_text = (OUT / "article_text.txt").read_text(encoding="utf-8")
        info["article_text_chars"] = len(article_text)
        info["article_text_sample"] = article_text[:12000]
        info["candidate_contexts"] = [
            article_text[max(0,m.start()-120):m.end()+200]
            for m in list(re.finditer(r"Lula|Fl[aá]vio", article_text, re.I))[:20]
        ]
        unique = {}
        for row in records:
            key = row["País"].casefold()
            if key in unique and unique[key] != row:
                raise ValueError("Conflicting counts for " + row["País"])
            unique[key] = row
        info["extracted_rows"] = len(records)
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
