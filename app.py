import streamlit as st
from scholar_search import run_scholar_search
from search_api import search_openalex,  search_arxiv, search_crossref
import pandas as pd
import json
import os
import glob
from dotenv import load_dotenv
from utils import filter_duplicates, save_results_to_json, save_results_to_database,get_latest_json,convert_latest_json_to_gsheet,enrich_with_firecrawl, summarize_filtered_papers, filter_top_papers


# ===================== PAGE CONFIG =====================
st.set_page_config(page_title="Paper Search App", layout="wide")

# -------------------- CONFIG FILE --------------------
RESULTS_DIR = "results"
DATABASE_DIR = "database"
DATABASE_FILE = "papers_db.json"
ENV_PATH = ".env"

if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

if not os.path.exists(ENV_PATH):
    open(ENV_PATH, "a").close()

load_dotenv(ENV_PATH)


# ===================== TABS =====================
tab1, tab2 = st.tabs([
    "🌐 All APIs + Scholar",
    "📁 Danh sách kết quả"
])

# ===================== TAB 1 =====================
with tab1:
    st.subheader("🔹 Tìm kiếm trên All APIs + Google Scholar")

    # Nhập từ khóa và số lượng bài một lần
    keyword_tab1 = st.text_input("Nhập từ khóa tìm kiếm (All APIs + Scholar):", key="keyword_tab1")
    max_results_tab1 = st.number_input("Số lượng bài muốn lấy mỗi nguồn", min_value=1, max_value=200, value=10, key="max_results_tab1")

    if st.button("🔍 Tìm kiếm All APIs + Scholar"):
        if not keyword_tab1.strip():
            st.warning("⚠️ Vui lòng nhập từ khóa tìm kiếm!")
        else:
            with st.spinner("Đang tìm kiếm trên tất cả các API..."):
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
                st.info("⏳ Đang lọc bài báo trùng...")
                unique_results = filter_duplicates(merged_results)

                # 4. Crawl abstract bổ sung bằng Firecrawl
                st.info("⏳ Đang bổ sung abstract...")
                enriched_results = enrich_with_firecrawl(unique_results)

                # 5. Lọc bài không liên quan
                st.info("⏳ Đang lọc bài báo...")
                top_results = filter_top_papers(enriched_results)

                # 6. Tóm tắt abstract
                st.info("⏳ Đang tóm tắt abstract...")
                summarized_results = summarize_filtered_papers(top_results)

                # 7. Lưu kết quả
                saved_file = save_results_to_json(
                    summarized_results,
                    output_dir=RESULTS_DIR,
                    prefix=f"allapi_scholar_{keyword_tab1.replace(' ', '_')}"
                )
                if saved_file:
                    save_results_to_database(saved_file)
                    st.success(f"✅ Đã lưu kết quả enriched vào: {saved_file}")
                convert_latest_json_to_gsheet()


                # 8. Hiển thị kết quả
                latest_file = get_latest_json()
                if latest_file:
                    try:
                        with open(latest_file, "r", encoding="utf-8") as f:
                            today_results = json.load(f)
                        df = pd.DataFrame(today_results)
                        st.subheader("📄 Kết quả bài báo hôm nay")
                        st.dataframe(df)
                    except Exception as e:
                        st.error(f"❌ Lỗi khi đọc file JSON: {e}")
                else:
                    st.info("ℹ️ Chưa có file kết quả hôm nay.")
                    
                # 9. Nút tải file JSON
                st.download_button(
                    label="📥 Tải kết quả JSON",
                    data=json.dumps(today_results, indent=2, ensure_ascii=False),
                    file_name=os.path.basename(saved_file),
                    mime="application/json"
                )




# ===================== TAB 2 =====================
with tab2:
    st.subheader("📂 Danh sách tất cả file kết quả đã lưu")

    files = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")), key=os.path.getmtime, reverse=True)

    if not files:
        st.info("⚠️ Chưa có file kết quả nào được lưu.")
    else:
        for file_path in files:
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path) / 1024  # KB
            st.write(f"**📄 {filename}** ({file_size:.2f} KB)")

            with open(file_path, "rb") as f:
                st.download_button(
                    label=f"📥 Tải {filename}",
                    data=f.read(),
                    file_name=filename,
                    mime="application/json",
                    key=filename
                )
            st.markdown("---")
