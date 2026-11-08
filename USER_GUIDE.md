# HƯỚNG DẪN VẬN HÀNH TOÀN BỘ QUY TRÌNH (USER GUIDE)
**Dự án:** Xây dựng Ngữ liệu Song ngữ Hán Nôm – Quốc ngữ Tự động  
**Quy chuẩn áp dụng:** [Rules] - v2.1.pdf  
**Nhóm thực hiện:**
- Nguyễn Phúc Khang (MSSV: 24120068 - Trưởng nhóm)
- Phạm Minh Trọng (MSSV: 24120151)
- Hoàng Trọng Nghĩa (MSSV: 24120103)

---

## 1. Môi Trường Vận Hành (Tested Environment)
Dự án đã được triển khai, kiểm thử và chạy thực nghiệm trên môi trường tiêu chuẩn sau:
- **Hệ điều hành (OS):** Linux Ubuntu 24.04 LTS (x86_64) / Kernel 6.8
- **Phiên bản Python:** Python 3.14.8 (Tương thích tốt từ Python >= 3.10)
- **Bộ nhớ RAM:** Tối thiểu 8 GB (Khuyến nghị 16 GB khi xử lý file PDF scan 600+ trang)
- **Ổ cứng:** Tối thiểu 5 GB dung lượng trống để chứa ảnh trích xuất 300 DPI và cơ sở dữ liệu từ điển.
- **Card đồ họa (GPU):** Không bắt buộc (Toàn bộ pipeline chạy trên CPU với kiến trúc tối ưu microsecond B-Tree và API song song).

---

## 2. Hướng Dẫn Cài Đặt Trên Một Máy Mới Hoàn Toàn (From Scratch)

### Bước 2.1: Cài đặt các gói hệ thống cần thiết
Mở Terminal trên máy Ubuntu/Debian và thực hiện:
```bash
sudo apt-get update
sudo apt-get install -y git poppler-utils tesseract-ocr tesseract-ocr-vie
```
*(Ghi chú: `poppler-utils` cung cấp `pdftoppm` phục vụ trích xuất ảnh chuẩn ấn bản 300 DPI; `tesseract-ocr` phục vụ nhận dạng offline Quốc ngữ nếu không sử dụng API).*

### Bước 2.2: Tạo môi trường ảo và cài đặt thư viện Python
```bash
# Di chuyển vào thư mục dự án
cd sinom-midterm

# Khởi tạo môi trường ảo Python
python3 -m venv .venv
source .venv/bin/activate

# Cài đặt chính xác các phiên bản thư viện đã cố định (pinned dependencies)
pip install --upgrade pip
pip install -r requirements.txt
```

### Bước 2.3: Khởi tạo cơ sở dữ liệu tra cứu từ điển
Động cơ từ điển SQLite tích hợp 7 nguồn dữ liệu chuẩn (`hannom_rcv`, `btcn`, `dv`, `dnqatv`, `hvdic`, `unihan`, `cjkvi_variants`) với hơn 329.000 mục từ. Chỉ cần chạy một lệnh duy nhất:
```bash
python3 src/dict_engine/index_dict.py
```
*Thời gian chạy: ~5–6 giây. Kết quả: Tạo file `data/dict.db` (~25.5 MB) với B-Tree index giúp tra cứu ngữ âm dưới 1 millisecond.*

---

## 3. Cấu Hình Thông Tin Xác Thực (Credentials & APIs)

Hệ thống hỗ trợ 2 động cơ OCR:

### A. Động cơ Hán Nôm (API Kim Hán Nôm)
- **Token xác thực:** Lưu chuỗi JWT Bearer token được cấp vào file `configs/kim_token.txt`:
  ```bash
  mkdir -p configs
  echo "eyJhbGciOiJSUzI1NiIs..." > configs/kim_token.txt
  ```
- **Cơ chế tối ưu hóa Quota:**
  - Thay vì gọi 2 lượt (`/image-upload` $\to$ `/structure-classification` $\to$ `/image-ocr`), hệ thống tự động bóc tách kết quả OCR hoàn chỉnh đã được server nhúng sẵn trong trường `data.result.details.details` của API phân loại cấu trúc.
  - Tiết kiệm 50% số lượng request, nâng tối đa công suất xử lý lên tới 200 trang/ngày theo hạn ngạch.
  - Tích hợp bộ nhớ đệm SQLite (`data/ocr_cache.db`), không bao giờ gọi lại API cho các trang đã nhận dạng.

### B. Động cơ Quốc ngữ (OpenAI Vision API / Offline Tesseract)
- **Tùy chọn 1 (Offline hoàn toàn, Miễn phí):** Mặc định hệ thống sử dụng Tesseract với dữ liệu ngôn ngữ tiếng Việt `vie.traineddata` (đã lưu sẵn tại `data/tessdata/vie.traineddata`).
- **Tùy chọn 2 (OpenAI-compatible Vision API):** Nếu muốn sử dụng các mô hình thị giác cao cấp (GPT-4o, Claude, Qwen-VL):
  Tạo file `configs/openai_config.json`:
  ```json
  {
    "api_key": "sk-your-openai-or-openrouter-key",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini"
  }
  ```

---

## 4. Thực Thi Quy Trình Tự Động (Execution Guide)

Hệ thống được điều phối qua một CLI duy nhất: `scripts/run_pipeline.py`.

### Cách 1: Chạy toàn bộ quy trình tự động (End-to-End)
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage all
```

### Cách 2: Chạy kiểm thử nhanh một số trang (Dry-run / Quick Test)
Để kiểm tra tính thông suốt của toàn bộ pipeline trên một tập trang mẫu:
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --first-page 1 --last-page 5 \
    --dry-run-ocr \
    --stage all
```

### Cách 3: Chạy từng giai đoạn độc lập

#### Giai đoạn 1: Trích xuất ảnh & Phân loại thư mục
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage slice
```
*Kết quả:*
- Các trang được phân loại chính xác vào `data/processed/<Tên sách>/ch/`, `vi/`, `blank/`.
- File ánh xạ hình ảnh `<Tên sách>_image_map.json` tuân thủ đúng quy tắc đọc ngược của layout T1 (ví dụ: `vi.001` ánh xạ tới `ch.636`).

#### Giai đoạn 2: Nhận diện OCR
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage ocr
```
*Kết quả:*
- Tạo file nhãn chuẩn `Label.txt` (mỗi box đúng 4 toạ độ góc) và `fileState.txt` (toàn bộ dòng có state = `1`).
- Đảm bảo mở và chỉnh sửa hoàn hảo trên công cụ **PPOCRLabel**.

#### Giai đoạn 3: Ghép câu xuyên trang & Dóng hàng quy hoạch động (DP)
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage align
```
*Kết quả:*
- Tự động nối các câu bị đứt đoạn do chuyển trang (`PageStitcher`).
- Dóng hàng ngữ âm từng câu Nôm với Quốc ngữ, tính toán `text_diff` với toạ độ Unicode chuẩn xác.
- Xuất file `<Tên sách>.csv` (UTF-8 with BOM).
- Xuất file `<Tên sách>.xlsx` với màu sắc trực quan (Đen = Khớp, Đỏ = `error`, Vàng = `warn`).
- In bảng tổng kết độ tương đồng (%) theo đúng công thức Rubric v2.1.

#### Giai đoạn 4: Đóng gói bài nộp chuẩn Rubric
```bash
python3 scripts/run_pipeline.py \
    --pdf "data/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1).pdf" \
    --stage package
```
*Kết quả:*
- Tạo gói nộp bài chuẩn tại `output/24120068_24120151_24120103.zip` bao gồm:
  - Thư mục dữ liệu sách `<Tên sách>/` với đầy đủ `ch/`, `vi/`, `blank/`, `_image_map.json`, `.csv`, `.xlsx`.
  - `source.zip` chứa toàn bộ mã nguồn sạch cùng `requirements.txt` đã pinned.
  - Báo cáo tiến độ PDF `24120068_24120151_24120103_report.pdf`.

---

## 5. Hướng Dẫn Kiểm Tra Tính Tương Thích & Đạt Chuẩn (Verification)

### Kiểm tra bằng PPOCRLabel
1. Cài đặt PPOCRLabel (nếu muốn xem giao diện đồ họa):
   ```bash
   pip install ppocrlabel
   PPOCRLabel --lang vi
   ```
2. Mở thư mục `data/processed/<Tên sách>/ch` hoặc `vi`.
3. Kiểm tra: Bounding box hiển thị chính xác bao quanh từng khối chữ, không báo lỗi định dạng toạ độ, trạng thái nhãn hiển thị đã hoàn thành (màu xanh lá cây/state 1).

### Kiểm tra mở file .csv và .xlsx trên Excel / Google Sheets
- Mở file `.csv`: Hiển thị đúng tiếng Việt có dấu và chữ Hán Nôm Unicode, các cột thẳng hàng, không bị phân tách sai dấu nháy.
- Mở file `.xlsx`: Các ô văn bản Hán Nôm và Quốc ngữ hiển thị rõ ràng 3 màu (Đen, Đỏ, Vàng) tương ứng với nội dung trong cột `text_diff`.

---

## 6. Trực Quan Hóa Bounding Box Song Ngữ (Side-by-Side Dual Page Export)
Để xuất ảnh minh họa trực quan 2 trang Hán Nôm và Quốc ngữ song song với các bounding box và badge số thứ tự cùng màu (dùng chèn vào Phụ lục Báo cáo PDF hoặc Slide thuyết trình):
```bash
python3 scripts/visualize_parallel.py \
    --ch-img "data/processed/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1)/ch/<ảnh_nôm>.jpg" \
    --vi-img "data/processed/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 1)/vi/<ảnh_quốc_ngữ>.jpg" \
    --output "output/visualizations/side_by_side_demo.jpg"
```
Ảnh xuất ra ở độ phân giải cao (2576x1800), các cặp box giữa 2 trang được tự động đánh số badge và mã màu đồng bộ.

