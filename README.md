# Xây Dựng Pipeline Tự Động Thu Thập & Dóng Hàng Song Ngữ Hán Nôm – Quốc Ngữ

Dự án đồ án môn học Xử lý Ngôn ngữ Tự nhiên (Natural Language Processing) - Khoa Công nghệ Thông tin, Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM.

---

## 👥 Thông Tin Nhóm Thực Hiện
- **24120068** - Nguyễn Phúc Khang (Nhóm trưởng) - `24120068@student.hcmus.edu.vn`
- **24120151** - Phạm Minh Trọng - `24120151@student.hcmus.edu.vn`
- **24120103** - Hoàng Trọng Nghĩa - `24120103@student.hcmus.edu.vn`

---

## 📖 Giới Thiệu Dự Án
Dự án tập trung giải quyết bài toán xây dựng ngữ liệu song ngữ tự động (Automated Parallel Corpus Construction) giữa văn bản **Hán Nôm** cổ và bản dịch âm **Quốc ngữ** từ các tài liệu lịch sử scan chất lượng cao dạng PDF (cụ thể là bộ sách tôn giáo phân loại **T1**: *Sách Dạy Đấng Làm Người Sửa Mình*, Tập 1 & Tập 2).

Hệ thống được thiết kế theo chuẩn **Rubric v2.1** với mức độ tự động hóa tối đa:
1. **Trích xuất ảnh chuẩn ấn bản:** Cắt PDF ở độ phân giải 300 DPI bằng `pdftoppm`.
2. **Phân loại layout T1:** Tự động định vị các trang Quốc ngữ (đọc xuôi $1 \to 318$) và Hán Nôm (đọc ngược $636 \to 319$), sinh file ánh xạ chuẩn `_image_map.json`.
3. **Động cơ OCR thống nhất (OCREngine):**
   - Hán Nôm: Tích hợp API Kim Hán Nôm với cơ chế trích xuất tối ưu `structure-classification` (tiết kiệm 50% quota), lưu bộ nhớ đệm SQLite (`ocr_cache.db`).
   - Quốc ngữ: Hỗ trợ OpenAI-compatible Vision API (GPT-4o/Claude/Qwen) kết hợp phân đoạn OpenCV hoặc offline Tesseract OCR (`vie.traineddata`).
   - Xuất dữ liệu đánh nhãn PPOCRLabel chuẩn tuyệt đối: `Label.txt` (4 điểm toạ độ góc) và `fileState.txt` (tất cả dòng `state = 1`).
4. **Xử lý ghép câu xuyên trang (Cross-page Sentence Stitching):** Nối các câu/từ bị ngắt do đổi trang trước khi phân tách câu, gán đúng `img_id` của trang mở đầu.
5. **Dóng hàng ngữ âm quy hoạch động (Phonetic DP Alignment):** Kết hợp động cơ từ điển SQLite 329.000 mục từ (`data/dict.db`) và thuật toán Needleman-Wunsch tính toán text_diff và toạ độ ký tự Unicode (code point slices).
6. **Xuất bản dữ liệu chuẩn Rubric:**
   - `<Tên sách>.csv`: UTF-8 with BOM (`utf-8-sig`), chống lỗi font và lệch cột trên Excel/Google Sheets.
   - `<Tên sách>.xlsx`: Định dạng RichText đa màu trong từng ô tính (Đen = Khớp, Đỏ = `error`, Vàng = `warn`).
   - Tự động đánh giá độ tương đồng theo công thức chuẩn:
     $$\text{Độ tương đồng (\%)} = \left(1 - \frac{\text{unmatched\_chars (red)}}{\text{total\_nom\_chars}}\right) \times 100 \ge 95\%$$
7. **Đóng gói tự động:** Tự động xác thực toàn vẹn dữ liệu và đóng gói nộp bài thành file `<MSSV1_MSSV2_MSSV3>.zip`.

---

## 🛠️ Cài Đặt Môi Trường

### Yêu Cầu Hệ Thống
- Hệ điều hành: Linux (khuyến nghị Ubuntu 22.04 LTS / 24.04 LTS), macOS hoặc Windows (WSL2).
- Python: Phiên bản >= 3.10 (Đã kiểm thử toàn diện trên Python 3.14 / 3.11).
- Các gói công cụ hệ thống: `poppler-utils` (cho `pdftoppm`), `tesseract-ocr`.

```bash
# Cài đặt công cụ hệ thống trên Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr
```

### Cài Đặt Thư Viện Python (Pinned Dependencies)
```bash
# Tạo môi trường ảo (khuyến nghị)
python3 -m venv .venv
source .venv/bin/activate

# Cài đặt chính xác các phiên bản thư viện đã kiểm thử
pip install -r requirements.txt
```

---

## 🚀 Hướng Dẫn Sử Dụng Nhanh

### 1. Khởi Tạo Cơ Sở Dữ Liệu Từ Điển Tra Cứu Siêu Tốc (< 6s)
```bash
python3 src/dict_engine/index_dict.py
```

### 2. Chạy Toàn Bộ Pipeline Tự Động (Từ A đến Z)
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage all
```

### 3. Chạy Từng Giai Đoạn Riêng Lẻ
- **Giai đoạn 1 & 2: Cắt ảnh và phân loại:**
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage slice
  ```
- **Giai đoạn 3: Chạy OCR sinh `Label.txt` và `fileState.txt`:**
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage ocr
  ```
- **Giai đoạn 4: Ghép câu xuyên trang, dóng hàng DP và xuất CSV / Excel:**
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage align
  ```
- **Giai đoạn 5: Kiểm tra validation và đóng gói bài nộp:**
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage package
  ```

---

## 📂 Cấu Trúc Thư Mục Dự Án
```
sinom-midterm/
├── configs/                   # Cấu hình API tokens và model
│   ├── kim_token.txt          # Token truy cập API Kim Hán Nôm
│   └── openai_config.json     # Cấu hình API OpenAI-compatible (tuỳ chọn)
├── data/
│   ├── entries/               # 7 nguồn từ điển nguyên bản
│   ├── dict.db                # Cơ sở dữ liệu từ điển SQLite (329k+ từ)
│   ├── ocr_cache.db           # SQLite cache lưu trữ kết quả OCR
│   ├── tessdata/              # Dữ liệu offline Tesseract tiếng Việt (vie.traineddata)
│   └── processed/             # Thư mục chứa dữ liệu sách sau xử lý
├── docs/                      # Tài liệu đề bài và rubric quy định (Rules v2.1)
├── scripts/
│   ├── run_pipeline.py        # CLI điều phối toàn bộ quy trình
│   └── package_submission.py  # Đóng gói và kiểm định file nộp bài
├── src/
│   ├── dict_engine/           # Động cơ lập chỉ mục và tra cứu từ điển
│   ├── preprocessor/          # Cắt ảnh PDF 300 DPI, phân loại và lập map
│   ├── ocr/                   # Động cơ OCR thống nhất (Kim Hán Nôm + OpenAI/Tesseract)
│   ├── segmenter/             # Làm sạch văn bản, ghép câu xuyên trang và tách câu
│   ├── aligner/               # Thuật toán quy hoạch động dóng hàng Nôm - Quốc ngữ
│   └── evaluator/             # Xuất file CSV, Excel tô 3 màu và đo độ tương đồng
├── requirements.txt           # Thư viện phụ thuộc được cố định (pinned)
├── USER_GUIDE.md              # Hướng dẫn chi tiết chạy trên máy mới
└── README.md                  # Tài liệu giới thiệu tổng quan
```

