import os
import csv
import io
import ftplib
import logging
import datetime
import requests
import re
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
FEED_DIR = os.path.join(BASE_DIR, 'feeds')
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FEED_DIR, exist_ok=True)

log_file = os.path.join(LOG_DIR, f'vct_sync_{datetime.date.today()}.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)

load_dotenv(os.path.join(BASE_DIR, '.env'))

INVENTORY_URL = 'https://vctwheels.com/inventory-database/'
AUTH_URL      = 'https://vctwheels.com/wp-login.php?action=postpass'
PASSWORD      = 'slickride'

WBR_FTP_HOST = os.environ.get('FTP_HOST')
WBR_FTP_USER = os.environ.get('FTP_USER')
WBR_FTP_PASS = os.environ.get('FTP_PASS')

OUT_FILENAME = 'VCT_Inventory.csv'
OUT_FILE     = os.path.join(FEED_DIR, OUT_FILENAME)
CSV_HEADERS  = ['Item', 'Description', 'Finish', 'Size', 'BP', 'Brand', 'Qty']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def get_auth_cookie():
    logging.info("Authenticating with VCT...")
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.post(AUTH_URL, data={
        'post_password': PASSWORD,
        'Submit': 'Enter'
    }, headers={'Referer': INVENTORY_URL}, allow_redirects=True, timeout=30)

    for cookie in session.cookies:
        if 'wp-postpass' in cookie.name:
            logging.info("Auth cookie obtained")
            return session
    logging.error("Failed to get auth cookie")
    return None


def fetch_inventory_page(session):
    logging.info("Fetching VCT inventory page...")
    resp = session.get(INVENTORY_URL, timeout=60)
    if resp.status_code != 200:
        logging.error(f"Page fetch failed: {resp.status_code}")
        return None
    return resp.text


def decode_html(text):
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&quot;', '"').replace('&lt;', '<') \
               .replace('&gt;', '>').replace('&#39;', "'").replace('&nbsp;', ' ') \
               .replace('&#8230;', '...')
    return text.strip()


def parse_table(html):
    rows = []
    for row_match in re.finditer(r'<tr[^>]*data-row_id="\d+"[^>]*>([\s\S]*?)</tr>', html):
        cells = re.findall(r'<td>([\s\S]*?)</td>', row_match.group(1))
        values = [decode_html(c) for c in cells]
        if values:
            rows.append(values)
    logging.info(f"Parsed {len(rows)} rows")
    return rows


def write_csv(rows):
    with open(OUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        writer.writerows(rows)
    logging.info(f"Wrote {len(rows)} rows to {OUT_FILENAME}")


def upload_to_wbr():
    logging.info(f"Uploading {OUT_FILENAME} to WBR FTP...")
    ftp = ftplib.FTP(WBR_FTP_HOST, timeout=60)
    ftp.login(WBR_FTP_USER, WBR_FTP_PASS)
    with open(OUT_FILE, 'rb') as f:
        ftp.storbinary(f'STOR {OUT_FILENAME}', f)
    ftp.quit()
    logging.info(f"{OUT_FILENAME} uploaded OK")


def main():
    start = datetime.datetime.now()
    logging.info("=== VCT Inventory Sync Started ===")

    session = get_auth_cookie()
    if not session:
        return

    html = fetch_inventory_page(session)
    if not html:
        return

    rows = parse_table(html)
    if not rows:
        logging.error("No rows parsed — aborting")
        return

    write_csv(rows)

    try:
        upload_to_wbr()
    except Exception as e:
        logging.error(f"WBR FTP upload error: {e}")

    logging.info(f"=== VCT Sync Done in {datetime.datetime.now() - start} ===")


if __name__ == "__main__":
    main()
