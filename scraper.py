"""
Kerala Hospital Job Agent
--------------------------
Visits each hospital career page listed in hospitals.json, extracts
likely job-listing text (links/list items), compares against
previously seen entries (seen_jobs.json), and sends a Telegram
message for anything new.

Zero-cost design: meant to run on GitHub Actions on a daily schedule.
"""

import json
import hashlib
import os
import sys
import time
import requests
from bs4 import BeautifulSoup

HOSPITALS_FILE = "hospitals.json"
SEEN_FILE = "seen_jobs.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}

# Words that suggest a piece of text is a job listing, not navigation/footer junk
JOB_KEYWORDS = [
    "nurse", "medical officer", "technician", "technologist", "pharmacist",
    "consultant", "specialist", "executive", "manager", "assistant",
    "receptionist", "coordinator", "therapist", "radiographer",
    "lab", "billing", "hr ", "administrator", "officer", "duty doctor",
    "staff nurse", "vacancy", "vacancies", "hiring", "job opening",
    "physiotherapist", "counsellor", "supervisor", "engineer", "clerk"
]

NOISE_WORDS = [
    "privacy policy", "cookie", "sitemap", "all rights reserved",
    "book appointment", "find a doctor", "contact us", "home",
    "about us", "facebook", "instagram", "twitter", "linkedin",
    "subscribe", "newsletter"
]


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def hash_text(text):
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


def looks_like_job(text):
    t = text.strip().lower()
    if len(t) < 6 or len(t) > 160:
        return False
    if any(n in t for n in NOISE_WORDS):
        return False
    return any(k in t for k in JOB_KEYWORDS)


def extract_candidates(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = set()

    # Links and list items are the most common containers for job titles
    for tag in soup.find_all(["a", "li", "h2", "h3", "h4"]):
        text = tag.get_text(separator=" ", strip=True)
        if looks_like_job(text):
            candidates.add(text)

    return candidates


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram credentials, skipping send.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }, timeout=15)
    if resp.status_code != 200:
        print("Telegram send failed:", resp.text)


def check_hospital(hospital, seen):
    name = hospital["name"]
    url = hospital["url"]
    key = url  # one bucket of seen-hashes per URL

    seen.setdefault(key, [])
    seen_hashes = set(seen[key])

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] {name}: could not fetch ({e})")
        return []

    candidates = extract_candidates(resp.text)
    new_items = []

    for text in candidates:
        h = hash_text(text)
        if h not in seen_hashes:
            new_items.append(text)
            seen_hashes.add(h)

    seen[key] = list(seen_hashes)
    return new_items


def main():
    hospitals = load_json(HOSPITALS_FILE, [])
    seen = load_json(SEEN_FILE, {})

    first_run_urls = [h["url"] for h in hospitals if h["url"] not in seen]

    all_new = []
    for hospital in hospitals:
        new_items = check_hospital(hospital, seen)
        is_first_run = hospital["url"] in first_run_urls
        if new_items and not is_first_run:
            # Only alert if this isn't the very first time we've seen this URL
            # (first run just builds the baseline, to avoid a flood of "new" alerts)
            all_new.append((hospital["name"], hospital["url"], new_items))
        time.sleep(1)  # be polite to servers

    save_json(SEEN_FILE, seen)

    if not all_new:
        print("No new vacancies found.")
        return

    for name, url, items in all_new:
        msg_lines = [f"🏥 <b>{name}</b>", f"{url}", ""]
        for item in items[:15]:
            msg_lines.append(f"• {item}")
        message = "\n".join(msg_lines)
        send_telegram(message)
        print(f"Sent {len(items)} new listing(s) for {name}")


if __name__ == "__main__":
    sys.exit(main())
