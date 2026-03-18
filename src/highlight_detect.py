"""Highlight detection for credit card statements using OpenCV."""

import logging
import numpy as np
import cv2

logger = logging.getLogger(__name__)

# HSV ranges for common highlighter colors
HIGHLIGHT_RANGES = [
    # Yellow highlighter
    {"lower": np.array([15, 40, 180]), "upper": np.array([45, 255, 255])},
    # Green highlighter
    {"lower": np.array([35, 40, 180]), "upper": np.array([85, 255, 255])},
    # Pink/magenta highlighter
    {"lower": np.array([140, 30, 180]), "upper": np.array([175, 255, 255])},
    # Orange highlighter
    {"lower": np.array([5, 50, 180]), "upper": np.array([20, 255, 255])},
    # Light blue highlighter
    {"lower": np.array([85, 30, 180]), "upper": np.array([130, 200, 255])},
]


def detect_highlighted_regions(image: np.ndarray) -> np.ndarray:
    """Detect highlighted/marked regions in an image.

    Returns a binary mask where highlighted areas are white (255).
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    combined_mask = np.zeros(image.shape[:2], dtype=np.uint8)

    for color_range in HIGHLIGHT_RANGES:
        mask = cv2.inRange(hsv, color_range["lower"], color_range["upper"])
        combined_mask = cv2.bitwise_or(combined_mask, mask)

    # Dilate to connect nearby highlighted areas
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 10))
    combined_mask = cv2.dilate(combined_mask, kernel, iterations=2)

    # Remove very small regions (noise)
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = image.shape[0] * image.shape[1] * 0.001  # 0.1% of image area
    clean_mask = np.zeros_like(combined_mask)
    for cnt in contours:
        if cv2.contourArea(cnt) > min_area:
            cv2.drawContours(clean_mask, [cnt], -1, 255, -1)

    return clean_mask


def filter_highlighted_text(
    ocr_entries: list[dict], highlight_mask: np.ndarray, overlap_threshold: float = 0.3
) -> list[dict]:
    """Filter OCR entries to keep only those overlapping with highlighted regions.

    Args:
        ocr_entries: List of {text, bbox, confidence} from OCR.
        highlight_mask: Binary mask from detect_highlighted_regions.
        overlap_threshold: Minimum overlap ratio to consider text as highlighted.

    Returns:
        Filtered list of OCR entries that are in highlighted regions.
    """
    highlighted = []
    for entry in ocr_entries:
        bbox = entry["bbox"]
        # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x_min, x_max = int(min(xs)), int(max(xs))
        y_min, y_max = int(min(ys)), int(max(ys))

        # Clamp to image bounds
        h, w = highlight_mask.shape
        x_min = max(0, x_min)
        y_min = max(0, y_min)
        x_max = min(w - 1, x_max)
        y_max = min(h - 1, y_max)

        if x_max <= x_min or y_max <= y_min:
            continue

        # Calculate overlap ratio
        roi = highlight_mask[y_min:y_max, x_min:x_max]
        total_pixels = roi.size
        if total_pixels == 0:
            continue
        highlighted_pixels = np.count_nonzero(roi)
        overlap = highlighted_pixels / total_pixels

        if overlap >= overlap_threshold:
            highlighted.append(entry)

    logger.info(f"Highlight filter: {len(highlighted)}/{len(ocr_entries)} entries highlighted")
    return highlighted


def extract_highlighted_lines(
    ocr_entries: list[dict], highlight_mask: np.ndarray, overlap_threshold: float = 0.3
) -> list[str]:
    """Extract highlighted text, grouped into lines by Y-coordinate.

    Groups OCR entries by their vertical position, then for each line group,
    if ANY entry in the line is highlighted, includes the ENTIRE line.
    Returns reconstructed text lines sorted top-to-bottom.
    """
    if not ocr_entries:
        return []

    # Add center-y to each entry for grouping
    enriched = []
    for entry in ocr_entries:
        bbox = entry["bbox"]
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        cy = (min(ys) + max(ys)) / 2
        cx = min(xs)
        enriched.append({"entry": entry, "cy": cy, "cx": cx})

    # Sort by y
    enriched.sort(key=lambda e: e["cy"])

    # Group into lines (entries within ~15px vertical distance)
    lines: list[list[dict]] = []
    current_line = [enriched[0]]
    for item in enriched[1:]:
        if abs(item["cy"] - current_line[-1]["cy"]) < 15:
            current_line.append(item)
        else:
            lines.append(current_line)
            current_line = [item]
    lines.append(current_line)

    # Check each line: if any entry overlaps highlight, include the whole line
    highlighted_lines = []
    h, w = highlight_mask.shape

    for line_items in lines:
        line_has_highlight = False
        for item in line_items:
            bbox = item["entry"]["bbox"]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x_min = max(0, int(min(xs)))
            y_min = max(0, int(min(ys)))
            x_max = min(w - 1, int(max(xs)))
            y_max = min(h - 1, int(max(ys)))

            if x_max <= x_min or y_max <= y_min:
                continue

            roi = highlight_mask[y_min:y_max, x_min:x_max]
            if roi.size > 0 and np.count_nonzero(roi) / roi.size >= overlap_threshold:
                line_has_highlight = True
                break

        if line_has_highlight:
            # Sort entries left-to-right within the line
            line_items.sort(key=lambda e: e["cx"])
            text = "  ".join(item["entry"]["text"] for item in line_items)
            highlighted_lines.append(text)

    logger.info(f"Highlight lines: {len(highlighted_lines)} out of {len(lines)} total lines")
    return highlighted_lines


def has_highlights(image: np.ndarray) -> bool:
    """Quick check if an image has any highlighted regions."""
    mask = detect_highlighted_regions(image)
    highlight_ratio = np.count_nonzero(mask) / mask.size
    return highlight_ratio > 0.005  # At least 0.5% of image is highlighted
