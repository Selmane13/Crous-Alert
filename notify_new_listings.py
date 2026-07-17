"""
Automated CROUS housing checker, designed to run unattended (e.g. on a
GitHub Actions schedule every 5 minutes).

Behavior:
    - Fetches all listings from the CROUS "trouverunlogement" API.
    - Compares against IDs already seen (stored in seen_ids.json).
    - Sends a Telegram message for each NEW listing only.
    - If the request fails (e.g. expired cookie), sends a Telegram alert
      instead of failing silently.

Required environment variables:
    TELEGRAM_BOT_TOKEN  - your bot's token from @BotFather
    TELEGRAM_CHAT_ID    - your Telegram chat id
    CROUS_COOKIE        - a fresh 'Cookie' header value from your browser
"""

import json
import os
import sys
from pathlib import Path

import requests

URL = "https://trouverunlogement.lescrous.fr/api/fr/search/47"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CROUS_COOKIE = os.environ["CROUS_COOKIE"]

SEEN_FILE = Path("seen_ids.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "Accept": "application/ld+json, application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": (
        "https://trouverunlogement.lescrous.fr/tools/47/search"
        "?bounds=1.0300648_49.4652606_1.1521157_49.4172001&locationName=Rouen"
    ),
    "Content-Type": "application/json",
    "Origin": "https://trouverunlogement.lescrous.fr",
    "Cookie": CROUS_COOKIE,
}

PAYLOAD = {
    "idTool": 47,
    "need_aggregation": True,
    "page": 1,
    "pageSize": 24,
    "sector": None,
    "occupationModes": [],
    "location": [
        {"lon": -9.9079, "lat": 51.7087},
        {"lon": 14.3224, "lat": 40.5721},
    ],
    "residence": None,
    "precision": 6,
    "equipment": [],
    "price": {"max": 10000000},
    "area": {"min": 0},
    "adaptedPmr": False,
    "toolMechanism": "residual",
}


def send_telegram(text: str) -> None:
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        api_url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)


def fetch_all_listings(page_size: int = 24, max_pages: int = 50) -> list:
    items_all = []
    page = 1
    while page <= max_pages:
        payload = dict(PAYLOAD, page=page, pageSize=page_size)
        resp = requests.post(URL, headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") if isinstance(data, dict) else None
        items = results.get("items") if isinstance(results, dict) else None
        if not items:
            break
        items_all.extend(items)
        if len(items) < page_size:
            break
        page += 1
    return items_all


def format_item(item: dict) -> str:
    residence = item.get("residence", {}) or {}
    rents = []
    for mode in item.get("occupationModes", []) or []:
        rent = mode.get("rent", {}) or {}
        if rent.get("min") is not None:
            rents.append(rent["min"])
    rent_min = f"{min(rents) / 100:.0f}€/mois" if rents else "n/a"
    listing_url = f"https://trouverunlogement.lescrous.fr/tools/47/accommodations/{item.get('id', '')}"
    return (
        f"🏠 <b>{residence.get('label', 'Résidence inconnue')}</b>\n"
        f"{item.get('label', '')}\n"
        f"📍 {residence.get('address', '')}\n"
        f"💶 à partir de {rent_min}\n"
        f"🔗 {listing_url}"
    )


def main() -> None:
    seen_ids = set()
    if SEEN_FILE.exists():
        seen_ids = set(json.loads(SEEN_FILE.read_text()))

    try:
        items = fetch_all_listings()
    except requests.exceptions.RequestException as e:
        send_telegram(
            "⚠️ Le script CROUS a échoué (probablement cookie expiré).\n"
            f"Erreur: {e}\n\n"
            "Va sur trouverunlogement.lescrous.fr, ouvre les DevTools > Network, "
            "copie un nouveau header 'Cookie', et mets à jour le secret CROUS_COOKIE "
            "sur GitHub."
        )
        raise

    if not items:
        print("No items returned by the API.")
        SEEN_FILE.write_text("[]")
        return

    current_ids = {str(item.get("id")) for item in items}
    new_ids = current_ids - seen_ids

    if new_ids:
        new_items = [i for i in items if str(i.get("id")) in new_ids]
        for item in new_items:
            send_telegram(format_item(item))
        print(f"Sent {len(new_items)} new listing notification(s).")
    else:
        print("No new listings.")

    SEEN_FILE.write_text(json.dumps(sorted(current_ids)))


if __name__ == "__main__":
    main()
