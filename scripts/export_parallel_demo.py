"""Export one OCR page pair as a searchable PDF with linked sentence regions.

Requires xelatex, fontTools and a Nôm font supplied with --font.
OCR is reused from Label.txt; sentence regions are interpolated, not detected.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from src.aligner.book_aligner import BookAligner

DEFAULT_CH_ROI = [.20, .14, .75, .86]

COLORS = ['#9c27b0', '#007c91', '#c45c00', '#1e62c0', '#28813b', '#c62861']


def read_boxes(path, image):
    for line in path.read_text(encoding='utf-8').splitlines():
        name, data = line.split('\t', 1)
        if Path(name).name == image:
            return json.loads(data)
    raise ValueError(f'No OCR labels for {image}')


def body_boxes(boxes, size, roi):
    """Explicit sample-specific body ROI; record exclusions in manifest."""
    w, h = size
    keep, excluded = [], []
    for b in boxes:
        x = sum(p[0] for p in b['points']) / 4 / w
        y = sum(p[1] for p in b['points']) / 4 / h
        (keep if roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3] else excluded).append(b)
    return keep, excluded


def interpolate(points, start, end, vertical):
    def lerp(a, b, t):
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    a, b, c, d = points
    if vertical:
        return [lerp(a, d, start), lerp(b, c, start), lerp(b, c, end), lerp(a, d, end)]
    return [lerp(a, b, start), lerp(a, b, end), lerp(d, c, end), lerp(d, c, start)]


def locate_regions(boxes, sentences, vertical):
    # Remove only whitespace for matching, retain raw character positions for geometry.
    stream = []
    for box_index, box in enumerate(boxes):
        for char_index, char in enumerate(box['transcription']):
            if not char.isspace():
                stream.append((char, box_index, char_index))
    full = ''.join(c for c, _, _ in stream)
    offset = 0
    result = []
    for sentence in sentences:
        key = ''.join(c for c in sentence if not c.isspace())
        if full[offset:offset + len(key)] != key:
            raise ValueError('Sentence text does not match OCR stream; refusing to draw misleading boxes')
        regions = []
        consumed = stream[offset:offset + len(key)]
        for box_index in dict.fromkeys(b for _, b, _ in consumed):
            indices = [i for _, b, i in consumed if b == box_index]
            box = boxes[box_index]
            length = len(box['transcription'])
            regions.append({'ocr_box_index': box_index,
                            'points': interpolate(box['points'], min(indices)/length,
                                                  (max(indices)+1)/length, vertical)})
        result.append(regions)
        offset += len(key)
    if offset != len(stream):
        raise ValueError('Some OCR text is missing from alignment output')
    return result


def tex(text):
    replacements = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
                    '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}',
                    '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(c, c) for c in text)


def annotate(image, regions, output):
    original_width = image.width
    image = image.copy().convert('RGB')
    image.thumbnail((1500, 2200))
    sx = image.width / original_width
    # Both axes use the same aspect-preserving scale.
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('/usr/share/fonts/noto/NotoSans-Bold.ttf', 22)
    for number, parts in enumerate(regions, 1):
        color = COLORS[(number - 1) % len(COLORS)]
        for j, region in enumerate(parts):
            pts = [(p[0]*sx, p[1]*sx) for p in region['points']]
            draw.line(pts + [pts[0]], fill=color, width=3)
            if j == 0:
                x, y = pts[0]
                draw.rectangle((x, max(0, y-28), x+45, max(0, y-28)+28), fill=color)
                draw.text((x+3, max(0, y-28)), str(number), fill='white', font=font)
    image.save(output, quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--book-dir', type=Path, default=Path('data/processed/T1_Bao_Cao_Tien_Do'))
    parser.add_argument('--ch-image', default='T1_Bao_Cao_Tien_Do.587.jpg')
    parser.add_argument('--vi-image', default='T1_Bao_Cao_Tien_Do.048.jpg')
    parser.add_argument('--output-dir', type=Path, default=Path('output/demo_parallel'))
    parser.add_argument('--font', type=Path, default=Path('output/demo_parallel/fonts/NomNaTong-Regular.ttf'))
    parser.add_argument('--ch-roi', type=float, nargs=4, default=DEFAULT_CH_ROI)
    parser.add_argument('--vi-roi', type=float, nargs=4, default=[0, .15, 1, .85])
    parser.add_argument('--extra-pair', nargs=2, action='append', default=[], metavar=('CH_IMAGE', 'VI_IMAGE'),
                        help='Append another independently aligned page pair')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    font_path = args.font.resolve()
    if not font_path.exists():
        raise FileNotFoundError('Supply a Nôm TTF with --font; see https://github.com/nomfoundation/font/releases')
    font_target = out / 'fonts' / 'NomNaTong-Regular.ttf'
    font_target.parent.mkdir(exist_ok=True)
    if font_target != font_path:
        shutil.copy2(font_path, font_target)
    sample = out / 'sample'
    manifest = {'ocr_source': 'Existing Label.txt; no new OCR API calls',
                'geometry': 'Original OCR line/column boxes; sentence subregions are interpolated estimates',
                'scope': 'One source-page pair; final unfinished sentence is retained as a fragment',
                'font_source': 'https://github.com/nomfoundation/font', 'pages': {}}
    side_boxes = {}
    images = {}
    for side, filename, roi in [('ch', args.ch_image, args.ch_roi), ('vi', args.vi_image, args.vi_roi)]:
        source = args.book_dir / side / filename
        with Image.open(source) as image:
            images[side] = image.convert('RGB')
        boxes, excluded = body_boxes(read_boxes(args.book_dir / side / 'Label.txt', filename), images[side].size, roi)
        if not boxes:
            raise ValueError(f'No body boxes for {side}')
        side_boxes[side] = boxes
        manifest['pages'][side] = {'source': str(source), 'roi': roi, 'excluded_boxes': excluded}
        dest = sample / side
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'Label.txt').write_text(f'{side}/{filename}\t{json.dumps(boxes, ensure_ascii=False)}\n', encoding='utf-8')
        images[side].save(out / f'{side}.jpg', quality=95)
    (sample / 'Demo_image_map.json').write_text(json.dumps({'pairs': [{'ch': [args.ch_image], 'vi': [args.vi_image]}]}), encoding='utf-8')
    result = BookAligner().align_book(str(sample), 'Demo', str(out))
    with open(result['csv_path'], encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    for side in ['ch', 'vi']:
        regions = locate_regions(side_boxes[side], [r[f'{side}_txt'] for r in rows], side == 'ch')
        for row, parts in zip(rows, regions):
            row[f'{side}_regions'] = parts
        annotate(images[side], regions, out / f'{side}_annotated.jpg')
    coverage = TTFont(font_target).getBestCmap()
    missing = sorted({c for row in rows for c in row['ch_txt'] if ord(c) not in coverage and not c.isspace()})
    if missing:
        raise ValueError(f'Nôm font lacks glyphs: {missing}')
    manifest['alignment_metrics'] = result['metrics']
    manifest['sentences'] = rows
    (out / 'alignment.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    sections = [r'''% !TeX program = xelatex
% !TeX encoding = UTF-8
\documentclass[11pt]{article}
\usepackage[a3paper,landscape,margin=15mm]{geometry}
\usepackage{fontspec,graphicx,xcolor}
\setmainfont{Noto Sans}
\newfontfamily\nomfont[Path=fonts/]{NomNaTong-Regular.ttf}
\XeTeXlinebreaklocale "zh"
\XeTeXlinebreakskip=0pt plus 1pt
\setlength{\parindent}{0pt}
\begin{document}
{\Large Đối chiếu Hán Nôm – Quốc ngữ: trang in 589}\par
Nguồn: PDF 587 (Nôm) và PDF 48 (Quốc ngữ). Bản thử từ OCR đã lưu, chưa hiệu đính.\par
Cùng số và màu viền = cùng câu/thành phần. Box theo câu là ước lượng từ box OCR dòng/cột.\par
Màu viền chỉ định danh cặp, không biểu thị độ chính xác.\par\medskip
\includegraphics[width=.49\linewidth,height=.80\textheight,keepaspectratio]{ch_annotated.jpg}\hfill
\includegraphics[width=.49\linewidth,height=.80\textheight,keepaspectratio]{vi_annotated.jpg}
\clearpage
{\Large Văn bản số đối chiếu}\par
Văn bản có thể chọn và sao chép. Giữ nguyên OCR; lỗi nhận dạng và lỗi dóng hàng có thể còn tồn tại.\par
Phần cuối trang chưa kết thúc câu được giữ như một thành phần, không suy đoán phần trang kế tiếp.\par\bigskip
''']
    for number, row in enumerate(rows, 1):
        color = COLORS[(number-1) % len(COLORS)].lstrip('#')
        sections.append(r'\begin{minipage}{\linewidth}' + '\n' +
                        r'\definecolor{paircolor}{HTML}{' + color + '}\n' +
                        r'{\color{paircolor}\large Cặp ' + str(number) + '} — ' + tex(row['sentence_id']) + r'\par\smallskip' + '\n' +
                        r'\begin{minipage}[t]{.48\linewidth}\textbf{Hán Nôm}\par\medskip{\nomfont\fontsize{17}{26}\selectfont ' + tex(row['ch_txt']) + r'\par}\end{minipage}\hfill' + '\n' +
                        r'\begin{minipage}[t]{.48\linewidth}\textbf{Quốc ngữ}\par\medskip ' + tex(row['vi_txt']) + r'\par\end{minipage}' + '\n' +
                        r'\par\medskip\hrule\end{minipage}\par\bigskip' + '\n')
    total_pairs = len(rows)
    for index, (ch_image, vi_image) in enumerate(args.extra_pair, 1):
        extra_out = out / f'pair_{index + 1:02d}'
        subprocess.run([
            sys.executable, str(Path(__file__).resolve()),
            '--book-dir', str(args.book_dir.resolve()),
            '--ch-image', ch_image, '--vi-image', vi_image,
            '--output-dir', str(extra_out), '--font', str(font_target),
            '--ch-roi', *map(str, args.ch_roi), '--vi-roi', *map(str, args.vi_roi),
        ], check=True)
        extra_manifest = json.loads((extra_out / 'alignment.json').read_text(encoding='utf-8'))
        total_pairs += len(extra_manifest['sentences'])
        extra_tex = (extra_out / 'parallel_demo.tex').read_text(encoding='utf-8')
        body = extra_tex.split(r'\begin{document}', 1)[1].rsplit(r'\end{document}', 1)[0]
        for image_name in ['ch_annotated.jpg', 'vi_annotated.jpg']:
            body = body.replace('{' + image_name + '}', '{' + extra_out.name + '/' + image_name + '}')
        sections.append(r'\clearpage' + '\n' + body)
    sections.append(r'\end{document}')
    document = ''.join(sections)
    document = document.replace('Đối chiếu Hán Nôm – Quốc ngữ: trang in 589',
                                'Đối chiếu Hán Nôm – Quốc ngữ')
    document = document.replace('Nguồn: PDF 587 (Nôm) và PDF 48 (Quốc ngữ).',
                                'Nguồn: ' + tex(args.ch_image) + ' (Nôm) / ' + tex(args.vi_image) + ' (Quốc ngữ).')
    (out / 'parallel_demo.tex').write_text(document, encoding='utf-8')
    (out / '.latexmkrc').write_text(
        '$pdf_mode = 5;\n$do_cd = 1;\n', encoding='utf-8'
    )
    run = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'parallel_demo.tex'], cwd=out,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / 'build.log').write_text(run.stdout, encoding='utf-8')
    if run.returncode:
        raise RuntimeError(f'PDF build failed; see {out / "build.log"}')
    print(f'PDF: {out / "parallel_demo.pdf"}; {total_pairs} sentence/fragment pairs')


if __name__ == '__main__':
    main()
