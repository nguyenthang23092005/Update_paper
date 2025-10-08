import requests
import xml.etree.ElementTree as ET




# ========================
# 1. OpenAlex API
# ========================
def decode_openalex_abstract(inverted_index):
    if not inverted_index:
        return "Not Available"
    words = sorted([(pos, word) for word, positions in inverted_index.items() for pos in positions])
    return " ".join(word for pos, word in words)

def search_openalex(query="Non-Destructive Testing", rows=100, date=None):
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per_page": rows,
        "sort": "publication_date:desc"
    }
    if date:
        params["filter"] = f"from_publication_date:{date},to_publication_date:{date}"

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    data = response.json()
    if "results" not in data or not data["results"]:
        return []

    results = []
    for item in data["results"]:
        pub_date = item.get("publication_date", "Not Available")
        if date and pub_date != date:
            continue

        title = item.get("title", "No title")
        abstract = decode_openalex_abstract(item.get("abstract_inverted_index"))
        if abstract and isinstance(abstract, str):
            abstract = abstract.replace("\n", " ").strip()

        authors = [a["author"]["display_name"] for a in item.get("authorships", []) if "author" in a]
        authors_str = ", ".join(authors) if authors else "Not Available"
        link = item.get("primary_location", {}).get("landing_page_url", "Not Available")
        citations = item.get("cited_by_count", 0)
        status = item.get("open_access", {}).get("status", "Not Available")

        results.append({
            "source": "OpenAlex",
            "title": title,
            "abstract": abstract,
            "authors": authors_str,
            "link": link,
            "citations": citations,
            "status": status,
            "pub_date": pub_date
        })
    return results


# ========================
# 2. Semantic Scholar API
# ========================
def search_semantic_scholar(query="Non-Destructive Testing", rows=100, date=None):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": rows,
        "fields": "title,abstract,authors,year,url,citationCount"
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    data = response.json()
    if "data" not in data or not data["data"]:
        return []

    results = []
    for item in data["data"]:
        pub_year = str(item.get("year", "Not Available"))
        # API chỉ có năm → chỉ lọc theo năm nếu cần
        if date and not pub_year.startswith(date.split("-")[0]):
            continue

        title = item.get("title", "No title")
        abstract = item.get("abstract")
        authors = [a["name"] for a in item.get("authors", [])]
        authors_str = ", ".join(authors) if authors else "Not Available"
        link = item.get("url", "Not Available")
        citations = item.get("citationCount", 0)

        results.append({
            "source": "Semantic Scholar",
            "title": title,
            "abstract": abstract if abstract else "Not Available",
            "authors": authors_str,
            "link": link,
            "citations": citations,
            "status": "Not Available",
            "pub_date": pub_year
        })


# ========================
# 3. arXiv API
# ========================
def search_arxiv(query="Non-Destructive Testing", rows=100, date=None):
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": rows,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    root = ET.fromstring(response.content)
    ns = {"arxiv": "http://www.w3.org/2005/Atom"}
    entries = root.findall("arxiv:entry", ns)
    if not entries:
        return []

    results = []
    for entry in entries:
        title = entry.find("arxiv:title", ns).text.strip()
        abstract = entry.find("arxiv:summary", ns).text.strip()
        link = entry.find("arxiv:id", ns).text.strip()
        authors = [a.find("arxiv:name", ns).text for a in entry.findall("arxiv:author", ns)]
        authors_str = ", ".join(authors) if authors else "Not Available"
        pub_date = entry.find("arxiv:published", ns).text[:10]

        if date and pub_date != date:
            continue

        results.append({
            "source": "arXiv",
            "title": title,
            "abstract": abstract,
            "authors": authors_str,
            "link": link,
            "citations": 0,
            "status": "Open Access",
            "pub_date": pub_date
        })
    return results


# ========================
# 4. CrossRef API
# ========================
def search_crossref(query="Non-Destructive Testing", rows=100, date=None):
    url = "https://api.crossref.org/works"
    params = {
        "query": query,
        "rows": rows,
        "sort": "published",
        "order": "desc"
    }
    if date:
        params["filter"] = f"from-pub-date:{date},until-pub-date:{date}"

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    data = response.json()
    if "message" not in data or "items" not in data["message"]:
        return []

    results = []
    for item in data["message"]["items"]:
        date_parts = item.get("issued", {}).get("date-parts", [[None]])
        pub_date = "-".join(str(p) for p in date_parts[0] if p is not None)
        if date and pub_date != date:
            continue

        title = item.get("title", ["No title"])[0]
        abstract = item.get("abstract", "Not Available")
        if abstract and isinstance(abstract, str):
            abstract = abstract.replace("\n", " ").strip()

        authors = []
        for a in item.get("author", []):
            full_name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if full_name:
                authors.append(full_name)
        authors_str = ", ".join(authors) if authors else "Not Available"
        doi = item.get("DOI", "")
        link = f"https://doi.org/{doi}" if doi else "Not Available"
        citations = item.get("is-referenced-by-count", 0)
        status = item.get("publisher", "Not Available")

        results.append({
            "source": "Crossref",
            "title": title,
            "abstract": abstract,
            "authors": authors_str,
            "link": link,
            "citations": citations,
            "status": status,
            "pub_date": pub_date
        })
    return results




