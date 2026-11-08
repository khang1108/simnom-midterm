import argparse
import cv2
import numpy as np
from pathlib import Path

def analyze_image_statistics(img_path: Path):
    """Phân tích thống kê thực nghiệm phân phối Connected Components của 1 trang ảnh."""
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"Cannot read: {img_path}")
        return

    h, w = img.shape
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)

    if num_labels <= 1:
        print(f"[{img_path.name}] No components found.")
        return

    areas = stats[1:, cv2.CC_STAT_AREA]
    widths = stats[1:, cv2.CC_STAT_WIDTH]
    heights = stats[1:, cv2.CC_STAT_HEIGHT]

    print(f"=== EDA Phân Tích Thực Nghiệm: {img_path.name} ({w}x{h}) ===")
    print(f"Tổng số Connected Components: {len(areas)}")
    print(f"Area:   min={np.min(areas)}, Q25={np.percentile(areas, 25):.1f}, Median={np.median(areas):.1f}, Q75={np.percentile(areas, 75):.1f}, max={np.max(areas)}")
    print(f"Width:  min={np.min(widths)}, Q25={np.percentile(widths, 25):.1f}, Median={np.median(widths):.1f}, Q75={np.percentile(widths, 75):.1f}, max={np.max(widths)}")
    print(f"Height: min={np.min(heights)}, Q25={np.percentile(heights, 25):.1f}, Median={np.median(heights):.1f}, Q75={np.percentile(heights, 75):.1f}, max={np.max(heights)}")

def main():
    parser = argparse.ArgumentParser(description="EDA Tool to profile empirical page stats.")
    parser.add_argument("--image", type=str, required=True, help="Path to image file")
    args = parser.parse_args()
    analyze_image_statistics(Path(args.image))

if __name__ == "__main__":
    main()

