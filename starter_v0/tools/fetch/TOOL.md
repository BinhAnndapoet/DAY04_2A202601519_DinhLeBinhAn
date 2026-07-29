---
name: fetch
track: core
kind: http_scrape
provider: Direct (requests)
requires_env: []
inputs: [url]
outputs: [items]
side_effect: false
---
# fetch

Reads the content of a single URL by fetching the HTML directly and extracting text (no API key needed).
