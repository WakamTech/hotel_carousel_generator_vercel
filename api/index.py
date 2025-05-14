# api/index.py
import json
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
from io import BytesIO
import textwrap
import math
from flask import Flask, request, jsonify, send_from_directory
import shutil
import time
import re # Ajouté pour slugify
import unicodedata # Ajouté pour slugify
import traceback # Était utilisé, mais pas importé explicitement, ajout pour la clarté

# --- Configuration ---
# Sur Vercel, les fichiers temporaires doivent être écrits dans /tmp
VERCEL_TMP_DIR = "/tmp"
OUTPUT_DIR_NAME = "output_carousels_temp" # Nom du dossier dans /tmp
OUTPUT_DIR = os.path.join(VERCEL_TMP_DIR, OUTPUT_DIR_NAME)

IMAGE_SIZE = (1080, 1080)
BACKGROUND_COLOR_SLIDE1 = (20, 30, 40)
TEXT_COLOR_SLIDE1_HOTEL_NAME = (252, 196, 60)
TEXT_COLOR_SLIDE1_RATING_TEXT = (240, 240, 240)
IMAGE_OVERLAY_BG_COLOR = (0, 0, 0, 160)
IMAGE_SLIDE_EQUIPMENT_TEXT_COLOR = (252, 196, 60)
IMAGE_SLIDE_FOOTER_TEXT_COLOR = (255, 255, 255)

BASE_DIR_OF_SCRIPT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_DIR = os.path.dirname(BASE_DIR_OF_SCRIPT)
FONT_DIR = os.path.join(PROJECT_ROOT_DIR, "fonts")

FONT_SHRIKHAND_PATH = os.path.join(FONT_DIR, "Shrikhand-Regular.ttf")
FONT_BOLD_PATH = os.path.join(FONT_DIR, "Roboto-Bold.ttf")
FONT_REGULAR_PATH = os.path.join(FONT_DIR, "Roboto-Regular.ttf")

SLIDE1_HOTEL_NAME_FONT_SIZE = 120
SLIDE1_RATING_TEXT_FONT_SIZE = 50
SLIDE1_STAR_SIZE = 40
IMAGE_SLIDE_EQUIPMENT_FONT_SIZE = 80
IMAGE_SLIDE_FOOTER_HOTEL_NAME_SIZE = 35
IMAGE_SLIDE_FOOTER_RATING_SIZE = 35
IMAGE_SLIDE_STAR_SIZE = 30

PADDING = 70
LINE_SPACING_TITLE = 15
SECTION_SPACING = 40
IMAGE_SLIDE_TEXT_MARGIN = 50
FOOTER_BAND_HEIGHT = 100
FOOTER_PADDING = 30
STAR_TEXT_PADDING = 10

app = Flask(__name__)

font_shrikhand_check = None
font_bold_check = None
font_regular_check = None
try:
    font_shrikhand_check = ImageFont.truetype(FONT_SHRIKHAND_PATH, 10)
    font_bold_check = ImageFont.truetype(FONT_BOLD_PATH, 10)
    font_regular_check = ImageFont.truetype(FONT_REGULAR_PATH, 10)
    print("Polices principales chargées avec succès au démarrage de l'API.")
except IOError as e:
    print(f"ERREUR CRITIQUE AU DÉMARRAGE DE L'API: Impossible de charger une ou plusieurs polices depuis '{FONT_DIR}'. Erreur: {e}")

# --- Fonctions Utilitaires (y compris le nouveau slugify) ---

def slugify_filename(value, allow_unicode=False, char_limit=50):
    """
    Convertit une chaîne en un nom de fichier "slug" sûr.
    Les accents sont convertis en ASCII. Les caractères non alphanumériques
    sont remplacés par des underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower() # Supprime ce qui n'est pas mot, espace, ou tiret
    value = re.sub(r'[-\s]+', '_', value) # Remplace espaces et tirets par underscore
    value = re.sub(r'_+', '_', value) # Remplace multiples underscores par un seul
    return value[:char_limit]


def download_image(url):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        return img.convert("RGBA")
    except requests.exceptions.RequestException as e:
        print(f"  Avertissement: Erreur téléchargement {url}: {e}")
    except IOError:
        print(f"  Avertissement: Erreur ouverture image {url}.")
    except Exception as e:
        print(f"  Avertissement: Erreur inconnue {url}: {e}")
    return None

def resize_and_crop_to_square(img, target_size):
    try:
        return ImageOps.fit(img, target_size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    except Exception as e:
        print(f"  Avertissement: Erreur lors du redimensionnement/recadrage : {e}")
        placeholder = Image.new('RGB', target_size, (210, 210, 210))
        draw = ImageDraw.Draw(placeholder)
        try:
            font_path_placeholder = FONT_REGULAR_PATH if font_regular_check else "arial.ttf"
            font_placeholder_pil = ImageFont.truetype(font_path_placeholder, 40)
            text = "Erreur Image"
            bbox = font_placeholder_pil.getbbox(text)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((target_size[0]-w)/2, (target_size[1]-h)/2), text, font=font_placeholder_pil, fill=(100,100,100), anchor="lt")
        except Exception as font_error:
            print(f"  Avertissement: Impossible de charger la police pour le placeholder: {font_error}")
        return placeholder

def get_text_dimensions(text_string, font):
    if not text_string: return 0, 0
    bbox = font.getbbox(text_string)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def draw_multiline_text_custom_align(draw, text_lines, start_x_coord, start_y_coord, font, fill_color, line_spacing_val, align="left", container_width_val=None, max_total_height_val=None):
    current_y = start_y_coord
    lines_drawn_height = 0
    valid_text_lines = [line for line in text_lines if line.strip()]
    if not valid_text_lines: return current_y

    for i, line in enumerate(valid_text_lines):
        line_width, line_height = get_text_dimensions(line, font)

        if max_total_height_val and (lines_drawn_height + line_height > max_total_height_val):
            if i > 0:
                prev_line_bbox = font.getbbox(valid_text_lines[i-1])
                prev_line_height_actual = prev_line_bbox[3] - prev_line_bbox[1]
                current_y -= (prev_line_height_actual + line_spacing_val)
                
                ellipsis_width, ellipsis_height = get_text_dimensions("...", font)
                final_x_ellipsis = start_x_coord
                if align == "center" and container_width_val:
                    final_x_ellipsis = (container_width_val - ellipsis_width) / 2
                elif align == "right" and container_width_val:
                    final_x_ellipsis = container_width_val - PADDING - ellipsis_width
                
                draw.text((final_x_ellipsis, current_y), "...", font=font, fill=fill_color, anchor="la")
                current_y += ellipsis_height 
            break
        
        actual_x_pos = start_x_coord
        if align == "center" and container_width_val:
            actual_x_pos = (container_width_val - line_width) / 2
        elif align == "right" and container_width_val:
            actual_x_pos = container_width_val - PADDING - line_width
        
        draw.text((actual_x_pos, current_y), line, font=font, fill=fill_color, anchor="la")
        current_y += line_height + line_spacing_val
        
        lines_drawn_height += line_height
        if i < len(valid_text_lines) - 1:
             lines_drawn_height += line_spacing_val
            
    return current_y

def draw_star(draw, x_center, y_center, size, fill_color):
    points = []
    outer_radius = size / 2
    inner_radius = outer_radius * 0.382 
    for i in range(5):
        angle_outer = math.radians(i * 72 - 90) 
        points.append((x_center + outer_radius * math.cos(angle_outer),
                       y_center + outer_radius * math.sin(angle_outer)))
        angle_inner = math.radians((i * 72 + 36) - 90) 
        points.append((x_center + inner_radius * math.cos(angle_inner),
                       y_center + inner_radius * math.sin(angle_inner)))
    draw.polygon(points, fill=fill_color)

# --- Fonctions de création de slides ---

def create_first_slide(hotel_info):
    if not font_shrikhand_check or not font_bold_check:
        raise RuntimeError("Polices principales non initialisées pour create_first_slide.")

    img = Image.new('RGB', IMAGE_SIZE, BACKGROUND_COLOR_SLIDE1)
    draw = ImageDraw.Draw(img)
    font_hotel_name = ImageFont.truetype(FONT_SHRIKHAND_PATH, SLIDE1_HOTEL_NAME_FONT_SIZE)
    font_rating_text = ImageFont.truetype(FONT_BOLD_PATH, SLIDE1_RATING_TEXT_FONT_SIZE)
    hotel_name = hotel_info.get('hotelName', 'Hôtel Inconnu')
    name_lines = textwrap.wrap(hotel_name, width=18) 
    total_name_text_height = 0
    for line in name_lines: _, line_h = get_text_dimensions(line, font_hotel_name); total_name_text_height += line_h + LINE_SPACING_TITLE
    if name_lines: total_name_text_height -= LINE_SPACING_TITLE
    _, rating_line_height = get_text_dimensions("Noté : 9.9", font_rating_text)
    height_for_rating_line = max(rating_line_height, SLIDE1_STAR_SIZE)
    available_vertical_space_for_name = IMAGE_SIZE[1] - (PADDING * 2) - height_for_rating_line - SECTION_SPACING 
    start_y_name = PADDING + (available_vertical_space_for_name - total_name_text_height) / 2
    start_y_name = max(PADDING, start_y_name)
    draw_multiline_text_custom_align(draw, name_lines, 0, start_y_name, font_hotel_name, TEXT_COLOR_SLIDE1_HOTEL_NAME, LINE_SPACING_TITLE, align="center", container_width_val=IMAGE_SIZE[0])
    rating = hotel_info.get('rating', 'N/A'); rating_display_text = f"Noté : {rating}"
    rating_text_width, rating_text_actual_height = get_text_dimensions(rating_display_text, font_rating_text)
    total_rating_element_width = rating_text_width + STAR_TEXT_PADDING + SLIDE1_STAR_SIZE
    x_rating_start_centered = (IMAGE_SIZE[0] - total_rating_element_width) / 2
    y_rating_base = IMAGE_SIZE[1] - PADDING - height_for_rating_line
    y_text_final = y_rating_base + (height_for_rating_line - rating_text_actual_height) / 2
    draw.text((x_rating_start_centered, y_text_final), rating_display_text, font=font_rating_text, fill=TEXT_COLOR_SLIDE1_RATING_TEXT, anchor="la")
    x_star_center = x_rating_start_centered + rating_text_width + STAR_TEXT_PADDING + (SLIDE1_STAR_SIZE / 2)
    y_star_center = y_rating_base + height_for_rating_line / 2
    draw_star(draw, x_star_center, y_star_center, SLIDE1_STAR_SIZE, TEXT_COLOR_SLIDE1_RATING_TEXT)
    return img

def create_amenity_image_slide(image_url, hotel_name, amenity_text, rating):
    if not font_bold_check or not font_regular_check:
        raise RuntimeError("Polices Bold ou Regular non initialisées pour create_amenity_image_slide.")

    base_img = download_image(image_url)
    img_slide_base_rgba = Image.new('RGBA', IMAGE_SIZE, (220, 220, 220, 255)) 
    if base_img:
        if base_img.mode != 'RGBA': base_img = base_img.convert('RGBA')
        cropped_img = resize_and_crop_to_square(base_img, IMAGE_SIZE)
        img_slide_base_rgba.paste(cropped_img, (0,0))
    else:
        draw_placeholder = ImageDraw.Draw(img_slide_base_rgba)
        # Utiliser une police système de base si les polices personnalisées échouent au démarrage
        font_path_placeholder = FONT_REGULAR_PATH if font_regular_check else "arial.ttf" # Fallback vers arial
        font_placeholder = ImageFont.truetype(font_path_placeholder, 50)
        placeholder_text = "Image Indisponible"; w_placeholder, h_placeholder = get_text_dimensions(placeholder_text, font_placeholder)
        draw_placeholder.text(((IMAGE_SIZE[0]-w_placeholder)/2, (IMAGE_SIZE[1]-h_placeholder)/2), placeholder_text, font=font_placeholder, fill=(100,100,100,255), anchor="lt")
    
    overlay = Image.new('RGBA', IMAGE_SIZE, (0,0,0,0)); draw_overlay = ImageDraw.Draw(overlay)
    font_equipment = ImageFont.truetype(FONT_BOLD_PATH, IMAGE_SLIDE_EQUIPMENT_FONT_SIZE)
    equipment_lines = textwrap.wrap(amenity_text, width=16) 
    total_equipment_text_height = 0; max_equipment_line_width = 0
    for line in equipment_lines: w, line_h = get_text_dimensions(line, font_equipment); total_equipment_text_height += line_h + LINE_SPACING_TITLE; max_equipment_line_width = max(max_equipment_line_width, w)
    if equipment_lines: total_equipment_text_height -= LINE_SPACING_TITLE
    start_y_equipment = (IMAGE_SIZE[1] - FOOTER_BAND_HEIGHT - total_equipment_text_height) / 2; start_y_equipment = max(IMAGE_SLIDE_TEXT_MARGIN, start_y_equipment)
    
    if equipment_lines:
        equipment_bg_padding_x = 40; equipment_bg_padding_y = 25
        bg_x0 = (IMAGE_SIZE[0] - max_equipment_line_width) / 2 - equipment_bg_padding_x; bg_y0 = start_y_equipment - equipment_bg_padding_y 
        bg_x1 = bg_x0 + max_equipment_line_width + 2 * equipment_bg_padding_x; bg_y1 = start_y_equipment + total_equipment_text_height + equipment_bg_padding_y
        bg_y1 = min(bg_y1, IMAGE_SIZE[1] - FOOTER_BAND_HEIGHT - PADDING/4)
        if bg_x1 > bg_x0 and bg_y1 > bg_y0:
            temp_bg_img = Image.new('RGBA', IMAGE_SIZE, (0,0,0,0)); temp_draw = ImageDraw.Draw(temp_bg_img)
            temp_draw.rounded_rectangle([(bg_x0, bg_y0), (bg_x1, bg_y1)], radius=30, fill=IMAGE_OVERLAY_BG_COLOR); overlay.paste(temp_bg_img, (0,0), temp_bg_img)
    
    draw_multiline_text_custom_align(draw_overlay, equipment_lines, 0, start_y_equipment, font_equipment, IMAGE_SLIDE_EQUIPMENT_TEXT_COLOR, LINE_SPACING_TITLE, align="center", container_width_val=IMAGE_SIZE[0])
    
    footer_y_start = IMAGE_SIZE[1] - FOOTER_BAND_HEIGHT; draw_overlay.rectangle([(0, footer_y_start), (IMAGE_SIZE[0], IMAGE_SIZE[1])], fill=IMAGE_OVERLAY_BG_COLOR)
    font_footer_hotel_name = ImageFont.truetype(FONT_BOLD_PATH, IMAGE_SLIDE_FOOTER_HOTEL_NAME_SIZE)
    font_footer_rating = ImageFont.truetype(FONT_BOLD_PATH, IMAGE_SLIDE_FOOTER_RATING_SIZE)
    truncated_hotel_name_footer = textwrap.shorten(hotel_name, width=35, placeholder="..."); _, name_footer_height = get_text_dimensions(truncated_hotel_name_footer, font_footer_hotel_name)
    y_hotel_name_footer = footer_y_start + (FOOTER_BAND_HEIGHT - name_footer_height) / 2
    draw_overlay.text((FOOTER_PADDING, y_hotel_name_footer), truncated_hotel_name_footer, font=font_footer_hotel_name, fill=IMAGE_SLIDE_FOOTER_TEXT_COLOR, anchor="la")
    
    if rating:
        rating_footer_text = f"{rating}"; rating_text_width, rating_text_height = get_text_dimensions(rating_footer_text, font_footer_rating)
        x_rating_text_footer = IMAGE_SIZE[0] - FOOTER_PADDING - IMAGE_SLIDE_STAR_SIZE - STAR_TEXT_PADDING - rating_text_width
        combined_height_rating_star = max(rating_text_height, IMAGE_SLIDE_STAR_SIZE)
        y_rating_elements_base = footer_y_start + (FOOTER_BAND_HEIGHT - combined_height_rating_star) / 2
        y_rating_text_final_footer = y_rating_elements_base + (combined_height_rating_star - rating_text_height) / 2
        draw_overlay.text((x_rating_text_footer, y_rating_text_final_footer), rating_footer_text, font=font_footer_rating, fill=IMAGE_SLIDE_FOOTER_TEXT_COLOR, anchor="la")
        x_star_footer_center = x_rating_text_footer + rating_text_width + STAR_TEXT_PADDING + (IMAGE_SLIDE_STAR_SIZE / 2)
        y_star_footer_center = y_rating_elements_base + combined_height_rating_star / 2
        draw_star(draw_overlay, x_star_footer_center, y_star_footer_center, IMAGE_SLIDE_STAR_SIZE, IMAGE_SLIDE_FOOTER_TEXT_COLOR)
    
    img_slide_final = Image.alpha_composite(img_slide_base_rgba, overlay)
    return img_slide_final.convert('RGB')

# --- Logique principale de génération de carrousel ---

def generate_and_save_carousel(hotel_data):
    hotel_name = hotel_data.get('hotelName', 'hotel_inconnu')
    timestamp = int(time.time())
    
    # Utilisation de la fonction slugify pour un nom de dossier propre et sûr
    hotel_slug_base = slugify_filename(hotel_name, char_limit=40) # Augmenté un peu la limite pour le slug
    
    unique_folder_name = f"{hotel_slug_base}_{timestamp}"
    hotel_specific_output_dir = os.path.join(OUTPUT_DIR, unique_folder_name)
    
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(hotel_specific_output_dir, exist_ok=True)
    print(f"  Création du dossier temporaire : {hotel_specific_output_dir}")

    generated_image_relative_paths = []
    try:
        first_slide = create_first_slide(hotel_data)
        cover_filename = "00_cover.png"
        cover_path_absolute = os.path.join(hotel_specific_output_dir, cover_filename)
        first_slide.save(cover_path_absolute)
        generated_image_relative_paths.append(cover_filename)
        print(f"  Diapositive de couverture créée : {cover_path_absolute}")
    except Exception as e:
        print(f"  Erreur création slide titre pour {hotel_name}: {e}")
        traceback.print_exc()

    image_urls = hotel_data.get('imageUrls', [])
    amenities = hotel_data.get('popularAmenities', [])
    rating_value = hotel_data.get('rating', '')
    hotel_name_for_footer = hotel_data.get('hotelName', 'Hôtel')
    num_image_slides = min(len(image_urls), 5)

    for i in range(num_image_slides):
        image_url = image_urls[i]
        amenity_for_slide = amenities[i % len(amenities)] if amenities else "Découvrez nos services"
        try:
            image_slide = create_amenity_image_slide(image_url, hotel_name_for_footer, amenity_for_slide, rating_value)
            if image_slide:
                img_filename = f"{i+1:02d}_image.png"
                img_path_absolute = os.path.join(hotel_specific_output_dir, img_filename)
                image_slide.save(img_path_absolute)
                generated_image_relative_paths.append(img_filename)
                print(f"  Diapositive image {i+1} créée : {img_path_absolute}")
        except Exception as e:
            print(f"  Erreur création slide image {i+1} pour {hotel_name}: {e}")
            traceback.print_exc()
            
    return unique_folder_name, generated_image_relative_paths

# --- Routes Flask ---

@app.route('/api/generate', methods=['POST'])
def handle_generate_carousel_request():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    hotel_data = request.get_json()
    if not hotel_data or not isinstance(hotel_data, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    hotel_name = hotel_data.get('hotelName', 'hotel_inconnu')
    print(f"\nRequête reçue pour générer un carrousel pour : {hotel_name}")

    try:
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            print(f"Dossier de sortie principal créé dans /tmp : {OUTPUT_DIR}")

        unique_subfolder_name, relative_image_paths = generate_and_save_carousel(hotel_data)
        
        base_public_url = request.host_url.rstrip('/')
        carousel_public_urls = [
            f"{base_public_url}/generated_images/{unique_subfolder_name}/{os.path.basename(p)}" 
            for p in relative_image_paths
        ]
        response_data = {
            "hotelName": hotel_name,
            "carouselImageUrls": carousel_public_urls,
            "status": "success",
            "generatedFilesIn": f"/tmp/{OUTPUT_DIR_NAME}/{unique_subfolder_name}" # Chemin Vercel
        }
        print(f"  Carrousel généré pour {hotel_name}. URLs publiques: {carousel_public_urls}")
        return jsonify(response_data), 200
    except Exception as e:
        print(f"Erreur majeure lors de la génération du carrousel pour {hotel_name}: {e}")
        traceback.print_exc()
        return jsonify({"error": "Erreur interne du serveur lors de la génération des images", "details": str(e)}), 500

@app.route('/generated_images/<path:carousel_folder>/<path:filename>')
def serve_generated_image(carousel_folder, filename):
    # Nettoyage simple pour la sécurité, même si slugify devrait déjà aider
    safe_carousel_folder = slugify_filename(carousel_folder, char_limit=100) # Re-slugify pour être sûr
    # Pour filename, on s'attend à un format comme "00_cover.png" ou "01_image.png"
    # On peut être plus strict si nécessaire.
    safe_filename = "".join(c for c in filename if c.isalnum() or c in ['_', '-', '.'])

    if carousel_folder != safe_carousel_folder:
        # Le slugify peut modifier légèrement, donc cette vérification peut être trop stricte
        # Si le slugify de la route est identique au slugify original, c'est bon.
        # Le principal est que safe_carousel_folder soit bien formé.
        print(f"Avertissement: Le chemin du dossier du carrousel a été normalisé de '{carousel_folder}' à '{safe_carousel_folder}'")

    if filename != safe_filename:
        print(f"Avertissement: Le nom de fichier a été normalisé de '{filename}' à '{safe_filename}'")
        # Pourrait retourner 400 si le nom de fichier d'origine contenait des caractères manifestement dangereux
        # return jsonify({"error": "Nom de fichier invalide"}), 400

    directory_path = os.path.join(VERCEL_TMP_DIR, OUTPUT_DIR_NAME, safe_carousel_folder)
    
    # Vérification de sécurité pour éviter le path traversal
    abs_output_dir_root = os.path.abspath(os.path.join(VERCEL_TMP_DIR, OUTPUT_DIR_NAME))
    abs_requested_dir_path = os.path.abspath(directory_path)

    if not abs_requested_dir_path.startswith(abs_output_dir_root):
        print(f"Tentative d'accès non autorisé (path traversal) pour image: {abs_requested_dir_path} (base attendue: {abs_output_dir_root})")
        return jsonify({"error": "Accès non autorisé - chemin invalide"}), 403

    print(f"Tentative de servir: {safe_filename} depuis {directory_path}")
    try:
        return send_from_directory(directory_path, safe_filename)
    except FileNotFoundError:
        print(f"Image non trouvée: {os.path.join(directory_path, safe_filename)}")
        return jsonify({"error": "Image non trouvée"}), 404
    except Exception as e:
        print(f"Erreur en servant l'image: {e}")
        traceback.print_exc()
        return jsonify({"error": "Erreur serveur en servant l'image"}), 500


if __name__ == "__main__":
    print("Lancement du serveur Flask de développement local...")
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(FONT_DIR):
         print(f"ATTENTION: Le dossier de polices '{FONT_DIR}' n'existe pas ou n'est pas accessible.")
         print("La génération d'images échouera si les polices ne sont pas trouvées.")
         # Optionnel: créer le dossier s'il n'existe pas, mais l'utilisateur doit y mettre les polices.
         # os.makedirs(FONT_DIR, exist_ok=True)
         # print(f"Dossier '{FONT_DIR}' créé. Assurez-vous d'y placer les polices.")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))