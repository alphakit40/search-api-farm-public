"""Anonymous web (not API) proof that the repo page + raw README are readable."""
import urllib.error
import urllib.request

for url in ["https://github.com/alphakit40/search-api-farm-public",
            "https://raw.githubusercontent.com/alphakit40/search-api-farm-public/main/README.md"]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            print(r.status, url, len(body), "bytes")
    except urllib.error.HTTPError as e:
        print(e.code, url)
