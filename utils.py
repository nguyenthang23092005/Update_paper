import os
import glob
import json
import time
import requests
import re
from dateutil import parser
from datetime import datetime, timedelta
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import (
    CellFormat, Color, TextFormat, format_cell_range, set_column_width
)
from googleapiclient.discovery import build
from dotenv import load_dotenv
from google.genai import Client
from google.genai.types import GenerateContentConfig
load_dotenv()
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

client = Client(api_key=GOOGLE_API_KEY)



RESULTS_DIR = "results"
DATABASE_DIR = "database"
DATABASE_FILE = "papers_db.json"
SPREADSHEET_ID = "1snMFj6e4X3YUK_48xXJlb8VhLwcS4vSxb69LgoBcDO4"
creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")


def get_creds():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # Dành cho GitHub Actions
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and os.path.exists(creds_path):
        return Credentials.from_service_account_file(creds_path, scopes=scopes)

    # Dành cho chạy local
    local_path = r"D:\GitHub\Key_gg_sheet\eternal-dynamo-474316-f6-382e31e4ae72.json"
    if os.path.exists(local_path):
        return Credentials.from_service_account_file(local_path, scopes=scopes)

    raise FileNotFoundError("❌ Không tìm thấy file Google credential nào hợp lệ.")

def normalize_key(paper):
    """
    Chuẩn hóa key để so sánh trùng lặp:
    - Ưu tiên DOI (lowercase, bỏ khoảng trắng).
    - Nếu không có DOI → dùng link.
    - Nếu không có link → dùng title.
    """
    doi = (paper.get("doi") or "").strip().lower()
    link = (paper.get("link") or "").strip().lower()
    title = (paper.get("title") or "").strip().lower()

    if doi:
        return doi
    elif link:
        return link
    elif title:
        return title
    return ""

# ==============================
# Lấy file JSON mới nhất
# ==============================
def get_latest_json():
    """
    Lấy file JSON mới nhất theo ngày có dạng: YYYY-MM-DD_allapi_scholar_ndt.json
    """
    pattern = os.path.join(RESULTS_DIR, "*_allapi_scholar_*.json")
    json_files = glob.glob(pattern)

    if not json_files:
        print("⚠️ Không tìm thấy file JSON nào trong thư mục results/")
        return None

    # Lấy ngày từ tên file và chọn ngày mới nhất
    files_with_dates = []
    for f in json_files:
        base = os.path.basename(f)
        try:
            date_part = base.split("_")[0]  # Lấy phần YYYY-MM-DD
            datetime.strptime(date_part, "%Y-%m-%d")  # kiểm tra format
            files_with_dates.append((date_part, f))
        except Exception:
            continue

    if not files_with_dates:
        print("⚠️ Không tìm thấy file JSON hợp lệ theo ngày")
        return None

    # Chọn file có ngày mới nhất
    latest_file = max(files_with_dates, key=lambda x: x[0])[1]
    print(f"📂 File JSON mới nhất theo ngày: {latest_file}")
    return latest_file


# ==============================
# Lưu file JSON với timestamp
# ==============================
def save_results_to_json(data, output_dir=RESULTS_DIR, prefix="allapi_scholar_ndt"):
    """
    Lưu kết quả vào file JSON với tên chứa timestamp.
    Nếu cùng 1 ngày đã có file -> load dữ liệu cũ, merge thêm dữ liệu mới (lọc trùng), rồi ghi đè lại.
    """
    os.makedirs(output_dir, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Tìm file trong ngày hôm nay
    existing_file = None
    for fname in os.listdir(output_dir):
        if fname.startswith(today_str) and fname.endswith(f"{prefix}.json"):
            existing_file = os.path.join(output_dir, fname)
            break

    merged_data = []
    if existing_file:
        try:
            with open(existing_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception as e:
            print(f"⚠️ Lỗi khi đọc file cũ {existing_file}: {e}")
            old_data = []
        merged_data = old_data
    else:
        # Nếu chưa có file -> tạo file mới
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"{timestamp}_{prefix}.json"
        existing_file = os.path.join(output_dir, filename)

    # Merge dữ liệu (lọc trùng theo key chuẩn hóa)
    existing_keys = {normalize_key(item) for item in merged_data if normalize_key(item)}
    new_filtered = [p for p in data if normalize_key(p) not in existing_keys]

    if not new_filtered:
        print("⏩ Không có dữ liệu mới để thêm.")
        return existing_file

    merged_data.extend(new_filtered)

    try:
        with open(existing_file, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        print(f"💾 Đã cập nhật file: {existing_file} (thêm {len(new_filtered)} bài báo)")
        return existing_file
    except Exception as e:
        print(f"❌ Lỗi khi lưu file JSON: {e}")
        return None


# ==============================
# Load Database DOI
# ==============================
def load_database(db_dir=DATABASE_DIR, db_file=DATABASE_FILE):
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, db_file)

    if os.path.exists(db_path):
        try:
            if os.path.getsize(db_path) == 0:
                return []
            with open(db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ File JSON bị lỗi hoặc rỗng: {db_path}, tạo database mới")
            return []
    else:
        return []



def save_database(data, db_dir=DATABASE_DIR, db_file=DATABASE_FILE):
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, db_file)

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Database đã được cập nhật: {db_path}")

# ==============================
# Cập nhật Database (lưu Title + DOI)
# ==============================
def save_results_to_database(result_file, db_dir=DATABASE_DIR, db_file=DATABASE_FILE):
    """
    Đọc kết quả từ file JSON và lưu vào database.
    Chuẩn hóa key (doi/link/title) và loại bỏ trùng lặp.
    """
    if not os.path.exists(result_file):
        print(f"❌ File kết quả không tồn tại: {result_file}")
        return False

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            results = json.load(f)
    except Exception as e:
        print(f"❌ Lỗi khi đọc file kết quả {result_file}: {e}")
        return False

    db_data = load_database(db_dir, db_file)
    db_dict = {normalize_key(item): item for item in db_data if normalize_key(item)}

    new_count = 0
    for paper in results:
        key = normalize_key(paper)
        if key and key not in db_dict:
            db_dict[key] = {
                "title": paper.get("title", "Untitled"),
                "doi": paper.get("doi", paper.get("link", ""))
            }
            new_count += 1

    save_database(list(db_dict.values()), db_dir, db_file)
    print(f"✅ Đã thêm {new_count} bài báo mới vào database từ {result_file}")
    return True



# ==============================
# Lọc bài báo trùng 
# ==============================
def filter_duplicates(new_results, results_dir=RESULTS_DIR, db_dir=DATABASE_DIR, db_file=DATABASE_FILE):
    """
    Lọc trùng các bài báo mới bằng key chuẩn hóa (doi/link/title).
    - Nếu file mới nhất là hôm nay → không lọc.
    - Nếu file mới nhất là hôm qua → lọc theo hôm qua.
    - Nếu không phải hôm nay và không phải hôm qua → lọc theo database.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 🔹 Lấy file JSON mới nhất
    latest_file = get_latest_json()
    if not latest_file:
        return new_results

    # 🔹 Đọc dữ liệu file mới nhất
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            old_results = json.load(f)
    except Exception as e:
        print(f"❌ Lỗi khi đọc file {latest_file}: {e}")
        return new_results

    old_dates = {paper.get("pub_date", "") for paper in old_results}

    # ✅ File hôm nay → không lọc
    if today_str in old_dates:
        print("⏩ File mới nhất đã là hôm nay -> Không lọc trùng.")
        return new_results

    # ✅ Không phải hôm nay → lọc
    # Nếu là hôm qua → lọc theo hôm qua
    if yesterday_str in old_dates:
        old_keys = {normalize_key(p) for p in old_results if normalize_key(p)}
        filtered_results = [p for p in new_results if normalize_key(p) not in old_keys]
        removed_count = len(new_results) - len(filtered_results)
        print(f"🗑️ Đã loại bỏ {removed_count} bài báo trùng với hôm qua.")
        return filtered_results

    # ✅ Không phải hôm qua → lọc theo database
    db_path = os.path.join(db_dir, db_file)
    if not os.path.exists(db_path):
        print("⚠️ Không tìm thấy database -> Trả về toàn bộ dữ liệu mới.")
        return new_results

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            db_data = json.load(f)
            db_keys = {normalize_key(item) for item in db_data if normalize_key(item)}
    except Exception as e:
        print(f"❌ Lỗi khi đọc database {db_path}: {e}")
        return new_results

    filtered_results = [p for p in new_results if normalize_key(p) not in db_keys]
    removed_count = len(new_results) - len(filtered_results)
    print(f"🗑️ Đã loại bỏ {removed_count} bài báo trùng với database.")
    return filtered_results


def tidy_up_sheet_auto(spreadsheet_id, sheet_name=None):
    # 1. Kết nối Google Sheets API
    creds = get_creds()
    service = build("sheets", "v4", credentials=creds)

    # 2. Lấy metadata sheet
    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = sheet_metadata.get("sheets", [])

    if not sheets:
        print("⚠️ File Google Sheets trống, không có sheet nào.")
        return

    # 3. Xác định sheet_id
    sheet_id = None
    if sheet_name:
        for s in sheets:
            if s["properties"]["title"] == sheet_name:
                sheet_id = s["properties"]["sheetId"]
                break
    if not sheet_id:
        sheet_id = sheets[0]["properties"]["sheetId"]
        sheet_name = sheets[0]["properties"]["title"]
        print(f"⚠️ Không tìm thấy sheet bạn chỉ định. Sử dụng sheet đầu tiên: '{sheet_name}'")

    # 4. Lấy dữ liệu hiện tại để xác định số hàng và cột
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=sheet_name
    ).execute()
    values = result.get("values", [])
    num_rows = len(values) if values else 1
    num_cols = max(len(row) for row in values) if values else 1

    # 5. Tính chiều rộng cột dựa trên nội dung
    column_widths = [0] * num_cols
    for row in values:
        for col_index in range(num_cols):
            cell_value = row[col_index] if col_index < len(row) else ""
            column_widths[col_index] = max(column_widths[col_index], len(str(cell_value)))

    # 6. Tạo danh sách requests
    requests = [
        # Căn giữa header
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "textFormat": {"bold": True}
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment)"
            }
        },
        # Bật wrap text toàn sheet
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy"
            }
        },
        # Bo viền toàn bảng
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": num_rows,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols
                },
                "top": {"style": "SOLID", "width": 1},
                "bottom": {"style": "SOLID", "width": 1},
                "left": {"style": "SOLID", "width": 1},
                "right": {"style": "SOLID", "width": 1},
                "innerHorizontal": {"style": "SOLID", "width": 1},
                "innerVertical": {"style": "SOLID", "width": 1}
            }
        }
    ]

    # 7. Resize cột dựa trên nội dung
    for col_index, max_len in enumerate(column_widths):
        width_pixels = max(80, min(max_len * 10, 400))  # min 80px, max 400px
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_index,
                    "endIndex": col_index + 1
                },
                "properties": {"pixelSize": width_pixels},
                "fields": "pixelSize"
            }
        })

    # 8. Đặt chiều cao tất cả hàng ~10cm (10cm ≈ 378px)
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "ROWS",
                "startIndex": 0,
                "endIndex": num_rows
            },
            "properties": {"pixelSize": 378},
            "fields": "pixelSize"
        }
    })

    # 9. Gửi batchUpdate
    body = {"requests": requests}
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

    print(f"✅ Đã căn chỉnh và định dạng sheet '{sheet_name}' thành công!")



def append_json_to_gsheet(df, date_str):
    """Thêm hoặc ghi đè dữ liệu JSON vào Google Sheet, không đè sang ngày khác"""
    creds = get_creds()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    all_values = sheet.get_all_values()
    last_col = chr(ord('A') + len(df.columns) - 1)

    # Tìm xem ngày đã tồn tại chưa
    existing_row = None
    for idx, row in enumerate(all_values):
        if row and row[0].startswith(f"📅 Ngày {date_str}"):
            existing_row = idx + 1  # gspread index từ 1
            break

    if existing_row:
        print(f"ℹ️ Ngày {date_str} đã tồn tại trên sheet. Ghi đè dữ liệu.")
        start_row = existing_row

        # Tìm row cuối cùng của dữ liệu ngày hôm nay
        end_row = start_row + 1
        while end_row <= len(all_values):
            if all_values[end_row-1] and all_values[end_row-1][0].startswith("📅 Ngày"):
                break
            end_row += 1

        # Xóa toàn bộ vùng dữ liệu cũ
        sheet.delete_rows(start_row, end_row - 1)

        next_row = start_row
    else:
        next_row = len(all_values) + 3 if len(all_values) > 0 else 1  # thêm 2 dòng trống

    # 🗓️ Ghi tiêu đề ngày
    sheet.update_cell(next_row, 1, f"📅 Ngày {date_str}")
    try:
        sheet.merge_cells(next_row, 1, next_row, len(df.columns))
    except Exception:
        pass

    # Format tiêu đề ngày
    try:
        day_fmt = CellFormat(
            textFormat=TextFormat(bold=True, foregroundColor=Color(1, 0, 0), fontSize=13),
            horizontalAlignment='CENTER',
            backgroundColor=Color(0.85, 0.93, 1.0)
        )
        format_cell_range(sheet, f"A{next_row}:{last_col}{next_row}", day_fmt)
    except Exception:
        pass

    # 🧩 Ghi header và dữ liệu
    data_to_insert = [df.columns.values.tolist()] + df.values.tolist()
    sheet.update(f"A{next_row + 1}", data_to_insert)

    # Format header
    try:
        header_fmt = CellFormat(
            textFormat=TextFormat(bold=True),
            horizontalAlignment='CENTER',
            backgroundColor=Color(0.95, 0.95, 0.95)
        )
        format_cell_range(sheet, f"A{next_row + 1}:{last_col}{next_row + 1}", header_fmt)
    except Exception:
        pass

    # Căn giữa dữ liệu
    try:
        data_end_row = next_row + len(df) + 1
        center_fmt = CellFormat(
            textFormat=TextFormat(bold=False),
            horizontalAlignment='CENTER'
        )
        format_cell_range(sheet, f"A{next_row + 2}:{last_col}{data_end_row}", center_fmt)
    except Exception:
        pass

    # Auto-width cho các cột
    try:
        for i in range(1, len(df.columns) + 1):
            set_column_width(sheet, i, 160)
    except Exception:
        pass

    print(f"✅ Đã thêm/ghi đè dữ liệu ngày {date_str} vào Google Sheet")


def convert_latest_json_to_gsheet():
    """Đọc file JSON mới nhất (hôm nay) và nối vào sheet"""
    latest_file = get_latest_json()
    if not latest_file:
        print("⚠️ Không tìm thấy file JSON.")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    base = os.path.basename(latest_file)
    file_date = base.split("_")[0]

    if file_date != today_str:
        print("ℹ️ File JSON mới nhất không phải của hôm nay.")
        return

    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)
    append_json_to_gsheet(df, today_str)
    tidy_up_sheet_auto(SPREADSHEET_ID)
    
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

def fetch_abstract_and_pubdate_firecrawl(url):
    """
    Dùng Firecrawl Scrape API, trích xuất toàn bộ abstract và pubdate.
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
        return {"abstract": "Not Available", "pubdate": "Not Available"}

    content = data.get("data", {}).get("markdown", "")
    if not content:
        return {"abstract": "Not Available", "pubdate": "Not Available"}

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
    
    # --- Trích xuất pubdate từ markdown ---
    pubdate = "Not Available"
    # tìm các mẫu như "Published: 2025-01-20" hoặc "Ngày xuất bản: 20 Jan 2025"
    date_patterns = [
        r'published[:\s]+(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
        r'published[:\s]+(\d{1,2}\s\w+\s\d{4})', # DD Month YYYY
        r'ngày xuất bản[:\s]+(\d{1,2}\s\w+\s\d{4})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            try:
                pubdate = str(parser.parse(match.group(1)).date())
                break
            except:
                continue
    return {"abstract": abstract, "pubdate": pubdate}


def enrich_with_firecrawl(results):
    """
    Nhận danh sách results (các bài báo đã crawl từ OpenAlex, Arxiv, etc.)
    Nếu abstract = 'Not Available' hoặc pubdate = 'Not Available' thì dùng Firecrawl lấy.
    """
    for paper in results:
        needs_fetch = (
            (not paper.get("abstract") or paper["abstract"] == "Not Available") or
            (not paper.get("pubdate") or paper["pubdate"] == "Not Available")
        )
        if needs_fetch and paper.get("link") != "Not Available":
            print(f"Fetching abstract & pubdate with Firecrawl for: {paper['title']}")
            data = fetch_abstract_and_pubdate_firecrawl(paper["link"])
            paper["abstract"] = data["abstract"]
            paper["pubdate"] = data["pubdate"]
            time.sleep(6)  # tránh bị rate-limit
    return results


def evaluate_paper_combined(abstract, keywords):
    """
    Kiểm tra liên quan và đánh giá chất lượng bài báo trong 1 bước.

    Returns:
        dict: {
            "related": bool,
            "score": int (0-10)
        }
    """
    prompt = f"""
    You are an expert in scientific paper evaluation.

    Task: 
    1. Determine if the following abstract is related to the topic: {", ".join(keywords)}. Answer only YES or NO.
    2. If it is related, rate its quality on a scale from 0 (very poor) to 10 (excellent). 
       If it is not related, give a score of 0.
    Only respond in the format: YES/NO and score as an integer (e.g., YES 7 or NO 0).

    Abstract:
    {abstract}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=GenerateContentConfig(temperature=0)
        )
        text = response.text.strip().upper()
        related = "YES" in text
        score_match = re.search(r'\d+', text)
        score = int(score_match.group()) if score_match else 0
        score = min(max(score, 0), 10)
        return {"related": related, "score": score}
    except Exception as e:
        print(f"[Gemini Error - Combined Evaluation] {e}")
        return {"related": False, "score": 0}


# =========================================
# Hàm lọc bài báo không có abstract hoặc không liên quan
# =========================================
def filter_top_papers(results, keywords=["Non-Destructive Testing"], top_n=10):
    """
    Lọc các bài báo liên quan và chọn ra top N bài báo hay nhất dựa trên score AI.

    Parameters:
        results (list): Danh sách bài báo, mỗi bài báo là dict với 'abstract' và 'title'.
        keywords (list): Danh sách từ khóa liên quan đến chủ đề nghiên cứu.
        top_n (int): Số bài báo muốn giữ lại (mặc định 10).

    Returns:
        list: Danh sách bài báo đã lọc và sắp xếp theo chất lượng.
    """
    scored_papers = []

    for paper in results:
        title = paper.get("title", "Untitled")
        abstract = paper.get("abstract", "").strip()

        if not abstract or abstract.lower() == "not available":
            continue

        print(f"Checking relevance and quality for: {title}")
        # Gọi hàm đánh giá kết hợp liên quan + điểm chất lượng
        evaluation = evaluate_paper_combined(abstract, keywords)

        if evaluation["related"]:
            paper["score"] = evaluation["score"]
            scored_papers.append(paper)
        else:
            print(f"❌ Paper '{title}' is not relevant.")

        time.sleep(16)  # tránh bị rate-limit Gemini API

    # Sắp xếp theo score giảm dần và chỉ lấy top N
    top_papers = sorted(scored_papers, key=lambda x: x["score"], reverse=True)[:top_n]
    return top_papers


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