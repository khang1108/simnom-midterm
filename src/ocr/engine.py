import os
import time
import json
import base64
import hashlib
import shutil
import sqlite3
import subprocess
import requests
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional

DEFAULT_KIM_BASE_URL = "https://kimhannom.fit.hcmus.edu.vn"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
CACHE_DB_PATH = Path("data/ocr_cache.db")

class OCREngine:
    """
    Unified OCR Engine:
    Một bộ nhận diện OCR duy nhất điều phối toàn bộ pipeline cho cả Hán Nôm ('ch') và Quốc ngữ ('vi'):
    - 'ch': Ưu tiên gọi API Kim Hán Nôm của trường (hoặc OpenAI Vision API nếu cấu hình).
    - 'vi': Gọi OpenAI-compatible Vision API (hoặc fallback Tesseract local).
    - Tích hợp SQLite Caching chung để không lãng phí chi phí/quota.
    - Luôn trả về định dạng thống nhất: [{"transcription": "...", "points": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}].
    """
    def __init__(
        self,
        kim_token: Optional[str] = None,
        openai_key: Optional[str] = None,
        openai_base_url: str = DEFAULT_OPENAI_BASE_URL,
        openai_model: str = "gpt-4o-mini",
        tessdata_dir: Path = Path("data/tessdata"),
        cache_db: Path = CACHE_DB_PATH,
        min_interval_sec: float = 2.5
    ):
        # 1. Cấu hình Kim Hán Nôm API
        self.kim_token = kim_token
        if not self.kim_token:
            token_file = Path("configs/kim_token.txt")
            if token_file.exists():
                self.kim_token = token_file.read_text(encoding="utf-8").strip()

        self.kim_base_url = DEFAULT_KIM_BASE_URL
        self.kim_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Authorization": f"Bearer {self.kim_token}" if self.kim_token else ""
        }
        self.min_interval_sec = min_interval_sec
        self.last_kim_call = 0.0

        # 2. Cấu hình OpenAI Vision API
        self.openai_key = openai_key or os.getenv("OPENAI_API_KEY")
        self.openai_base_url = openai_base_url.rstrip("/")
        self.openai_model = openai_model
        config_path = Path("configs/openai_config.json")
        if config_path.exists() and not self.openai_key:
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                self.openai_key = cfg.get("api_key", self.openai_key)
                self.openai_base_url = cfg.get("base_url", self.openai_base_url).rstrip("/")
                self.openai_model = cfg.get("model", self.openai_model)
            except Exception:
                pass

        # 3. Cấu hình Tesseract local fallback
        self.tessdata_dir = tessdata_dir

        # 4. CSDL Cache
        self.cache_db = cache_db
        self._init_cache()

    def _init_cache(self):
        self.cache_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.cache_db)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ocr_cache (
            file_hash TEXT,
            image_name TEXT,
            script TEXT,
            engine TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (file_hash, script)
        );
        """)
        conn.commit()
        conn.close()

    def _get_file_hash(self, image_path: Path) -> str:
        hasher = hashlib.md5()
        with open(image_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _get_cached_result(self, file_hash: str, script: str, exclude_engine: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """exclude_engine: bỏ qua kết quả cache của engine có tiền tố này (vd. nâng Tesseract -> VLM)."""
        conn = sqlite3.connect(self.cache_db)
        cur = conn.cursor()
        cur.execute("SELECT result_json FROM ocr_cache WHERE file_hash = ? AND script = ? AND engine NOT LIKE ?",
                    (file_hash, script, f"{exclude_engine}%" if exclude_engine else "\x00"))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            boxes = json.loads(row[0])
            # Các bản cũ có thể đã cache lỗi API thành []. Cho phép thử lại.
            return boxes if boxes else None
        return None

    def _save_cached_result(self, file_hash: str, image_name: str, script: str, engine: str, boxes: List[Dict[str, Any]]):
        conn = sqlite3.connect(self.cache_db)
        cur = conn.cursor()
        cur.execute("""
        INSERT OR REPLACE INTO ocr_cache (file_hash, image_name, script, engine, result_json)
        VALUES (?, ?, ?, ?, ?)
        """, (file_hash, image_name, script, engine, json.dumps(boxes, ensure_ascii=False)))
        conn.commit()
        conn.close()

    def _rate_limit_kim(self):
        elapsed = time.time() - self.last_kim_call
        if elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)
        self.last_kim_call = time.time()

    # -------------------------------------------------------------------------
    # BACKEND 1: KIM HÁN NÔM API (CHỮ NÔM)
    # -------------------------------------------------------------------------
    def _ocr_kim_hannom(self, image_path: Path) -> List[Dict[str, Any]]:
        if not self.kim_token:
            raise ValueError("Kim Han Nom Bearer token not provided.")

        # 1. Upload ảnh
        self._rate_limit_kim()
        upload_url = f"{self.kim_base_url}/api/web/clc-sinonom/image-upload"
        with open(image_path, "rb") as f:
            files = {"image_file": (image_path.name, f, "image/jpeg")}
            resp = requests.post(upload_url, headers=self.kim_headers, files=files, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("is_success"):
                raise RuntimeError(f"Upload failed: {data.get('message')}")
            temp_name = data["data"]["file_name"]

        # 2. Phân loại cấu trúc (Server Kim Hán Nôm thường nhúng luôn kết quả OCR)
        self._rate_limit_kim()
        struct_url = f"{self.kim_base_url}/api/web/clc-sinonom/structure-classification"
        payload = {"file_name": temp_name, "ocr_id": 0, "lang_type": 0, "reading_direction": 0}
        resp = requests.post(struct_url, headers=self.kim_headers, json=payload, timeout=45)
        resp.raise_for_status()
        struct_data = resp.json().get("data", {})

        boxes = []
        embedded_result = struct_data.get("result", {})
        details = embedded_result.get("details", {}).get("details", [])

        if details:
            for item in details:
                pts = item.get("points", [])
                trans = item.get("transcription", "")
                diff = item.get("difficult", False)
                if len(pts) >= 4 and trans.strip():
                    boxes.append({
                        "transcription": trans.strip(),
                        "points": [[int(p[0]), int(p[1])] for p in pts[:4]],
                        "difficult": bool(diff)
                    })
        else:
            # 3. Fallback sang image-ocr nếu chưa có sẵn
            self._rate_limit_kim()
            ocr_url = f"{self.kim_base_url}/api/web/clc-sinonom/image-ocr"
            ocr_payload = {
                "ocr_id": struct_data.get("ocr_id", 1) or 1,
                "lang_type": struct_data.get("lang_type", 2) or 2,
                "reading_direction": struct_data.get("reading_direction", 1) or 1,
                "file_name": temp_name,
                "epitaph": 0,
                "tag": None
            }
            resp = requests.post(ocr_url, headers=self.kim_headers, json=ocr_payload, timeout=45)
            resp.raise_for_status()
            ocr_res = resp.json().get("data", {})

            texts = ocr_res.get("result_ocr_text", [])
            bboxes = ocr_res.get("result_bbox", [])
            for t, b in zip(texts, bboxes):
                if len(b) >= 4 and t.strip():
                    boxes.append({
                        "transcription": t.strip(),
                        "points": [[int(p[0]), int(p[1])] for p in b[:4]]
                    })

        return boxes

    # -------------------------------------------------------------------------
    # BACKEND 2: OPENAI-COMPATIBLE VISION API (QUỐC NGỮ / HÁN NÔM)
    # -------------------------------------------------------------------------
    @staticmethod
    def _detect_line_boxes_opencv(image_path: Path, script: str = "vi") -> List[List[List[int]]]:
        """Dùng OpenCV phát hiện chính xác tọa độ từng dòng chữ trên trang scan."""
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []
        h, w = img.shape
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Khử viền scan đen
        min_line = max(20, int(w * 0.05))
        h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_line, 1)))
        v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_line)))
        clean_bin = cv2.bitwise_and(binary, cv2.bitwise_not(cv2.bitwise_or(h_lines, v_lines)))

        # Giãn hình thái học theo chiều ngang để gom dòng
        kernel_size = (2, max(20, h // 15)) if script == "ch" else (max(20, w // 15), 2)
        line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        dilated = cv2.morphologyEx(clean_bin, cv2.MORPH_CLOSE, line_kernel)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rects = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if ((script == "ch" and ch > h * 0.12 and 6 <= cw <= w * 0.15)
                    or (script != "ch" and cw > w * 0.12 and 6 <= ch <= h * 0.15)):
                rects.append((x, y, cw, ch))

        rects.sort(key=(lambda r: -r[0]) if script == "ch" else (lambda r: r[1]))
        return [[[x, y], [x + cw, y], [x + cw, y + ch], [x, y + ch]] for x, y, cw, ch in rects]

    VLM_PROMPTS = {
        "vi": ("Chép lại CHÍNH XÁC dòng chữ tiếng Việt trong ảnh (sách Công giáo in đầu thế kỷ 20). "
               "Giữ nguyên chính tả cổ, dấu thanh, dấu gạch nối và dấu câu như trong ảnh; không sửa, không thêm. "
               "Chỉ trả về đúng dòng chữ đó."),
        "vi_strict": ("Chép lại CHÍNH XÁC dòng chữ tiếng Việt trong ảnh (sách Công giáo in đầu thế kỷ 20). "
                      "Nhìn kỹ từng chữ: phân biệt đ (có gạch ngang) với d, và các dấu ă, â, ê, ô, ơ, ư cùng dấu thanh. "
                      "Giữ nguyên chính tả cổ, dấu gạch nối và dấu câu như trong ảnh; không sửa, không thêm. "
                      "Chỉ trả về đúng dòng chữ đó."),
        "ch": ("Chép lại CHÍNH XÁC cột chữ Hán Nôm trong ảnh, đọc từ trên xuống dưới, không thêm khoảng trắng. "
               "Không suy đoán chữ ngoài ảnh. Chỉ trả về đúng các chữ đó."),
    }

    def _vlm_read_crop(self, img: np.ndarray, pts: List[List[int]], script: str, pad: int = 4,
                       min_h: int = 48, prompt: Optional[str] = None) -> str:
        h, w = img.shape[:2]
        if max(p[0] for p in pts) <= min(p[0] for p in pts) or max(p[1] for p in pts) <= min(p[1] for p in pts):
            return ""
        x1, x2 = max(0, min(p[0] for p in pts) - pad), min(w, max(p[0] for p in pts) + pad)
        y1, y2 = max(0, min(p[1] for p in pts) - pad), min(h, max(p[1] for p in pts) + pad)
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return ""
        if script == "vi" and crop.shape[0] < min_h:
            s = min_h / crop.shape[0]
            crop = cv2.resize(crop, (int(crop.shape[1] * s), min_h), interpolation=cv2.INTER_LANCZOS4)
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
            raise RuntimeError("Cannot encode text crop")
        payload = {
            "model": self.openai_model, "temperature": 0.0, "max_tokens": 200,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode()}},
                {"type": "text", "text": prompt or self.VLM_PROMPTS[script]},
            ]}],
        }
        resp = requests.post(f"{self.openai_base_url}/chat/completions", json=payload, timeout=120,
                             headers={"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"})
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    def _ocr_openai_vision(self, image_path: Path, script: str = "vi") -> List[Dict[str, Any]]:
        """
        VLM đọc lại từng vùng dòng/cột; văn bản luôn gắn với đúng vùng đã gửi.
        - 'vi': vùng = box dòng của Tesseract; dòng VLM trả rỗng thì giữ chữ Tesseract.
        - 'ch': vùng = cột phát hiện bằng OpenCV.
        """
        from concurrent.futures import ThreadPoolExecutor

        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        if script == "vi" and shutil.which("tesseract"):
            base = self._ocr_tesseract(image_path)
        else:
            base = [{"transcription": "", "points": p} for p in self._detect_line_boxes_opencv(image_path, script=script)]
        if not base:
            raise RuntimeError(f"No text regions detected in {image_path.name}")
        with ThreadPoolExecutor(16) as ex:
            texts = list(ex.map(lambda b: self._vlm_read_crop(img, b["points"], script), base))
        return [{"transcription": t or b["transcription"], "points": b["points"]}
                for b, t in zip(base, texts) if (t or b["transcription"]).strip()]

    # -------------------------------------------------------------------------
    # BACKEND 3: TESSERACT LOCAL FALLBACK (QUỐC NGỮ)
    # -------------------------------------------------------------------------
    def _ocr_tesseract(self, image_path: Path) -> List[Dict[str, Any]]:
        cmd = [
            "tesseract",
            str(image_path),
            "stdout",
            "--tessdata-dir", str(self.tessdata_dir),
            "-l", "vie",
            "-c", "tessedit_create_tsv=1"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Tesseract failed: {res.stderr}")

        lines = []
        current_words = []
        current_bbox = None

        for row in res.stdout.splitlines():
            parts = row.split("\t")
            if len(parts) < 12 or parts[0] == "level":
                continue

            level = parts[0]
            if level == "4":
                if current_words and current_bbox:
                    line_text = " ".join(current_words).strip()
                    if line_text:
                        lines.append({
                            "transcription": line_text,
                            "points": [
                                [current_bbox[0], current_bbox[1]],
                                [current_bbox[0] + current_bbox[2], current_bbox[1]],
                                [current_bbox[0] + current_bbox[2], current_bbox[1] + current_bbox[3]],
                                [current_bbox[0], current_bbox[1] + current_bbox[3]]
                            ]
                        })
                    current_words = []
                current_bbox = (int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]))
            elif level == "5":
                w = parts[11].strip()
                if w:
                    current_words.append(w)

        if current_words and current_bbox:
            line_text = " ".join(current_words).strip()
            if line_text:
                lines.append({
                    "transcription": line_text,
                    "points": [
                        [current_bbox[0], current_bbox[1]],
                        [current_bbox[0] + current_bbox[2], current_bbox[1]],
                        [current_bbox[0] + current_bbox[2], current_bbox[1] + current_bbox[3]],
                        [current_bbox[0], current_bbox[1] + current_bbox[3]]
                    ]
                })
        return lines

    # -------------------------------------------------------------------------
    # MAIN UNIFIED INTERFACE
    # -------------------------------------------------------------------------
    def recognize(self, image_path: Path, script: str = "ch", force_reocr: bool = False) -> List[Dict[str, Any]]:
        """
        Giao diện nhận diện duy nhất cho toàn bộ hệ thống:
        - image_path: Đường dẫn ảnh cần OCR.
        - script: 'ch' (Hán Nôm) hoặc 'vi' (Quốc ngữ).
        - force_reocr: Bỏ qua cache để chạy lại từ đầu nếu muốn.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        file_hash = self._get_file_hash(image_path)
        if not force_reocr:
            exclude = "tesseract" if (script == "vi" and self.openai_key) else None
            cached = self._get_cached_result(file_hash, script, exclude_engine=exclude)
            if cached is not None:
                return cached

        boxes = []
        engine_used = "unknown"

        if script == "ch":
            # Hán Nôm: Ưu tiên API Kim Hán Nôm
            if self.kim_token:
                try:
                    boxes = self._ocr_kim_hannom(image_path)
                    engine_used = "kim_hannom_api"
                except Exception as e:
                    print(f"[OCREngine] Kim Han Nom API failed ({e}), checking OpenAI Vision fallback...")

            # Nếu Kim API không thành công mà có OpenAI Key
            if not boxes and self.openai_key:
                boxes = self._ocr_openai_vision(image_path, script="ch")
                engine_used = f"openai:{self.openai_model}"

        else:
            # Quốc ngữ: Ưu tiên OpenAI Vision API (nếu có key)
            if self.openai_key:
                try:
                    boxes = self._ocr_openai_vision(image_path, script="vi")
                    engine_used = f"openai:{self.openai_model}"
                except Exception as e:
                    print(f"[OCREngine] OpenAI Vision failed ({e}), falling back to Tesseract local...")

            # Fallback sang Tesseract local
            if not boxes:
                boxes = self._ocr_tesseract(image_path)
                engine_used = "tesseract:vie"

        if not boxes or not any(b.get("transcription", "").strip() for b in boxes):
            raise RuntimeError(
                f"OCR produced no text for {image_path.name} (script={script}); "
                "result was not cached. Check backend credentials or verify the page manually."
            )

        # Chỉ cache kết quả có văn bản; trang trắng cần được xác nhận riêng.
        self._save_cached_result(file_hash, image_path.name, script, engine_used, boxes)
        return boxes
