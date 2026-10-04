"""
Generator ikon aplikasi Asisten Tugas Citra (ATC).
Membuat berkas icon.png (1024x1024) dan multi-resolution icon.ico (256, 128, 64, 48, 32, 16)
dengan teknik supersampling anti-aliasing berkualitas tinggi.
"""
import os
from PIL import Image, ImageDraw, ImageFont

def create_app_icon(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    size = 1024
    
    # 1. Canvas transparan
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 2. Squircle / Rounded Rect background ala Modern Academic Minimalist
    # Deep Obsidian dengan gradasi elegan
    margin = 48
    box = [margin, margin, size - margin, size - margin]
    radius = 210
    
    # Bayangan lembut luar (subtle drop shadow)
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [margin, margin + 20, size - margin, size - margin + 20],
        radius=radius,
        fill=(0, 0, 0, 110)
    )
    
    # Background utama Deep Obsidian
    draw.rounded_rectangle(box, radius=radius, fill=(28, 25, 23, 255)) # #1c1917
    
    # Border halus Stone-700
    draw.rounded_rectangle(box, radius=radius, outline=(68, 64, 60, 255), width=10) # #44403c
    
    # Subtle inner highlight di bagian atas
    highlight_box = [margin + 8, margin + 8, size - margin - 8, margin + 40]
    draw.rounded_rectangle(highlight_box, radius=16, fill=(255, 255, 255, 12))
    
    # 3. Elemen Visual: Naskah / Buku Akademik Terbuka & Bukti Sitasi Emerald
    # Gambar buku terbuka yang simetris dan elegan
    center_x = size // 2
    spine_y_top = 310
    spine_y_bot = 730
    page_width = 250
    page_lift = 60
    
    # Halaman Kiri (Ivory Stone #f5f5f4)
    left_poly = [
        (center_x - 12, spine_y_top + 15),
        (center_x - page_width, spine_y_top - page_lift),
        (center_x - page_width, spine_y_bot - page_lift),
        (center_x - 12, spine_y_bot + 15)
    ]
    draw.polygon(left_poly, fill=(245, 245, 244, 255))
    
    # Halaman Kanan (Warm Stone #fafaf9)
    right_poly = [
        (center_x + 12, spine_y_top + 15),
        (center_x + page_width, spine_y_top - page_lift),
        (center_x + page_width, spine_y_bot - page_lift),
        (center_x + 12, spine_y_bot + 15)
    ]
    draw.polygon(right_poly, fill=(250, 250, 249, 255))
    
    # Garis lipatan / bayangan spine tengah
    draw.rectangle([center_x - 12, spine_y_top + 15, center_x + 12, spine_y_bot + 15], fill=(214, 211, 209, 255))
    
    # Garis-garis teks ilmiah di halaman kiri (Stone-400 / #a8a29e)
    line_color_left = (168, 162, 158, 255)
    for i in range(4):
        ly = spine_y_top + 80 + i * 75
        lx_start = center_x - page_width + 45
        lx_end = center_x - 45 - (40 if i == 3 else 0)
        draw.line([(lx_start, ly - page_lift + 30), (lx_end, ly + 5)], fill=line_color_left, width=16)
        
    # Garis-garis teks ilmiah di halaman kanan
    line_color_right = (168, 162, 158, 255)
    for i in range(4):
        ry = spine_y_top + 80 + i * 75
        rx_start = center_x + 45
        rx_end = center_x + page_width - 45 - (50 if i == 3 else 0)
        draw.line([(rx_start, ry + 5), (rx_end, ry - page_lift + 30)], fill=line_color_right, width=16)

    # 4. Aksen Pita Pembatas / Bookmark Pita Emerald (#10b981) menjuntai dari tengah atas
    ribbon_w = 44
    ribbon_x1 = center_x - ribbon_w // 2
    ribbon_x2 = center_x + ribbon_w // 2
    ribbon_top = spine_y_top - 40
    ribbon_bot = spine_y_bot + 70
    v_notch = 28
    
    ribbon_poly = [
        (ribbon_x1, ribbon_top),
        (ribbon_x2, ribbon_top),
        (ribbon_x2, ribbon_bot),
        (center_x, ribbon_bot - v_notch),
        (ribbon_x1, ribbon_bot)
    ]
    draw.polygon(ribbon_poly, fill=(16, 185, 129, 255)) # Emerald 500
    
    # Garis tepi pita halus
    draw.polygon(ribbon_poly, outline=(5, 150, 105, 255)) # Emerald 600
    
    # 5. Badge "ATC" kecil monogram modern di bawah
    # Badge melengkung di bagian bawah buku
    badge_w = 180
    badge_h = 56
    badge_box = [center_x - badge_w // 2, 790, center_x + badge_w // 2, 790 + badge_h]
    draw.rounded_rectangle(badge_box, radius=20, fill=(41, 37, 36, 255), outline=(120, 113, 108, 255), width=4)
    
    # Teks ATC
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    
    text = "ATC"
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((center_x - tw // 2, 790 + (badge_h - th) // 2 - 4), text, fill=(250, 250, 249, 255), font=font)
    
    # 6. Simpan Master PNG
    master_png = os.path.join(output_dir, "icon.png")
    img.save(master_png, "PNG")
    print(f"Master icon saved: {master_png}")
    
    # 7. Ekspor Multi-Resolution ICO untuk Windows
    # Windows Explorer membutuhkan variasi ukuran: 256, 128, 64, 48, 32, 16
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    master_ico = os.path.join(output_dir, "icon.ico")
    
    img.save(
        master_ico,
        format="ICO",
        sizes=ico_sizes
    )
    print(f"Windows multi-resolution ICO saved: {master_ico}")
    
    # Salin juga ke root sebagai app.ico untuk kemudahan PyInstaller
    root_ico = os.path.abspath("app.ico")
    img.save(root_ico, format="ICO", sizes=ico_sizes)
    print(f"Root ICO saved: {root_ico}")

if __name__ == "__main__":
    create_app_icon("assets")
