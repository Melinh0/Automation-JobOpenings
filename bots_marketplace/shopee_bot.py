import os
import re
import json
import time
import random
import requests
import logging
import shutil
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

# Usa undetected_chromedriver (muito mais furtivo)
import undetected_chromedriver as uc

# Importa a função de categorização por IA
from llm_category import obter_categoria_llm

# Configura logging
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

# Diretório de perfil persistente (onde o login será salvo)
CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "/home/yago/.config/chrome_shopee_bot")
# Garante que o diretório exista
Path(CHROME_USER_DATA_DIR).mkdir(parents=True, exist_ok=True)

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

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
                if num > max_num:
                    max_num = num
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

def human_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def random_mouse_jitter(driver, element=None):
    try:
        actions = ActionChains(driver)
        if element and element.is_displayed():
            actions.move_to_element(element).pause(0.1)
            x_offset = random.randint(-5, 5)
            y_offset = random.randint(-5, 5)
            actions.move_by_offset(x_offset, y_offset).pause(0.1)
            actions.move_to_element(element)
            actions.perform()
        else:
            width = driver.execute_script("return window.innerWidth;")
            height = driver.execute_script("return window.innerHeight;")
            x = random.randint(50, width - 50)
            y = random.randint(50, height - 50)
            actions.move_by_offset(x, y).pause(0.1).perform()
            actions.move_by_offset(-x, -y).perform()
        human_delay(0.1, 0.3)
    except Exception:
        pass

def human_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
        human_delay(0.3, 0.7)
        if not element.is_displayed() or not element.is_enabled():
            return False
        actions = ActionChains(driver)
        actions.move_to_element(element).pause(random.uniform(0.1, 0.3))
        actions.click().perform()
        human_delay(0.2, 0.5)
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False

def accept_cookies_human(driver):
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
            random_mouse_jitter(driver, btn)
            if human_click(driver, btn):
                logger.info("Cookies aceitos.")
                return True
        except:
            continue
    return False

def is_login_page(driver):
    current_url = driver.current_url
    if "login" in current_url.lower() or "account" in current_url.lower():
        return True
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "não está logado" in body or "página indisponível" in body or "faça login" in body:
            return True
    except:
        pass
    return False

# ================= NAVEGAÇÃO HUMANIZADA =================
def navigate_to_shopee_human(driver):
    """Acessa o Google, pesquisa Shopee, clica no resultado e mantém sessão."""
    logger.info("Acessando o Google para pesquisar Shopee...")
    driver.get("https://www.google.com")
    human_delay(5, 8)
    
    # Aceita cookies do Google (se aparecer)
    try:
        accept_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Aceitar')]"))
        )
        human_click(driver, accept_btn)
    except:
        pass
    
    # Pesquisa "shopee"
    search_box = driver.find_element(By.NAME, "q")
    for char in "shopee":
        search_box.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    human_delay(0.5, 1)
    search_box.send_keys(Keys.RETURN)
    human_delay(8, 12)
    
    # Role a página de resultados
    for _ in range(random.randint(2, 4)):
        driver.execute_script(f"window.scrollBy(0, {random.randint(300, 600)});")
        human_delay(1, 2)
    
    # Encontra e clica no link principal da Shopee
    try:
        shopee_link = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'shopee.com.br')]"))
        )
        human_click(driver, shopee_link)
        logger.info("Clique no resultado da Shopee")
    except Exception as e:
        logger.warning(f"Não encontrou link da Shopee no Google, acessando diretamente: {e}")
        driver.get("https://shopee.com.br/")
    
    human_delay(10, 15)
    
    # Role a página inicial
    for _ in range(random.randint(2, 5)):
        driver.execute_script(f"window.scrollBy(0, {random.randint(300, 700)});")
        human_delay(1.5, 3)
        random_mouse_jitter(driver)
    
    accept_cookies_human(driver)

# ================= FUNÇÕES DE EXTRAÇÃO =================
def extract_product_name_human(driver):
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        )
        driver.execute_script("window.scrollBy(0, 100);")
        human_delay(0.5, 1.0)
        elem = driver.find_element(By.CSS_SELECTOR, "h1.vR6K3w")
        random_mouse_jitter(driver, elem)
        return elem.text.strip()
    except Exception as e:
        logger.error(f"Erro ao extrair nome: {e}")
        return ""

def extract_prices_human(driver):
    promo = 0.0
    original = None
    human_delay(2, 4)
    for attempt in range(3):
        try:
            promo_elem = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.jRlVo0 div.IZPeQz"))
            )
            if promo_elem and promo_elem.is_displayed():
                promo_str = promo_elem.text.strip()
                if promo_str:
                    promo = parse_price(promo_str)
                    if promo > 0:
                        break
        except:
            pass
        human_delay(1, 2)
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

def extract_image_url_human(driver):
    driver.execute_script("window.scrollBy(0, 200);")
    human_delay(2, 3)
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".UdI7e2 img, .UBG7wZ img"))
        )
        img = driver.find_element(By.CSS_SELECTOR, ".UdI7e2 img")
        random_mouse_jitter(driver, img)
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
        logger.error(f"Erro ao extrair URL da imagem: {e}")
        return ""

def extrair_categoria_shopee_human(driver):
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

def process_product_human(driver, link, existing_products):
    logger.info(f"Processando: {link}")
    driver.get(link)
    human_delay(12, 18)  # espera longa para carregar

    # Verifica se foi redirecionado para login
    if is_login_page(driver):
        logger.error("Página de login detectada. Por favor, faça login manualmente na janela do Chrome e pressione ENTER.")
        input("Após fazer login, pressione ENTER para continuar...")
        # Recarrega o link
        driver.get(link)
        human_delay(12, 18)
        if is_login_page(driver):
            logger.error("Ainda em página de login. Abortando este link.")
            return None, False

    accept_cookies_human(driver)

    try:
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        )
    except Exception as e:
        logger.error(f"Timeout esperando título: {e}")
        return None, False

    # Rolagem suave – mais tempo
    for _ in range(random.randint(3, 6)):
        driver.execute_script(f"window.scrollBy(0, {random.randint(200, 500)});")
        human_delay(1.5, 2.5)
        random_mouse_jitter(driver)

    nome = extract_product_name_human(driver)
    if not nome:
        logger.warning("Nome não encontrado.")
        return None, False

    preco_promo, preco_original = extract_prices_human(driver)
    if preco_promo == 0.0:
        logger.warning("Preço não encontrado.")
        return None, False

    img_url = extract_image_url_human(driver)
    imagem_filename = download_image(img_url, nome) if img_url else ""
    categoria_original = extrair_categoria_shopee_human(driver)

    categorias_existentes = [p.get('categoria', '') for p in existing_products if p.get('categoria')]
    categoria_sugerida = obter_categoria_llm(nome, nome, categorias_existentes)
    categoria = categoria_sugerida if categoria_sugerida else (categoria_original or "Geral")
    logger.info(f"Produto: {nome} | Preço: R${preco_promo:.2f} | Categoria: {categoria}")

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
        logger.info(f"Atualizado: {nome}")
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
        logger.info(f"Novo produto: {nome} (ID {new_id})")
        return new_prod, False

# ================= DRIVER STEALTH COM PERFIL PERSISTENTE =================
def create_stealth_driver():
    """Cria driver undetected com perfil persistente (mantém login)."""
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Usa um perfil separado e persistente
    options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
    # Não define profile-directory, para usar o padrão do data-dir
    driver = uc.Chrome(options=options, version_main=147)
    # Remove a propriedade 'webdriver' (redundante, mas seguro)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def run_bot(links):
    driver = create_stealth_driver()
    driver.set_window_size(random.randint(1200, 1600), random.randint(800, 1000))
    try:
        # Navegação humanizada até a Shopee via Google
        navigate_to_shopee_human(driver)
        
        produtos = load_json()
        for idx, link in enumerate(links, 1):
            logger.info(f"=== Produto {idx}/{len(links)} ===")
            produto, is_update = process_product_human(driver, link, produtos)
            if produto is None:
                logger.warning(f"Link ignorado: {link}")
                continue
            if not is_update:
                produtos.append(produto)
            save_json(produtos)
            human_delay(30, 60)  # pausa longa entre produtos
    except Exception as e:
        logger.error(f"Erro fatal no bot: {e}", exc_info=True)
    finally:
        logger.info("Bot finalizado. Fechando navegador em 5 segundos...")
        time.sleep(5)
        driver.quit()

if __name__ == "__main__":
    lista_links = read_links_from_txt()
    if not lista_links:
        logger.error("Nenhum link encontrado.")
    else:
        logger.info(f"Total de links: {len(lista_links)}")
        logger.info("Usando undetected-chromedriver com perfil persistente.")
        input("Certifique-se de que o Chrome não está aberto. Pressione ENTER para iniciar...")
        run_bot(lista_links)