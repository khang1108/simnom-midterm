"""Export the updated Progress Report Markdown to a publication-grade PDF via Pandoc + XeLaTeX."""

import re
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MD_SRC = Path(
    "/home/phuckhang/.gemini/antigravity/brain/edf69dfd-cf12-45e0-b5f4-6f176ef4000a/Bao_Cao_Tien_Do_Do_An_NLP_Han_Nom.md"
)
ARCH_PNG = ROOT_DIR / "output/pipeline_v24_arch.png"
BUILD_DIR = ROOT_DIR / "output/pdf_build"
PDF_OUT = ROOT_DIR / "output/Bao_Cao_Tien_Do_Do_An_NLP_Han_Nom.pdf"

HEADER_TEX = r"""
\usepackage{fontspec}
\newfontfamily\cjkfont{Noto Serif CJK TC}[Scale=0.95]
\usepackage{xcolor}
\definecolor{PrimaryBlue}{HTML}{1E3A8A}
\definecolor{AccentBlue}{HTML}{2563EB}
\definecolor{MutedGray}{HTML}{475569}
\definecolor{LightBg}{HTML}{F8FAFC}
\definecolor{RuleGray}{HTML}{CBD5E1}

\usepackage{titlesec}
\titleformat{\section}{\Large\bfseries\sffamily\color{PrimaryBlue}}{}{0em}{}[\vspace{2pt}{\color{AccentBlue}\titlerule[0.8pt]}]
\titleformat{\subsection}{\large\bfseries\sffamily\color{PrimaryBlue}}{}{0em}{}
\titleformat{\subsubsection}{\normalsize\bfseries\sffamily\color{PrimaryBlue}}{}{0em}{}
\titleformat{\paragraph}[hang]{\normalsize\bfseries\sffamily\color{MutedGray}}{}{0em}{}
\titlespacing*{\subsubsection}{0pt}{10pt}{4pt}
\titlespacing*{\paragraph}{0pt}{8pt}{3pt}

\usepackage{needspace}
\usepackage[export]{adjustbox}
\usepackage{float}
\usepackage{caption}
\captionsetup[figure]{font={small,sf},labelfont={bf,color=PrimaryBlue},labelsep=period,skip=6pt}
\renewcommand{\figurename}{Hình}
\renewcommand{\tablename}{Bảng}

\usepackage{etoolbox}
\AtBeginEnvironment{longtable}{\scriptsize\renewcommand{\arraystretch}{1.22}}
\setlength{\LTleft}{0pt}
\setlength{\LTright}{0pt}
\setlength{\tabcolsep}{3.5pt}

\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\footnotesize\sffamily\color{MutedGray}Báo cáo Tiến độ Đồ án NLP}
\fancyhead[R]{\footnotesize\sffamily\color{MutedGray}Cập nhật 20/11/2026}
\fancyfoot[C]{\footnotesize\sffamily\color{MutedGray}Trang \thepage}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0pt}

\usepackage{enumitem}
\setlist[itemize]{itemsep=3pt,topsep=4pt,parsep=0pt}
\setlist[enumerate]{itemsep=3pt,topsep=4pt,parsep=0pt}

\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}
\sloppy
"""

CJK_RUN_RE = re.compile(r"([\u3000-\u303F\u3400-\u4DBF\u4E00-\u9FFF]+)")


def replace_extb_glyphs(text: str) -> str:
    """Replace CJK Extension-B glyphs lacking local font support with crisp Unicode references."""
    replacements = {
        "𨷯": "[U+28DEF]",
        "𢖕": "[U+22595]",
        "𢇷": "[U+221F7]",
        "𠊚": "[U+2029A]",
        "𡗶": "[U+215F6]",
    }
    for ch, rep in replacements.items():
        text = text.replace(ch, rep)
    return text


def preprocess_markdown(raw_md: str) -> str:
    """Prepare Markdown so Mermaid diagrams, side-by-side figures, and tables render cleanly in XeLaTeX."""
    md = replace_extb_glyphs(raw_md)

    # 1. Thay khối Mermaid bằng ảnh PNG kiến trúc đã render
    mermaid_pattern = re.compile(r"```mermaid\s+flowchart\s+TD.*?```", re.DOTALL)
    arch_block = (
        "\n```{=latex}\n"
        "\\begin{figure}[H]\n"
        "\\centering\n"
        f"\\includegraphics[max width=0.82\\linewidth, max height=0.29\\textheight, keepaspectratio]{{{ARCH_PNG.resolve()}}}\n"
        "\\caption{Kiến trúc Hybrid Pipeline chuẩn Quy định v2.4 tích hợp công cụ \\texttt{ocr-nom-align} v0.2.0.}\n"
        "\\end{figure}\n"
        "```\n"
    )
    md, n_mmd = mermaid_pattern.subn(lambda _m: arch_block, md)
    if n_mmd == 0:
        raise RuntimeError("Không tìm thấy khối Mermaid trong file báo cáo nguồn.")

    # 2. Thay bảng 2 ảnh so sánh cạnh nhau bằng hai minipage gọn trong khổ A4
    side_by_side_pattern = re.compile(
        r"\|\s*[^|\n]+\s*\|\s*[^|\n]+\s*\|\n\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|\n\|\s*!\[(.*?)\]\((.*?)\)\s*\|\s*!\[(.*?)\]\((.*?)\)\s*\|",
        re.DOTALL,
    )

    def _sub_side_by_side(match: re.Match) -> str:
        c1, p1, c2, p2 = match.groups()
        return (
            "\n```{=latex}\n"
            "\\begin{figure}[H]\n"
            "\\centering\n"
            "\\begin{minipage}[t]{0.48\\linewidth}\n"
            "\\centering\n"
            f"\\includegraphics[max width=\\linewidth, max height=0.27\\textheight, keepaspectratio]{{{p1}}}\\\\\n"
            f"\\vspace{{2pt}}{{\\footnotesize\\sffamily (a) {c1}}}\n"
            "\\end{minipage}\\hfill\n"
            "\\begin{minipage}[t]{0.48\\linewidth}\n"
            "\\centering\n"
            f"\\includegraphics[max width=\\linewidth, max height=0.27\\textheight, keepaspectratio]{{{p2}}}\\\\\n"
            f"\\vspace{{2pt}}{{\\footnotesize\\sffamily (b) {c2}}}\n"
            "\\end{minipage}\n"
            "\\caption{Minh họa tách dòng Quốc ngữ 4 điểm bằng detector + \\texttt{VietOCR} trên trang sạch và trang ố vàng nặng.}\n"
            "\\end{figure}\n"
            "```\n"
        )

    md, n_side = side_by_side_pattern.subn(_sub_side_by_side, md)
    if n_side == 0:
        raise RuntimeError("Không tìm thấy bảng so sánh 2 ảnh 048 và 275 trong file nguồn.")

    # 3. Chuyển các ảnh đứng một mình thành figure[H] có giới hạn kích thước rõ ràng
    single_img_re = re.compile(r"^!\[(.*?)\]\((.*?)\)\s*$", re.MULTILINE)

    def _sub_single_img(match: re.Match) -> str:
        cap, path = match.groups()
        cap_tex = cap.replace("<->", "$\\leftrightarrow$")
        if "pua_crops" in path:
            max_h, max_w = "0.20\\textheight", "0.84\\linewidth"
        elif "pair_048_587" in path:
            max_h, max_w = "0.27\\textheight", "0.94\\linewidth"
        else:
            max_h, max_w = "0.34\\textheight", "0.94\\linewidth"
        return (
            "\n```{=latex}\n"
            "\\begin{figure}[H]\n"
            "\\centering\n"
            f"\\includegraphics[max width={max_w}, max height={max_h}, keepaspectratio]{{{path}}}\n"
            f"\\caption{{{cap_tex}}}\n"
            "\\end{figure}\n"
            "```\n"
        )

    md = single_img_re.sub(_sub_single_img, md)

    # 4. Chèn dòng trống trước danh sách gạch đầu dòng khi dòng trước không phải list/trống
    pre_lines = md.splitlines()
    spaced_lines = []
    for line in pre_lines:
        if line.strip().startswith("#### Bảng"):
            spaced_lines.append("\n```{=latex}\n\\needspace{7\\baselineskip}\n```\n")
        is_bullet = bool(re.match(r"^\s*[-*]\s+", line))
        if is_bullet and spaced_lines:
            prev = spaced_lines[-1]
            prev_is_bullet = bool(re.match(r"^\s*[-*]\s+", prev))
            if prev.strip() and not prev_is_bullet and not prev.strip().startswith("```"):
                spaced_lines.append("")
        spaced_lines.append(line)
    md = "\n".join(spaced_lines)

    # 5. Nới độ dài vạch ngăn bảng Markdown để Pandoc chia tỷ lệ cột longtable cân đối hơn
    lines = md.splitlines()
    adjusted_lines = []
    for line in lines:
        if line.strip().startswith("|") and "---" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 8:
                widths = [8, 9, 5, 5, 10, 18, 12, 33]
            elif len(cells) == 7:
                widths = [30, 14, 17, 10, 8, 6, 15]
            elif len(cells) == 3:
                widths = [28, 22, 50]
            elif len(cells) == 4:
                widths = [10, 34, 12, 34]
            else:
                widths = [max(len(c), 8) for c in cells]
            new_cells = []
            for c, w in zip(cells, widths):
                left = ":" if c.startswith(":") else "-"
                right = ":" if c.endswith(":") else "-"
                new_cells.append(left + ("-" * max(3, w - 2)) + right)
            adjusted_lines.append("| " + " | ".join(new_cells) + " |")
        else:
            adjusted_lines.append(line)

    return "\n".join(adjusted_lines) + "\n"


def postprocess_tex(tex: str) -> str:
    """Wrap CJK characters with Noto Serif CJK TC and fix Pandoc default table/title styling."""
    out_lines = []
    for line in tex.splitlines():
        if line.lstrip().startswith("%") or "\\hypersetup" in line or "pdftitle" in line:
            out_lines.append(line)
            continue
        out_lines.append(CJK_RUN_RE.sub(r"{\\cjkfont \1}", line))
    res = "\n".join(out_lines) + "\n"
    # Thêm tô nền nhạt xen kẽ hoặc viền nhẹ cho header bảng nếu cần giữ booktabs gọn gàng
    return res


def main() -> None:
    if not MD_SRC.exists():
        raise FileNotFoundError(f"Không tìm thấy file nguồn: {MD_SRC}")
    if not ARCH_PNG.exists():
        raise FileNotFoundError(f"Không tìm thấy ảnh sơ đồ: {ARCH_PNG}")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    pre_md_path = BUILD_DIR / "report_preprocessed.md"
    header_path = BUILD_DIR / "header.tex"
    tex_path = BUILD_DIR / "report.tex"

    raw_md = MD_SRC.read_text(encoding="utf-8")
    pre_md_path.write_text(preprocess_markdown(raw_md), encoding="utf-8")
    header_path.write_text(HEADER_TEX.strip() + "\n", encoding="utf-8")

    pandoc_cmd = [
        "pandoc",
        str(pre_md_path),
        "--from=markdown+tex_math_dollars+pipe_tables+raw_tex",
        "--to=latex",
        "--standalone",
        "--include-in-header", str(header_path),
        "-V", "documentclass=article",
        "-V", "papersize=a4",
        "-V", "geometry:top=1.55cm,bottom=1.55cm,left=1.6cm,right=1.6cm",
        "-V", "fontsize=10pt",
        "-V", "mainfont=Noto Serif",
        "-V", "sansfont=Fira Sans",
        "-V", "monofont=JetBrains Mono",
        "-V", "colorlinks=true",
        "-V", "linkcolor=AccentBlue",
        "-V", "urlcolor=AccentBlue",
        "-o", str(tex_path),
    ]
    subprocess.run(pandoc_cmd, cwd=str(ROOT_DIR), check=True)

    tex_content = tex_path.read_text(encoding="utf-8")
    tex_path.write_text(postprocess_tex(tex_content), encoding="utf-8")

    xelatex_cmd = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={BUILD_DIR}",
        str(tex_path),
    ]
    # Chạy 2 lần để cập nhật page numbers & table widths ổn định
    subprocess.run(xelatex_cmd, cwd=str(ROOT_DIR), check=True)
    subprocess.run(xelatex_cmd, cwd=str(ROOT_DIR), check=True)

    compiled_pdf = BUILD_DIR / "report.pdf"
    if not compiled_pdf.exists():
        raise RuntimeError("XeLaTeX không tạo được file report.pdf")

    PDF_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(compiled_pdf, PDF_OUT)
    print(f"Đã xuất PDF thành công: {PDF_OUT} ({PDF_OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
