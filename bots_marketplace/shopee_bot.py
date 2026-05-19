import os
import re
import json
import time
import random
import logging
import shutil
from pathlib import Path
from dotenv import load_dotenv
import pyautogui
import pyperclip
from PIL import Image, ImageGrab

from llm_category import obter_categoria_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

def expand_path(path_str: str) -> Path:
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

JSON_PATH = expand_path(os.getenv("JSON_SHOPEE", ""))
IMAGES_DIR = expand_path(os.getenv("IMAGES_SHOPEE", ""))
LINKS_FILE = expand_path(os.getenv("TXT_SHOPEE", ""))

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

if not LINKS_FILE.exists():
    raise FileNotFoundError(f"Arquivo de links não encontrado: {LINKS_FILE}")

def choose_machine():
    print("\nEscolha a máquina que está usando:")
    print("1 - Linux")
    print("2 - Windows")
    while True:
        choice = input("Digite 1 ou 2: ").strip()
        if choice == "1":
            return "linux"
        elif choice == "2":
            return "windows"
        else:
            print("Opção inválida. Tente novamente.")

MACHINE = choose_machine()
PREFIX = "SHOPEE_LINUX" if MACHINE == "linux" else "SHOPEE_WINDOWS"
METHOD = os.getenv(f"{PREFIX}_METHOD", "save" if MACHINE == "linux" else "copy")

ADDRESS_BAR_X = int(os.getenv(f"{PREFIX}_ADDRESS_BAR_X", "0"))
ADDRESS_BAR_Y = int(os.getenv(f"{PREFIX}_ADDRESS_BAR_Y", "0"))
CLICK_COPY_X = int(os.getenv(f"{PREFIX}_CLICK_COPY_X", "0"))
CLICK_COPY_Y = int(os.getenv(f"{PREFIX}_CLICK_COPY_Y", "0"))

if MACHINE == "linux":
    SAVE_RIGHT_CLICK_X = int(os.getenv(f"{PREFIX}_SAVE_RIGHT_CLICK_X", "0"))
    SAVE_RIGHT_CLICK_Y = int(os.getenv(f"{PREFIX}_SAVE_RIGHT_CLICK_Y", "0"))
    FILENAME_FIELD_X = int(os.getenv(f"{PREFIX}_FILENAME_FIELD_X", "0"))
    FILENAME_FIELD_Y = int(os.getenv(f"{PREFIX}_FILENAME_FIELD_Y", "0"))
else:
    FIRST_CLICK_X = int(os.getenv(f"{PREFIX}_FIRST_CLICK_X", "0"))
    FIRST_CLICK_Y = int(os.getenv(f"{PREFIX}_FIRST_CLICK_Y", "0"))
    RIGHT_CLICK_X = int(os.getenv(f"{PREFIX}_RIGHT_CLICK_X", "0"))
    RIGHT_CLICK_Y = int(os.getenv(f"{PREFIX}_RIGHT_CLICK_Y", "0"))
    COPY_IMAGE_CLICK_X = int(os.getenv(f"{PREFIX}_COPY_IMAGE_CLICK_X", "0"))
    COPY_IMAGE_CLICK_Y = int(os.getenv(f"{PREFIX}_COPY_IMAGE_CLICK_Y", "0"))

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip().replace(" ", "_")[:200]

def parse_price(price_str: str) -> float:
    if not price_str:
        return 0.0
    cleaned = price_str.replace("R$", "").strip()
    if " - " in cleaned:
        cleaned = cleaned.split(" - ")[0]
    cleaned = re.sub(r'[^\d,.]', '', cleaned).replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def load_json():
    if JSON_PATH.exists():
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_json(data):
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_new_id(existing_products):
    max_num = 0
    for prod in existing_products:
        if prod.get('id', '').startswith('shopee_'):
            try:
                num = int(prod['id'].split('_')[1])
                max_num = max(max_num, num)
            except:
                continue
    return f"shopee_{max_num + 1:03d}"

def read_links_from_txt():
    links = []
    if not LINKS_FILE.exists():
        logger.error(f"Arquivo de links não encontrado: {LINKS_FILE}")
        return links
    with open(LINKS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and line.startswith('http'):
                links.append(line)
    return links

def extract_product_info_from_text(text: str):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    product_data = {'nome': '', 'preco': 0.0, 'preco_original': 0.0, 'categoria': ''}
    
    start_idx = 0
    for i, line in enumerate(lines):
        if 'Carrinho Faça login' in line or 'carrinho' in line.lower():
            start_idx = i + 1
            break
    
    breadcrumb_line = None
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if line == 'Shopee' and i+1 < len(lines) and '>' in lines[i+1]:
            breadcrumb_line = lines[i+1]
            break
        if line.startswith('Shopee') and '>' in line:
            breadcrumb_line = line
            break
        if '>' in line and any(cat in line for cat in ('Computadores', 'Áudio', 'Eletrônicos')):
            breadcrumb_line = line
            break
    
    if breadcrumb_line:
        parts = [p.strip() for p in breadcrumb_line.split('>')]
        categoria = parts[-1].replace('icon arrow right', '').strip()
        product_data['categoria'] = categoria
    
    search_start = start_idx
    if breadcrumb_line and breadcrumb_line in lines:
        search_start = lines.index(breadcrumb_line) + 1
    
    for i in range(search_start, min(search_start+15, len(lines))):
        line = lines[i]
        if len(line) < 30:
            continue
        if any(palavra in line.lower() for palavra in ('icon', 'imagem', 'favoritar', 'compartilhar', 'avaliações', 'variação', 'denunciar')):
            continue
        if re.match(r'^\d{4}-\d{2}-\d{2}', line):
            continue
        product_data['nome'] = line
        break
    
    if not product_data['nome'] and breadcrumb_line:
        longest = ''
        for i in range(search_start, min(search_start+20, len(lines))):
            if len(lines[i]) > len(longest) and len(lines[i]) > 30:
                longest = lines[i]
        product_data['nome'] = longest
    
    price_ranges = re.findall(r'R\$\s*([\d\.,]+)\s*-\s*R\$\s*([\d\.,]+)', text)
    if price_ranges:
        product_data['preco'] = parse_price(price_ranges[0][0])
        if len(price_ranges) > 1:
            product_data['preco_original'] = parse_price(price_ranges[1][1])
        else:
            product_data['preco_original'] = product_data['preco']
    else:
        price_match = re.search(r'R\$\s*([\d\.,]+)', text)
        if price_match:
            product_data['preco'] = parse_price(price_match.group(0))
            product_data['preco_original'] = product_data['preco']
        else:
            product_data['preco'] = 0.0
            product_data['preco_original'] = 0.0
    
    return product_data

def type_link_and_enter(link):
    pyautogui.click(ADDRESS_BAR_X, ADDRESS_BAR_Y)
    time.sleep(1)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.5)
    pyautogui.press('delete')
    time.sleep(0.5)
    pyautogui.write(link)
    time.sleep(1)
    pyautogui.press('enter')

def copy_page_content():
    pyautogui.click(CLICK_COPY_X, CLICK_COPY_Y)
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(1)
    return pyperclip.paste()

def save_image_via_context_menu(filename):
    pyautogui.click(SAVE_RIGHT_CLICK_X, SAVE_RIGHT_CLICK_Y, button='right')
    time.sleep(1.2)
    pyautogui.press('s')
    time.sleep(2)
    pyautogui.click(FILENAME_FIELD_X, FILENAME_FIELD_Y)
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.write(filename)
    time.sleep(0.8)
    pyautogui.press('enter')
    time.sleep(2)

def get_latest_downloaded_file():
    download_dir = Path.home() / "Downloads"
    files = list(download_dir.glob("*"))
    return max(files, key=os.path.getctime) if files else None

def copy_image_via_coordinates():
    pyautogui.click(FIRST_CLICK_X, FIRST_CLICK_Y)
    time.sleep(0.8)
    pyautogui.rightClick(RIGHT_CLICK_X, RIGHT_CLICK_Y)
    time.sleep(0.8)
    pyautogui.click(COPY_IMAGE_CLICK_X, COPY_IMAGE_CLICK_Y)
    time.sleep(1.5)
    img = ImageGrab.grabclipboard()
    if img is None:
        logger.warning("Nenhuma imagem copiada. Verifique as coordenadas.")
    return img

def capture_image(safe_name):
    if METHOD == "save":
        save_image_via_context_menu(safe_name)
        time.sleep(2)
        downloaded = get_latest_downloaded_file()
        if downloaded and downloaded.suffix.lower() in ('.webp', '.jpg', '.jpeg', '.png'):
            final_path = IMAGES_DIR / safe_name
            if downloaded.suffix.lower() != '.png':
                with Image.open(downloaded) as img:
                    img.save(final_path, 'PNG')
                downloaded.unlink()
            else:
                shutil.move(str(downloaded), str(final_path))
            return final_path.name
        else:
            return ""
    else:
        imagem = copy_image_via_coordinates()
        if imagem:
            final_path = IMAGES_DIR / safe_name
            imagem.save(final_path, 'PNG')
            return safe_name
        else:
            return ""

def process_product(link, existing_products):
    type_link_and_enter(link)
    time.sleep(random.uniform(12, 18))

    page_text = copy_page_content()
    if not page_text:
        logger.error("Falha ao copiar conteúdo.")
        return None, False

    data = extract_product_info_from_text(page_text)
    nome = data.get('nome')
    preco = data.get('preco', 0.0)
    categoria_extraida = data.get('categoria', '')

    if not nome or len(nome) < 5:
        lines = page_text.split('\n')
        for line in lines:
            line = line.strip()
            if 10 < len(line) < 200 and not line.startswith(('Ir para', 'Central do', 'Vender', 'Baixe')):
                nome = line
                break
    if not nome or len(nome) < 5:
        logger.error(f"Nome inválido: '{nome}'")
        return None, False

    safe_name = sanitize_filename(nome) + '.png'
    imagem_filename = capture_image(safe_name)

    categorias_existentes = [p.get('categoria', '') for p in existing_products if p.get('categoria')]
    contexto = f"Produto: {nome}\nCategoria sugerida pelo site: {categoria_extraida}"
    categoria = obter_categoria_llm(nome, contexto, categorias_existentes) or (categoria_extraida or "Geral")

    existing = next((p for p in existing_products if p.get('link') == link), None)
    if existing:
        if existing.get('nome') != nome and existing.get('imagem'):
            old = IMAGES_DIR / existing['imagem']
            if old.exists():
                old.unlink()
        existing.update({
            'nome': nome,
            'preco': preco,
            'preco_original': preco,
            'descricao': nome,
            'imagem': imagem_filename,
            'link': link,
            'categoria': categoria
        })
        logger.info(f"Atualizado: {nome} | Preço: R${preco:.2f}")
        return existing, True
    else:
        new_id = generate_new_id(existing_products)
        new_prod = {
            "id": new_id,
            "nome": nome,
            "preco": preco,
            'preco_original': preco,
            'descricao': nome,
            'imagem': imagem_filename,
            'link': link,
            'categoria': categoria
        }
        logger.info(f"Novo produto: {nome} (ID {new_id}) | Preço: R${preco:.2f}")
        return new_prod, False

def run_bot(links):
    produtos = load_json()
    for idx, link in enumerate(links, 1):
        logger.info(f"=== Produto {idx}/{len(links)} ===")
        produto, is_update = process_product(link, produtos)
        if produto is None:
            logger.warning(f"Link ignorado: {link}")
            continue
        if not is_update:
            produtos.append(produto)
        save_json(produtos)
        time.sleep(random.uniform(30, 60))

if __name__ == "__main__":
    lista_links = read_links_from_txt()
    if not lista_links:
        logger.error("Nenhum link encontrado.")
    else:
        logger.info(f"Total de links: {len(lista_links)}")
        logger.info(f"Máquina selecionada: {MACHINE.upper()} - Método: {METHOD}")
        input("Pressione ENTER para iniciar (navegador deve estar em primeiro plano)...")
        run_bot(lista_links)