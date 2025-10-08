from scholar_search import run_scholar_search
from search_api import search_openalex,  search_arxiv, search_crossref
from dotenv import load_dotenv
from utils import filter_duplicates, save_results_to_json, save_results_to_database,convert_latest_json_to_gsheet,enrich_with_firecrawl, summarize_filtered_papers, filter_top_papers,convert_latest_json_to_gdoc
import os


RESULTS_DIR = "results"
DATABASE_DIR = "database"
DATABASE_FILE = "papers_db.json"
ENV_PATH = ".env"

if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

if not os.path.exists(ENV_PATH):
    open(ENV_PATH, "a").close()

load_dotenv(ENV_PATH)

keyword_tab1 = "Non-Destructive Testing"
max_results_tab1 = 30


# 1. Gọi các API
openalex_res = search_openalex(query=keyword_tab1, rows=max_results_tab1)
arxiv_res = search_arxiv(query=keyword_tab1, rows=max_results_tab1)
crossref_res = search_crossref(query=keyword_tab1, rows=max_results_tab1)

# Google Scholar
scholar_data = run_scholar_search(keyword_tab1, max_results_tab1)

# 2. Hợp nhất kết quả
merged_results = []
for res in [openalex_res, arxiv_res, crossref_res, scholar_data]:
    merged_results.extend(res)

# 3. Lọc trùng 
print("⏳ Đang lọc bài báo trùng...")
unique_results = filter_duplicates(merged_results)

# 4. Crawl abstract bổ sung bằng Firecrawl
print("⏳ Đang bổ sung abstract...")
enriched_results = enrich_with_firecrawl(unique_results)

# 5. Lọc bài không liên quan
print("⏳ Đang lọc bài báo...")
top_results = filter_top_papers(enriched_results)

# 6. Tóm tắt abstract
print("⏳ Đang tóm tắt abstract...")
summarized_results = summarize_filtered_papers(top_results)

# 7. Lưu kết quả
saved_file = save_results_to_json(
    summarized_results,
    output_dir=RESULTS_DIR,
    prefix=f"allapi_scholar_{keyword_tab1.replace(' ', '_')}"
)
if saved_file:
    save_results_to_database(saved_file)
    print(f"✅ Đã lưu kết quả enriched vào: {saved_file}")
# 8. Lưu trên gg sheet
convert_latest_json_to_gsheet()
convert_latest_json_to_gdoc()