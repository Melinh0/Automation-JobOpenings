import os
import re
import json
import time
import random
import requests
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Importa a função de categorização por IA
from llm_category import obter_categoria_llm

# Carrega variáveis do arquivo .env
load_dotenv()

def expand_path(path_str: str) -> Path:
    """Expande variáveis de ambiente (ex: %VAR%) e retorna um Path."""
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

# ================= CONFIGURAÇÕES (lidas do .env) =================
JSON_PATH = expand_path(os.getenv("JSON_SHOPEE", ""))
IMAGES_DIR = expand_path(os.getenv("IMAGES_SHOPEE", ""))
LINKS_FILE = expand_path(os.getenv("TXT_SHOPEE", ""))
BOT_PROFILE_DIR = expand_path(os.getenv("PROFILE_SHOPEE", ""))

# Cria os diretórios se não existirem
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
BOT_PROFILE_DIR.mkdir(exist_ok=True)

# Validação básica
if not LINKS_FILE.exists():
    raise FileNotFoundError(f"Arquivo de links não encontrado: {LINKS_FILE}")
if not JSON_PATH.parent.exists():
    raise FileNotFoundError(f"Diretório do JSON não encontrado: {JSON_PATH.parent}")

# ================= FUNÇÕES AUXILIARES =================
def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip().replace(" ", "_")
    return name[:200]

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
        if not ext or ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
            ext = '.jpg'
        filename = sanitize_filename(product_name) + ext
        filepath = IMAGES_DIR / filename
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, stream=True, timeout=15)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return filename
    except Exception as e:
        print(f"Erro ao baixar imagem: {e}")
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
                if num > max_num:
                    max_num = num
            except:
                continue
    return f"shopee_{max_num + 1:03d}"

def read_links_from_txt():
    links = []
    if not LINKS_FILE.exists():
        print(f"Arquivo de links não encontrado: {LINKS_FILE}")
        return links
    with open(LINKS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and line.startswith('http'):
                links.append(line)
    return links

# ================= FUNÇÕES DE SCRAPING =================
def accept_cookies(driver):
    wait = WebDriverWait(driver, 10)
    selectors = [
        "button.Q4KP5g",
        "//button[contains(text(), 'Aceitar todos')]",
        "//button[contains(text(), 'Aceitar')]"
    ]
    for selector in selectors:
        try:
            if selector.startswith("//"):
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
            else:
                btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            btn.click()
            print("Cookies aceitos.")
            return True
        except:
            continue
    return False

def extract_product_name(driver):
    try:
        return WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        ).text.strip()
    except Exception as e:
        print(f"Erro ao extrair nome: {e}")
        return ""

def extract_prices(driver):
    promo = 0.0
    original = None

    try:
        promo_elem = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.jRlVo0 div.IZPeQz"))
        )
        promo_str = promo_elem.text.strip()
        if promo_str:
            promo = parse_price(promo_str)
    except Exception as e:
        print(f"Erro ao capturar preço promocional: {e}")

    if promo == 0.0:
        try:
            fallback_promo = driver.find_element(By.CSS_SELECTOR, "div.jRlVo0 .IZPeQz, div.jRlVo0 ._2eqbU")
            promo = parse_price(fallback_promo.text.strip())
        except:
            pass

    try:
        orig_elem = driver.find_element(By.CSS_SELECTOR, "div.jRlVo0 div.ZA5sW5")
        orig_str = orig_elem.text.strip()
        if orig_str:
            original = parse_price(orig_str)
    except:
        pass

    if promo == 0.0:
        try:
            any_price = driver.find_element(By.CSS_SELECTOR, "div.jRlVo0 div")
            promo = parse_price(any_price.text.strip())
        except:
            pass

    return promo, original

def extract_image_url(driver):
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".UdI7e2 img, .UBG7wZ img"))
        )
        img = driver.find_element(By.CSS_SELECTOR, ".UdI7e2 img")
        url = img.get_attribute('src') or img.get_attribute('data-src')
        if url and url.startswith('http'):
            url = re.sub(r'@resize_w\d+_nl', '', url)
            return url
    except:
        pass
    try:
        thumbnails = driver.find_elements(By.CSS_SELECTOR, ".UBG7wZ .YM40Nc img")
        for thumb in thumbnails:
            url = thumb.get_attribute('src') or thumb.get_attribute('data-src')
            if url and url.startswith('http') and 'video' not in url.lower():
                url = re.sub(r'@resize_w\d+_nl', '', url)
                return url
    except:
        pass
    try:
        any_img = driver.find_element(By.CSS_SELECTOR, "img[src*='.sg']")
        return any_img.get_attribute('src')
    except Exception as e:
        print(f"Erro ao extrair URL da imagem: {e}")
        return ""

def extrair_categoria_shopee(driver) -> str:
    """Extrai a categoria do breadcrumb da Shopee (usando Selenium)."""
    try:
        breadcrumbs = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".idLK2l"))
        )
        links = breadcrumbs.find_elements(By.CSS_SELECTOR, "a.EtYbJs")
        if len(links) == 0:
            return ""
        categoria = links[-1].text.strip()
        if "Animais" in categoria or "Pet" in categoria:
            return "Pets"
        if "Celular" in categoria or "Smartphone" in categoria:
            return "Acessórios de Celular"
        return categoria
    except:
        return ""

def human_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def process_product(driver, link, existing_products):
    print(f"\nProcessando: {link}")
    driver.get(link)
    human_delay(2, 4)
    accept_cookies(driver)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        )
    except Exception as e:
        print(f"Timeout esperando título: {e}")
        print(f"URL atual: {driver.current_url}")
        if "login" in driver.current_url.lower():
            print("Página de login detectada. Faça login manualmente.")
            input("Após login, pressione ENTER...")
            driver.get(link)
            human_delay(3, 5)
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
                )
            except:
                print("Falha mesmo após login. Abortando.")
                return None, False
        else:
            return None, False

    nome = extract_product_name(driver)
    if not nome:
        return None, False

    preco_promo, preco_original = extract_prices(driver)

    if preco_promo == 0.0:
        print(f"Preço promocional não encontrado para {link}. Abortando.")
        return None, False

    if preco_original is None or preco_original == 0.0:
        preco_original = preco_promo

    img_url = extract_image_url(driver)
    imagem_filename = download_image(img_url, nome) if img_url else ""
    categoria_original = extrair_categoria_shopee(driver)
    descricao = nome  
    categorias_existentes = [prod.get('categoria', '') for prod in existing_products if prod.get('categoria')]
    categoria_sugerida = obter_categoria_llm(nome, descricao, categorias_existentes)
    if categoria_sugerida:
        print(f"🤖 IA sugeriu categoria: '{categoria_sugerida}' (original: '{categoria_original}')")
        categoria = categoria_sugerida
    else:
        categoria = categoria_original if categoria_original else "Geral"
        if not categoria_sugerida:
            print(f"ℹ️ Usando categoria original: '{categoria}'")

    existing = next((p for p in existing_products if p.get('link') == link), None)
    if existing:
        if existing.get('nome') != nome:
            old_img = IMAGES_DIR / existing.get('imagem', '')
            if old_img.exists():
                old_img.unlink()
        existing.update({
            'nome': nome,
            'preco': preco_promo,
            'preco_original': preco_original,
            'descricao': nome,
            'imagem': imagem_filename,
            'link': link,
            'categoria': categoria
        })
        print(f"Atualizado: {nome} (R${preco_promo:.2f}) | Categoria: {categoria}")
        return existing, True
    else:
        new_id = generate_new_id(existing_products)
        new_prod = {
            "id": new_id,
            "nome": nome,
            "preco": preco_promo,
            "preco_original": preco_original,
            "descricao": nome,
            "imagem": imagem_filename,
            "link": link,
            "categoria": categoria
        }
        print(f"Novo produto: {nome} (ID {new_id}) - Preço: R${preco_promo:.2f} | Categoria: {categoria}")
        return new_prod, False

def run_bot(links):
    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={str(BOT_PROFILE_DIR)}")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        produtos = load_json()
        for link in links:
            try:
                produto, is_update = process_product(driver, link, produtos)
                if produto is None:
                    print(f"Link ignorado: {link}")
                    continue
                if not is_update:
                    produtos.append(produto)
                save_json(produtos)
                human_delay(4, 8)
            except Exception as e:
                print(f"Erro crítico em {link}: {e}")
                continue
    finally:
        driver.quit()
        print("[LOG] Driver encerrado.")

if __name__ == "__main__":
    lista_links = read_links_from_txt()
    if not lista_links:
        print("Nenhum link encontrado.")
    else:
        print(f"Total de links: {len(lista_links)}")
        print(f"\nO bot usará um perfil dedicado do Chrome: {BOT_PROFILE_DIR}")
        print("Na primeira execução, pode pedir login na Shopee. Faça login uma vez e o perfil salvará a sessão.")
        print("As imagens serão salvas em alta resolução.\n")
        input("Pressione ENTER para iniciar...")
        run_bot(lista_links)