import os
import json
from google.oauth2.service_account import Credentials  # chú ý là service_account, không phải Credentials

# Lấy đường dẫn từ biến môi trường
creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

# In ra đường dẫn
print(f"Đang dùng file JSON credentials: {creds_path}")

# Kiểm tra file có tồn tại không
if not os.path.exists(creds_path):
    print("❌ File không tồn tại!")
else:
    print("✅ File tồn tại, đang thử đọc nội dung JSON...")

    # Đọc thử JSON để check
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print("✅ JSON hợp lệ, các key chính: ", list(data.keys()))
    except json.JSONDecodeError as e:
        print("❌ Lỗi JSON:", e)

    # Thử tạo Credentials
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        print("✅ Credentials tạo thành công")
    except Exception as e:
        print("❌ Lỗi khi tạo Credentials:", e)
