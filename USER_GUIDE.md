# HƯỚNG DẪN VẬN HÀNH TOÀN BỘ QUY TRÌNH (USER GUIDE)
**Dự án:** Xây dựng Ngữ liệu Song ngữ Hán Nôm – Quốc ngữ Tự động  
**Quy chuẩn áp dụng:** Quy_định_đồ_án_v2.6.pdf  
**Nhóm thực hiện:**
- Nguyễn Phúc Khang (MSSV: 24120068 - Trưởng nhóm)
- Phạm Minh Trọng (MSSV: 24120151)
- Hoàng Trọng Nghĩa (MSSV: 24120103)

---

## 1. Môi Trường Vận Hành (Tested Environment)
Dữ liệu nộp được tạo trên hai máy:

| | Máy chạy pipeline (OCR, ROVER, dóng hàng, `_updated.pdf`) | Máy phát triển (sửa code, chạy test, đóng gói) |
|---|---|---|
| Hệ điều hành | Ubuntu 24.04.3 LTS (x86_64) | Arch Linux (x86_64), kernel 7.2 |
| CPU / RAM | 128 luồng / 2 TB | Intel Core i7-8750H (12 luồng) / 15 GB |
| GPU | NVIDIA A100-SXM4-80GB (1 card, chạy vLLM 0.34.0 phục vụ Qwen3-VL-8B-Instruct) | Không có |
| Python | 3.12.16 | 3.14.8 |

- Pipeline chạy được với Python >= 3.10. Bước OCR Quốc ngữ cần GPU NVIDIA đủ VRAM cho Qwen3-VL-8B-Instruct qua vLLM; các bước còn lại chạy trên CPU.
- Ổ cứng cần tối thiểu 5 GB trống cho PDF gốc, ảnh trích xuất, từ điển và hai file `_updated.pdf` (khoảng 170 MB mỗi tập).
- Nếu máy không có `tesseract`, khung dòng Quốc ngữ được phát hiện bằng OpenCV.

---

## 2. Hướng Dẫn Cài Đặt Trên Một Máy Mới Hoàn Toàn (From Scratch)

### Bước 2.1: Cài đặt các gói hệ thống cần thiết
Mở Terminal trên máy Ubuntu/Debian và thực hiện:
```bash
sudo apt-get update
sudo apt-get install -y git poppler-utils qpdf tesseract-ocr tesseract-ocr-vie
```
*(Ghi chú: `poppler-utils` cung cấp `pdftoppm` để cắt ảnh (72 DPI ≈ độ phân giải gốc); `qpdf` tạo `_updated.pdf` khi loại trang trùng; `tesseract-ocr` phục vụ nhận dạng offline Quốc ngữ nếu không sử dụng API).*

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

### B. Động cơ Quốc ngữ (Qwen3-VL-8B-Instruct qua vLLM, Tesseract làm box dòng)
Quốc ngữ được đọc bằng mô hình thị giác mở **Qwen/Qwen3-VL-8B-Instruct** (miễn phí, chạy trên GPU riêng, giao tiếp kiểu OpenAI `/v1/chat/completions`). Tesseract (`data/tessdata/vie.traineddata`) chỉ dùng để tìm box từng dòng; mỗi dòng được cắt ra, phóng lên tối thiểu 48 px chiều cao và gửi cho Qwen với `temperature=0`, `max_tokens=200`. Dòng Qwen trả rỗng thì giữ chữ Tesseract.

Khởi động server mô hình (GPU ≥ 24 GB, vLLM đã cài trong một venv riêng):
```bash
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen3-VL-8B-Instruct --port 8120 \
    --max-model-len 8192 --gpu-memory-utilization 0.85 --limit-mm-per-prompt '{"image":1}'
```
Nếu GPU ở máy khác, mở tunnel: `ssh -N -L 8120:localhost:8120 <máy-gpu>`.

Prompt đã dùng (`src/ocr/engine.py`, `OCREngine.VLM_PROMPTS`):
- `vi` (lượt chính, 48 px):
  > Chép lại CHÍNH XÁC dòng chữ tiếng Việt trong ảnh (sách Công giáo in đầu thế kỷ 20). Giữ nguyên chính tả cổ, dấu thanh, dấu gạch nối và dấu câu như trong ảnh; không sửa, không thêm. Chỉ trả về đúng dòng chữ đó.
- `vi_strict` (lượt phụ, phóng 96 px, dùng cho ROVER):
  > Chép lại CHÍNH XÁC dòng chữ tiếng Việt trong ảnh (sách Công giáo in đầu thế kỷ 20). Nhìn kỹ từng chữ: phân biệt đ (có gạch ngang) với d, và các dấu ă, â, ê, ô, ơ, ư cùng dấu thanh. Giữ nguyên chính tả cổ, dấu gạch nối và dấu câu như trong ảnh; không sửa, không thêm. Chỉ trả về đúng dòng chữ đó.

**ROVER (voting 3 bản OCR):** với mỗi từ, nếu bản Qwen không phải âm đọc của chữ Nôm nào trên trang đối ứng mà bản Tesseract hoặc bản Qwen 96 px là âm đọc đó, thì lấy bản phụ (`reconcile_vi_with_nom` trong `src/ocr/runner.py`). Kết quả 3 bản được lưu trong cache với khóa `vi`, `vi_tess`, `vi_vlm96`.

Truyền thông số cho bước OCR bằng tham số dòng lệnh (`--openai-key EMPTY --openai-base-url http://localhost:8120/v1 --openai-model Qwen/Qwen3-VL-8B-Instruct`) hoặc file `configs/openai_config.json` (cùng ba trường `api_key`, `base_url`, `model`). vLLM không kiểm tra key nên dùng `EMPTY`.

---

## 4. Thực Thi Quy Trình Tự Động (Execution Guide)

### Lệnh đã chạy để tạo dữ liệu nộp (lặp cho Tập 1 và Tập 2)
```bash
B="data/processed/T1_Sách Dạy Đấng Làm Người Sửa Mình (Tập 2)"
python scripts/prepare_books.py
python -m src.ocr.runner --book-dir "$B" --token "$(cat configs/kim_token.txt)" \
    --openai-key EMPTY --openai-base-url http://localhost:8120/v1 --openai-model Qwen/Qwen3-VL-8B-Instruct
python scripts/run_official_align.py --book-dir "$B" --out-dir "$B"
```
- `prepare_books.py`: cắt ảnh theo `configs/books_structure.json`, xoay các trang scan ngược (`rotate_180`), ghép lại các trang Nôm đặt sai chỗ (`pair_segments`), chép PDF gốc thành `<Tên sách>.pdf` và ghép `<Tên sách>_updated.pdf` từ ảnh đã nộp, tạo `_image_map.json`.
- `src.ocr.runner`: OCR `ch/` (Kim Hán Nôm), `vi/`, `intro/`, `ref/`, `toc/` (Qwen3-VL), đổi ký tự riêng PUA của Kim sang Unicode chuẩn theo `configs/pua_to_unicode.csv` (Unihan `kIRG_VSource` hoặc đối chiếu IDS; chữ chưa có trong Unicode ghi `〓`), sửa chữ Kim nhận nhầm hình theo `configs/kim_glyph_fix.csv`, rồi chạy ROVER.
- `run_official_align.py`: dóng hàng, tính `text_diff`, xuất `.csv`, `.xlsx`, `_placeholder_map.json` (khi có `〓`, tự kiểm 7 điều kiện của Quy định v2.6), chạy `check`, `check-diff --final`, `score`. File trung gian `_pairs.csv`, `_align_report.json` ghi vào `data/processed/_extras/<Tên sách>/` (đưa vào `extras.zip`).
- Mọi kết quả OCR được cache trong `data/ocr_cache.db`; chạy lại không gọi lại API hay mô hình.

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
- Các trang được phân loại chính xác vào `data/processed/<Tên sách>/` theo khoảng trang khai báo trong `configs/books_structure.json` (`ch`, `vi`, `intro`, `ref`, `toc`, `blank`, `misc`, `missing/ch`).
- File ánh xạ hình ảnh `<Tên sách>_image_map.json` tuân thủ đúng quy tắc đọc ngược của layout T1 (ví dụ Tập 1: `vi.011` ánh xạ tới `ch.624`).

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
- In bảng tổng kết độ tương đồng (%) theo đúng công thức Quy định v2.4.

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

