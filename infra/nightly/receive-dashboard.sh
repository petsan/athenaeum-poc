#!/bin/sh
# LXC 250: the forced command of the Athenaeum dashboard key (D16).
# Reads a tar of the dashboard on stdin and swaps it into /srv/evalgate/reports/athenaeum,
# which nginx already serves at /athenaeum/. Nothing else is possible with that key.
set -eu
[ "${SSH_ORIGINAL_COMMAND:-}" = "publish" ] || { echo "refused: the only command is 'publish'" >&2; exit 1; }
dest=/srv/evalgate/reports/athenaeum
incoming=$(mktemp -d "$dest/.incoming.XXXXXX")
trap 'rm -rf "$incoming"' EXIT
head -c 50000000 | tar -x -C "$incoming" --no-same-owner --no-same-permissions -f -
bad=$(find "$incoming" -mindepth 1 \( -type l -o \( -type f ! -name '*.html' ! -name '*.json' ! -name '*.md' \) \
      -o \( ! -type f ! -type d \) \) | head -n 5)
[ -z "$bad" ] || { echo "refused: unexpected entries: $bad" >&2; exit 1; }
find "$incoming" -type d -exec chmod 755 {} + ; find "$incoming" -type f -exec chmod 644 {} +
find "$dest" -mindepth 1 -maxdepth 1 ! -name "$(basename "$incoming")" -exec rm -rf {} +
find "$incoming" -mindepth 1 -maxdepth 1 -exec mv {} "$dest"/ \;
echo "published $(find "$dest" -type f | wc -l) files"
