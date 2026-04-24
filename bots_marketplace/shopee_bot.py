import os
import re
import json
import time
import random
import requests
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains

# Importa a função de categorização por IA
from llm_category import obter_categoria_llm

load_dotenv()

CHROME_DEBUG_PORT = 9223  

# ================= CONFIGURAÇÕES =================
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

def human_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def human_scroll(driver, pixels=300):
    """Rola a página de forma aleatória como um humano faria."""
    scroll_by = random.randint(100, pixels)
    driver.execute_script(f"window.scrollBy(0, {scroll_by});")
    human_delay(0.01, 0.05)  # pequena pausa entre scrolls

def human_click(driver, element):
    """Clica em um elemento de forma mais natural: move o mouse e clica."""
    actions = ActionChains(driver)
    actions.move_to_element(element).pause(random.uniform(0.1, 0.3)).click().perform()
    human_delay(0.2, 0.5)

# ================= INICIAR CHROME COM DEPURAÇÃO =================
def start_chrome_debug():
    """Verifica se já há instância na porta configurada; se não, inicia o Chrome manualmente."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', CHROME_DEBUG_PORT))
    sock.close()
    if result == 0:
        print(f"✅ Conexão com Chrome debug já ativa na porta {CHROME_DEBUG_PORT}. Reutilizando...")
        return True
    else:
        print(f"🚀 Iniciando Chrome com depuração remota na porta {CHROME_DEBUG_PORT}...")
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        user_data_dir = r"C:\chrome_debug"
        cmd = [
            chrome_path,
            f"--remote-debugging-port={CHROME_DEBUG_PORT}",
            f"--user-data-dir={user_data_dir}",
            f"--remote-allow-origins=http://127.0.0.1:{CHROME_DEBUG_PORT}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(1)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sock.connect_ex(('127.0.0.1', CHROME_DEBUG_PORT)) == 0:
                sock.close()
                print(f"✅ Chrome debug iniciado com sucesso na porta {CHROME_DEBUG_PORT}.")
                return True
            sock.close()
        print(f"❌ Falha ao iniciar Chrome debug na porta {CHROME_DEBUG_PORT}. Verifique o caminho e permissões.")
        return False

# ================= FUNÇÕES DE SCRAPING HUMANIZADAS =================
def accept_cookies_human(driver):
    """Tenta aceitar cookies com ações humanas."""
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
            human_click(driver, btn)
            print("Cookies aceitos.")
            return True
        except:
            continue
    return False

def extract_product_name_human(driver):
    try:
        # Espera o título com um tempo variável
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        )
        # Rolagem leve para garantir que o elemento está visível
        driver.execute_script("window.scrollBy(0, 100);")
        human_delay(0.2, 0.5)
        elem = driver.find_element(By.CSS_SELECTOR, "h1.vR6K3w")
        return elem.text.strip()
    except Exception as e:
        print(f"Erro ao extrair nome: {e}")
        return ""

def extract_prices_human(driver):
    promo = 0.0
    original = None
    # Pequena espera adicional para preços carregarem dinamicamente
    human_delay(1, 2)
    try:
        promo_elem = WebDriverWait(driver, 15).until(
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

def extract_image_url_human(driver):
    # Rolar um pouco para ativar lazy loading
    driver.execute_script("window.scrollBy(0, 200);")
    human_delay(1, 1.5)
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
    print(f"\nProcessando: {link}")
    driver.get(link)
    # Aguarda a página carregar de forma imprevisível
    human_delay(3, 6)
    accept_cookies_human(driver)

    # Rolagem aleatória para simular leitura
    for _ in range(random.randint(1, 3)):
        human_scroll(driver, 400)
        human_delay(0.5, 1)

    # Espera pelo título
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
        )
    except Exception as e:
        print(f"Timeout esperando título: {e}")
        print(f"URL atual: {driver.current_url}")
        if "login" in driver.current_url.lower() or "captcha" in driver.current_url.lower():
            print("Página de login ou CAPTCHA detectada. Resolva manualmente na janela do Chrome e pressione ENTER...")
            input("Após resolver, pressione ENTER para continuar...")
            driver.get(link)
            human_delay(5, 8)
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.vR6K3w"))
                )
            except:
                print("Falha mesmo após intervenção manual. Abortando.")
                return None, False
        else:
            return None, False

    nome = extract_product_name_human(driver)
    if not nome:
        return None, False

    preco_promo, preco_original = extract_prices_human(driver)

    if preco_promo == 0.0:
        print(f"Preço promocional não encontrado para {link}. Abortando.")
        return None, False

    if preco_original is None or preco_original == 0.0:
        preco_original = preco_promo

    img_url = extract_image_url_human(driver)
    imagem_filename = download_image(img_url, nome) if img_url else ""
    categoria_original = extrair_categoria_shopee_human(driver)
    descricao = nome
    categorias_existentes = [prod.get('categoria', '') for prod in existing_products if prod.get('categoria')]
    categoria_sugerida = obter_categoria_llm(nome, descricao, categorias_existentes)
    if categoria_sugerida:
        print(f"🤖 IA sugeriu categoria: '{categoria_sugerida}' (original: '{categoria_original}')")
        categoria = categoria_sugerida
    else:
        categoria = categoria_original if categoria_original else "Geral"
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

def run_bot_human(links):
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")
    driver = webdriver.Chrome(options=chrome_options)

    # Opcional: abrir uma nova aba para não atrapalhar a manual
    driver.execute_script("window.open('');")
    driver.switch_to.window(driver.window_handles[-1])
    print("Nova aba aberta. Iniciando coleta...")

    try:
        produtos = load_json()
        for idx, link in enumerate(links, 1):
            print(f"\n=== Produto {idx}/{len(links)} ===")
            try:
                produto, is_update = process_product_human(driver, link, produtos)
                if produto is None:
                    print(f"Link ignorado: {link}")
                    continue
                if not is_update:
                    produtos.append(produto)
                save_json(produtos)
                # Pausa longa e aleatória entre produtos (simula navegação humana)
                human_delay(8, 15)
            except Exception as e:
                print(f"Erro crítico em {link}: {e}")
                continue
    finally:
        # Não fecha o driver, apenas encerra o script
        print("[INFO] Bot finalizado. A janela do Chrome permanecerá aberta.")
        # driver.quit()  # Não fechar para preservar a sessão

if __name__ == "__main__":
    lista_links = read_links_from_txt()
    if not lista_links:
        print("Nenhum link encontrado.")
    else:
        print(f"Total de links: {len(lista_links)}")
        print("O bot usará Chrome com depuração remota (porta 9222).")
        print("Você deve ter uma instância do Chrome com depuração ativa. Tentando iniciar automaticamente...")
        if start_chrome_debug():
            input("Pressione ENTER para iniciar a coleta...")
            run_bot_human(lista_links)
        else:
            print("Não foi possível iniciar o Chrome debug. Abra manualmente com o comando:")
            print(f' "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={CHROME_DEBUG_PORT} --user-data-dir="C:\\chrome_debug" --remote-allow-origins=http://127.0.0.1:{CHROME_DEBUG_PORT}')