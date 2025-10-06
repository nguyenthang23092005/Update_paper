import requests
import json
import os
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import time
from google.genai import Client
from google.genai.types import GenerateContentConfig
load_dotenv()
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

client = Client(api_key=GOOGLE_API_KEY)



RESULTS_DIR = "results"


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


# ========================
# Merge & Save to One File
# ========================
def merge_and_save(all_results, filename):
    """
    Gộp tất cả kết quả vào 1 file và loại bỏ trùng lặp.
    Trùng lặp được xác định bởi: title + authors hoặc link.
    """
    unique = {}
    for paper in all_results:
        key = (paper['title'].lower().strip(), paper['authors'].lower().strip(), paper['link'].lower().strip())
        if key not in unique:
            unique[key] = paper

    final_results = list(unique.values())

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    filepath = os.path.join(RESULTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(final_results)} unique papers to {filepath}")

def fetch_abstract_firecrawl(url):
    """
    Dùng Firecrawl Scrape API, trích xuất toàn bộ abstract (nhiều dòng).
    """
    if not FIRECRAWL_API_KEY:
        raise ValueError("Thiếu FIRECRAWL_API_KEY, hãy set trong biến môi trường.")

    api_url = "https://api.firecrawl.dev/v1/scrape"
    headers = {"Authorization": f"Bearer {FIRECRAWL_API_KEY}"}
    payload = {
        "url": url,
        "formats": ["markdown"],  
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[Firecrawl Error] {e}")
        return "Not Available"

    content = data.get("data", {}).get("markdown", "")
    if not content:
        return "Not Available"

    lines = content.splitlines()
    abstract_lines = []
    capture = False

    for line in lines:
        low = line.lower().strip()
        # Bắt đầu từ Abstract / Tóm tắt
        if "abstract" in low or "tóm tắt" in low:
            capture = True
            continue
        # Nếu gặp Keywords / Introduction thì dừng lại
        if capture and ("keywords" in low or "introduction" in low or "references" in low):
            break
        if capture:
            abstract_lines.append(line.strip())

    abstract = " ".join(abstract_lines).strip()
    return abstract if abstract else "Not Available"


def enrich_with_firecrawl(results):
    """
    Nhận danh sách results (các bài báo đã crawl từ OpenAlex, Arxiv, etc.)
    Nếu abstract = 'Not Available' thì dùng Firecrawl lấy abstract từ link.
    """
    for paper in results:
        if (not paper.get("abstract") or paper["abstract"] == "Not Available") and paper.get("link") != "Not Available":
            print(f"Fetching abstract with Firecrawl for: {paper['title']}")
            paper["abstract"] = fetch_abstract_firecrawl(paper["link"])
            time.sleep(6)
    return results


def check_relevance_with_genai(abstract, keywords):
    """
    Kiểm tra abstract có liên quan tới các từ khóa nghiên cứu (vd: NDT) hay không.
    Trả về True/False.

    Parameters:
        abstract (str): Abstract của bài báo.
        keywords (list): Danh sách từ khóa liên quan đến chủ đề nghiên cứu.

    Returns:
        bool: True nếu bài báo liên quan, False nếu không.
    """
    prompt = f"""
    You are an expert in scientific paper classification.

    Task: Determine whether the following abstract is related to the topic: {", ".join(keywords)}.
    Answer only with "YES" or "NO".

    Abstract:
    {abstract}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt,
            config=GenerateContentConfig(temperature=0)
        )
        answer = response.text.strip().upper()
        return "YES" in answer
    except Exception as e:
        print(f"[Gemini Error - Relevance Check] {e}")
        return False


# =========================================
# Hàm lọc bài báo không có abstract hoặc không liên quan
# =========================================
def filter_irrelevant_papers(results, keywords=["Non-Destructive Testing"]):
    """
    Lọc các bài báo không có abstract hoặc không liên quan đến nghiên cứu.

    Parameters:
        results (list): Danh sách bài báo, mỗi bài báo là dict với 'abstract' và 'title'.
        keywords (list): Danh sách từ khóa liên quan đến chủ đề nghiên cứu.

    Returns:
        list: Danh sách bài báo đã lọc.
    """
    filtered_papers = []

    for paper in results:
        title = paper.get("title", "Untitled")
        abstract = paper.get("abstract", "").strip()

        # Bỏ qua nếu không có abstract
        if not abstract or abstract.lower() == "not available":
            continue

        print(f"Checking relevance for: {title}")
        is_relevant = check_relevance_with_genai(abstract, keywords)

        if is_relevant:
            filtered_papers.append(paper)
        else:
            print(f"❌ Paper '{title}' is not relevant.")
        time.sleep(16)  
    return filtered_papers


# =========================================
# Hàm tóm tắt abstract
# =========================================
def summarize_with_genai(abstract):
    """
    Dùng Gemini API để tóm tắt abstract thành 3-4 câu.

    Parameters:
        abstract (str): Abstract của bài báo.

    Returns:
        str: Tóm tắt abstract.
    """
    prompt = f"""
    Summarize the following abstract in 3-4 concise sentences.
    Use simple and clear academic English.

    Abstract:
    {abstract}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # Model chất lượng cao
            contents=prompt,
            config=GenerateContentConfig(temperature=0.3)
        )
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini Error - Summarization] {e}")
        return "Tóm tắt không thành công"


# =========================================
# Hàm tóm tắt toàn bộ danh sách bài đã lọc
# =========================================
def summarize_filtered_papers(filtered_papers):
    """
    Tóm tắt abstract của tất cả các bài báo đã lọc.

    Parameters:
        filtered_papers (list): Danh sách bài báo đã lọc, mỗi bài chứa 'abstract' và 'title'.

    Returns:
        list: Danh sách bài báo với key 'summary' chứa tóm tắt abstract.
    """
    for paper in filtered_papers:
        abstract = paper.get("abstract", "").strip()
        title = paper.get("title", "Untitled")
        
        if abstract:
            print(f"Summarizing abstract for: {title}")
            paper["summary"] = summarize_with_genai(abstract)
            time.sleep(16)  

    return filtered_papers

