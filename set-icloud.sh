#!/bin/bash
# Store the iCloud (CardDAV) login for birthdays in .env without echoing it.
# Run on the server: sudo /opt/eink-dash/set-icloud.sh
set -e
read -p "Apple ID email: " U
read -s -p "App-specific password (xxxx-xxxx-xxxx-xxxx): " P; echo
cd "$(dirname "$0")"
sed -i '/^ICLOUD_USERNAME=/d;/^ICLOUD_APP_PASSWORD=/d' .env
printf 'ICLOUD_USERNAME=%s\nICLOUD_APP_PASSWORD=%s\n' "$U" "$P" >> .env
chmod 600 .env
docker compose up -d --force-recreate
sleep 10
docker exec eink-dash python -c "from app import birthdays as b; print(len(b.fetch_contacts()), 'contacts with birthdays found')"
