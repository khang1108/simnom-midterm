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

Hệ thống được thiết kế theo **Quy định đồ án v2.4** với mức độ tự động hóa tối đa:
1. **Trích xuất ảnh:** Cắt PDF bằng `pdftoppm` ở 72 DPI (xấp xỉ độ phân giải ảnh gốc nhúng trong PDF, 800×1135; cắt 300 DPI chỉ phóng to ảnh ~5,5 lần). Trang trùng được loại bằng `qpdf` thành `<Tên sách>_updated.pdf`.
2. **Phân loại layout T1:** Khoảng trang của từng thư mục (`vi`, `ch`, `intro`, `ref`, `toc`, `blank`, `misc`, `missing/ch`) và cách ghép cặp trang Quốc ngữ (đọc xuôi) – Hán Nôm (đọc ngược) khai báo trong `configs/books_structure.json`, sinh file ánh xạ `_image_map.json` và tự kiểm định.
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
- Các gói công cụ hệ thống: `poppler-utils` (cho `pdftoppm`), `qpdf`, `tesseract-ocr` + dữ liệu tiếng Việt.

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y poppler-utils qpdf tesseract-ocr tesseract-ocr-vie
# Arch Linux
sudo pacman -S poppler qpdf tesseract tesseract-data-vie
```

### Chuẩn Bị Dữ Liệu (không nằm trong git)
```
data/
├── T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf
├── T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2).pdf
├── entries/      # btcn, dv, dnqatv_wikisource, hannom_rcv, hvdic, unihan, cjkvi_variants (.jsonl)
└── tessdata/     # vie.traineddata (chép từ /usr/share/tessdata hoặc /usr/share/tesseract-ocr/*/tessdata)
configs/kim_token.txt   # Bearer token Kim Hán Nôm (cookie `token` sau khi đăng nhập; hết hạn sau 1 giờ)
```

> ⚠️ API Kim Hán Nôm giới hạn 25 lượt/phút, 50 lượt/giờ, 200 lượt/ngày, 600 lượt/tuần (mỗi trang ≥ 2 lượt).
> Kết quả OCR được cache trong `data/ocr_cache.db`, nên khi hết quota/token chỉ cần chạy lại `--stage ocr`.

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
- **Giai đoạn 1 & 2: Cắt ảnh, phân loại, `_updated.pdf` và `_image_map.json`** (tương đương `python3 scripts/prepare_books.py --book tap1`):
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage slice
  ```
- **Giai đoạn 3: Chạy OCR sinh `Label.txt` và `fileState.txt`:**
  ```bash
  python3 scripts/run_pipeline.py --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" --stage ocr
  ```
  OCR Quốc ngữ chính dùng **Qwen3-VL-8B-Instruct** (vLLM, OpenAI-compatible): Tesseract chỉ tìm box dòng, VLM đọc lại
  từng dòng (Tập 1: âm tiết sai 642 → 147, similarity 92,8% → 93,4%). Ví dụ với vLLM trên GPU server qua SSH tunnel:
  ```bash
  vllm serve Qwen/Qwen3-VL-8B-Instruct --port 8120 --max-model-len 8192 --limit-mm-per-prompt '{"image":1}'   # trên server
  ssh -N -L 8120:127.0.0.1:8120 <server> &                                                                    # trên máy local
  python3 scripts/run_pipeline.py --pdf "..." --stage ocr \
      --openai-key EMPTY --openai-base-url http://localhost:8120/v1 --openai-model Qwen/Qwen3-VL-8B-Instruct
  ```
  Vế Nôm: `configs/pua_to_unicode.csv` (ký tự riêng PUA của Kim → Unicode) và `configs/kim_glyph_fix.csv`
  (chữ Kim nhận nhầm hình nhất quán, đã đối chiếu ảnh + IDS, vd. 𠯇/吔 → 吧 "và") được áp dụng ngay khi ghi `Label.txt`.
  Sau OCR, bước **ROVER** chọn lại từng từ Quốc ngữ giữa bản Qwen, bản Tesseract và lượt Qwen thứ hai (ảnh ×2): chỉ lấy
  bản phụ khi nó là âm đọc của chữ Nôm trên trang đối ứng còn bản chính thì không (sửa d/đ, ă/â/ơ/ư).
  Âm theo quy ước Nôm Công giáo của sách (tên riêng Giê-su 支秋, I-ghe-rê-gia 衣計移加…; 識=sấm, 諫=khiêm…) nằm trong
  `configs/catholic_nom_readings.csv`. Lỗi bản scan khai báo trong `configs/books_structure.json`: trang lộn ngược
  (`rotate_180`) và trang Nôm đặt sai chỗ (các đoạn `range` một–hai trang).
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
├── docs/                      # Tài liệu đề bài và quy định đồ án (đến v2.4)
├── scripts/
│   ├── run_pipeline.py        # CLI điều phối toàn bộ quy trình
│   ├── prepare_books.py       # Cắt ảnh + phân loại + image_map theo configs/books_structure.json
│   ├── run_official_align.py  # Dóng hàng hybrid (BookAligner + tools/ocr-nom-align)
│   └── package_submission.py  # Đóng gói và kiểm định file nộp bài
├── src/
│   ├── dict_engine/           # Động cơ lập chỉ mục và tra cứu từ điển
│   ├── preprocessor/          # Tiện ích tiền xử lý ảnh (tăng cường, phân loại trang trắng)
│   ├── ocr/                   # Động cơ OCR thống nhất (Kim Hán Nôm + OpenAI/Tesseract)
│   ├── segmenter/             # Làm sạch văn bản, ghép câu xuyên trang và tách câu
│   ├── aligner/               # Thuật toán quy hoạch động dóng hàng Nôm - Quốc ngữ
│   └── evaluator/             # Xuất file CSV, Excel tô 3 màu và đo độ tương đồng
├── requirements.txt           # Thư viện phụ thuộc được cố định (pinned)
├── USER_GUIDE.md              # Hướng dẫn chi tiết chạy trên máy mới
└── README.md                  # Tài liệu giới thiệu tổng quan
```

