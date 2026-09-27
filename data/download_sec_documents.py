#!/usr/bin/env python3
"""
Download the SEC documents referenced by public_sec_documents.csv.

Usage:
    export SEC_USER_AGENT="Your Name your.email@example.com"
    python download_sec_documents.py

SEC asks automated clients to identify themselves. Keep request rates modest.
"""
from pathlib import Path
import csv, os, time, urllib.request

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "sec_documents"
OUT.mkdir(exist_ok=True)
ua = os.environ.get("SEC_USER_AGENT")
if not ua:
    raise SystemExit("Set SEC_USER_AGENT, e.g. 'Your Name your.email@example.com'.")

with open(ROOT / "public_sec_documents.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

for row in rows:
    url = row["source_url"]
    suffix = ".htm"
    if url.lower().endswith(".pdf"):
        suffix = ".pdf"
    target = OUT / f'{row["document_id"]}{suffix}'
    if target.exists():
        print("skip", target.name)
        continue
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            target.write_bytes(r.read())
        print("saved", target.name)
    except Exception as e:
        print("ERROR", row["document_id"], e)
    time.sleep(0.2)
