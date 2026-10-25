# G1 election results scraper

Experimental extraction of country-level vote counts from the G1 article (25 Oct 2026).

Run automatically via GitHub Actions on pushes to main, or run locally:

```bash
pip install -r requirements.txt
python scraper.py
```

Outputs are stored in `output/` and uploaded as workflow artifacts. The script never fabricates missing rows; review `debug.html` if no structured results are found. Article text may change and the site may block automated requests.
