import os
import re
import json
import time
import random
import requests
import logging
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import undetected_chromedriver as uc

from llm_category import obter_categoria_llm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# ================= CONFIGURAÇÕES =================
def expand_path(path_str: str) -> Path:
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

JSON_PATH = expand_path(os.getenv("JSON_SHOPEE", ""))
IMAGES_DIR = expand_path(os.getenv("IMAGES_SHOPEE", ""))
LINKS_FILE = expand_path(os.getenv("TXT_SHOPEE", ""))

CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", str(Path.home() / ".config" / "chrome_shopee_bot"))
Path(CHROME_USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

if not LINKS_FILE.exists():
    raise FileNotFoundError(f"Arquivo de links não encontrado: {LINKS_FILE}")

# ================= FUNÇÕES AUXILIARES =================
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

def download_image(url: str, product_name: str) -> str:
    try:
        parsed_url = urlparse(url)
        ext = os.path.splitext(parsed_url.path)[1]
        if not ext or ext.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            ext = '.jpg'
        filename = sanitize_filename(product_name) + ext
        filepath = IMAGES_DIR / filename
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://shopee.com.br/'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=15)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return filename
    except Exception as e:
        logger.error(f"Erro ao baixar imagem: {e}")
        return ""

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

# ================= DRIVER STEALTH (CHROME) - CORRIGIDO =================
def create_stealth_driver():
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    # Removidas as opções experimentais problemáticas
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

    # Não especifique version_main, deixe o undetected-chromedriver detectar automaticamente
    driver = uc.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

# ================= EXTRAÇÃO AVANÇADA DE DADOS =================
def extract_from_store(html_content):
    """Extrai dados do produto do window.__STORE__ (mais confiável)"""
    match = re.search(r'window\.__STORE__\s*=\s*JSON\.parse\((".*?")\);', html_content, re.DOTALL)
    if not match:
        return {}
    try:
        json_str = json.loads(match.group(1))
        state = json.loads(json_str)
        pdp = state.get('DOMAIN_PDP', {}) or state.get('pdp', {})
        data = pdp.get('data', {})
        bff_data = data.get('PDP_BFF_DATA', {})
        cached = bff_data.get('cachedMap', {})
        for key, value in cached.items():
            item = value.get('item', {})
            if item.get('item_id'):
                price = item.get('price_min') or item.get('price') or 0
                if isinstance(price, (int, float)):
                    price = price / 100000.0
                return {
                    'nome': item.get('title', ''),
                    'preco': price,
                    'imagem_url': f"https://cf.shopee.com.br/file/{item.get('image', '')}" if item.get('image') else '',
                    'shop_location': item.get('shop_location', '')
                }
    except Exception as e:
        logger.debug(f"Erro ao parsear __STORE__: {e}")
    return {}

def extract_product_info_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    product_data = {}

    # 1. __STORE__
    store_data = extract_from_store(html_content)
    if store_data:
        product_data.update(store_data)

    # 2. JSON-LD
    if not product_data.get('nome'):
        script_ld = soup.find('script', type='application/ld+json')
        if script_ld and script_ld.string:
            try:
                data = json.loads(script_ld.string)
                if isinstance(data, dict):
                    product_data['nome'] = product_data.get('nome') or data.get('name')
                    if not product_data.get('preco'):
                        price = data.get('offers', {}).get('price', '')
                        if price:
                            product_data['preco'] = parse_price(str(price))
                    if not product_data.get('imagem_url') and 'image' in data:
                        product_data['imagem_url'] = data['image']
            except:
                pass

    # 3. Título da página
    if not product_data.get('nome'):
        title = soup.find('title')
        if title:
            raw_title = title.text.strip()
            product_data['nome'] = raw_title.split('|')[0].strip()

    # 4. Seletor específico da Shopee
    if not product_data.get('nome'):
        h1 = soup.find('h1', class_=re.compile(r'WBVL_7|vR6K3w|product-title'))
        if h1:
            product_data['nome'] = h1.text.strip()

    # 5. Preço via seletores do DOM
    if not product_data.get('preco') or product_data['preco'] == 0.0:
        for class_pattern in [r'IZPeQz', r'_67d6e6', r'price___', r'product-price']:
            price_elem = soup.find('div', class_=re.compile(class_pattern))
            if price_elem:
                product_data['preco'] = parse_price(price_elem.text)
                break
        if not product_data.get('preco'):
            meta_price = soup.find('meta', {'property': 'product:price:amount'})
            if meta_price and meta_price.get('content'):
                product_data['preco'] = parse_price(meta_price['content'])

    # 6. Imagem
    if not product_data.get('imagem_url'):
        img = soup.find('img', class_=re.compile(r'rWN4DK|UdI7e2|product-image'))
        if img and img.get('src'):
            product_data['imagem_url'] = img['src']
        else:
            img = soup.find('img', src=re.compile(r'\.sg|\.jpg|\.png'))
            if img and img.get('src'):
                product_data['imagem_url'] = img['src']

    return product_data

# ================= PROCESSAMENTO DE UM PRODUTO (NOVA ABA, SEM POLLING) =================
def process_product_in_new_tab(driver, link, existing_products):
    """Abre link em nova aba, aguarda carregamento completo, extrai e fecha a aba."""
    original_tab = driver.current_window_handle

    # Abre nova aba
    driver.execute_script("window.open('');")
    new_tab = driver.window_handles[-1]
    driver.switch_to.window(new_tab)

    logger.info(f"Acessando: {link}")
    driver.get(link)

    # Aguarda até 20 segundos pelo elemento do título do produto
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.WBVL_7, .WBVL_7, .IZPeQz"))
        )
        logger.debug("Página do produto carregada.")
    except TimeoutException:
        logger.warning("Timeout esperando página. Tentando extrair parcialmente.")

    # Pausa extra para garantir renderização de JS (simula humano)
    time.sleep(2)

    html = driver.page_source

    # Fecha a aba e volta para a original
    driver.close()
    driver.switch_to.window(original_tab)

    if not html or len(html) < 2000:
        logger.error(f"HTML insuficiente (tamanho: {len(html)})")
        debug_path = Path("debug_html") / f"{int(time.time())}_failed.html"
        debug_path.parent.mkdir(exist_ok=True)
        debug_path.write_text(html if html else "EMPTY", encoding='utf-8')
        return None, False

    data = extract_product_info_from_html(html)
    nome = data.get('nome')
    preco = data.get('preco', 0.0)
    img_url = data.get('imagem_url', '')

    # Validação do nome
    if not nome or nome.strip().lower() in ["shopee", "shopping", "produto", "product", "shopee brasil"] or len(nome) < 5:
        logger.error(f"Nome inválido: '{nome}'")
        debug_path = Path("debug_html") / f"{int(time.time())}_generic_name.html"
        debug_path.parent.mkdir(exist_ok=True)
        debug_path.write_text(html, encoding='utf-8')
        return None, False

    # Tratamento de preço
    if preco == 0.0:
        logger.warning(f"Preço não encontrado para {nome}. Tentando regex...")
        price_match = re.search(r'R\$\s*([\d\.,]+)', html)
        if price_match:
            preco = parse_price(price_match.group(0))
        else:
            cents_match = re.search(r'"price"\s*:\s*(\d+)', html)
            if cents_match:
                preco = int(cents_match.group(1)) / 100.0

    imagem_filename = download_image(img_url, nome) if img_url else ""

    # Categoria via IA
    categorias_existentes = [p.get('categoria', '') for p in existing_products if p.get('categoria')]
    categoria_sugerida = obter_categoria_llm(nome, nome, categorias_existentes)
    categoria = categoria_sugerida if categoria_sugerida else "Geral"

    existing = next((p for p in existing_products if p.get('link') == link), None)
    if existing:
        if existing.get('nome') != nome and existing.get('imagem'):
            old_img = IMAGES_DIR / existing['imagem']
            if old_img.exists():
                old_img.unlink()
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
            "preco_original": preco,
            "descricao": nome,
            "imagem": imagem_filename,
            "link": link,
            "categoria": categoria
        }
        logger.info(f"Novo produto: {nome} (ID {new_id}) | Preço: R${preco:.2f}")
        return new_prod, False

# ================= MAIN =================
def run_bot(links):
    driver = create_stealth_driver()
    try:
        time.sleep(3)
        produtos = load_json()
        for idx, link in enumerate(links, 1):
            logger.info(f"=== Produto {idx}/{len(links)} ===")
            produto, is_update = process_product_in_new_tab(driver, link, produtos)
            if produto is None:
                logger.warning(f"Link ignorado: {link}")
                continue
            if not is_update:
                produtos.append(produto)
            save_json(produtos)
            # Pausa entre produtos (5-15 segundos) para evitar detecção
            time.sleep(random.uniform(5, 15))
    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
    finally:
        logger.info("Fechando navegador em 3 segundos...")
        time.sleep(3)
        driver.quit()

if __name__ == "__main__":
    lista_links = read_links_from_txt()
    if not lista_links:
        logger.error("Nenhum link encontrado.")
    else:
        logger.info(f"Total de links: {len(lista_links)}")
        logger.info("Navegação: nova aba, wait 20s, sem interrupção brusca.")
        input("Pressione ENTER para iniciar...")
        run_bot(lista_links)