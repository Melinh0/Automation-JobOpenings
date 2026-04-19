import os
import re
import time
import json
import random
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO

# Importa a função de categorização por IA
from llm_category import obter_categoria_llm

# Carrega variáveis do arquivo .env
load_dotenv()

def expand_path(path_str: str) -> Path:
    """Expande variáveis de ambiente (ex: %VAR%) e retorna um Path."""
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

# ================= CONFIGURAÇÕES (lidas do .env) =================
LINKS_TXT = expand_path(os.getenv("TXT_SHEIN", ""))
IMAGENS_DIR = expand_path(os.getenv("IMAGES_SHEIN", ""))
JSON_PATH = expand_path(os.getenv("JSON_SHEIN", ""))
CHROME_PROFILE_DIR = expand_path(os.getenv("PROFILE_SHEIN", ""))

# Cria os diretórios se não existirem
IMAGENS_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Validação básica
if not LINKS_TXT.exists():
    raise FileNotFoundError(f"Arquivo de links não encontrado: {LINKS_TXT}")
if not JSON_PATH.parent.exists():
    raise FileNotFoundError(f"Diretório do JSON não encontrado: {JSON_PATH.parent}")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def kill_chrome_processes():
    """Mata todos os processos do Chrome para liberar o perfil."""
    try:
        subprocess.run("taskkill /f /im chrome.exe", shell=True, capture_output=True)
        log("Processos do Chrome finalizados.")
        time.sleep(2)
    except Exception as e:
        log(f"Não foi possível matar processos do Chrome: {e}")

def random_delay(min_sec=1.5, max_sec=4.0):
    time.sleep(random.uniform(min_sec, max_sec))

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip().replace(" ", "_")
    return name[:200]

def extrair_id_produto(link: str) -> str:
    match = re.search(r'-p-(\d+)', link)
    if match:
        return match.group(1)
    return link.rstrip('/').split('/')[-1].replace('.html', '')

def extrair_nome(page) -> str:
    try:
        nome_elem = page.locator('.product-intro__head-name h1')
        if nome_elem.count() == 0:
            nome_elem = page.locator('h1.fsp-element')
        return nome_elem.inner_text().strip() if nome_elem.count() else ""
    except Exception as e:
        log(f"Erro ao extrair nome: {e}")
        return ""

def extrair_precos(page) -> tuple:
    preco_atual = None
    preco_original = None

    try:
        price_container = page.locator('#productMainPriceId').first
        if price_container.count():
            text = price_container.inner_text().strip()
            match = re.search(r'R\$\s*(\d+)[.,](\d{2})', text)
            if match:
                inteiro = match.group(1)
                centavos = match.group(2)
                preco_atual = float(f"{inteiro}.{centavos}")
            else:
                nums = re.findall(r'(\d+)[.,](\d{2})', text)
                if nums:
                    inteiro, centavos = nums[0]
                    preco_atual = float(f"{inteiro}.{centavos}")
    except Exception as e:
        log(f"Erro ao extrair preço atual: {e}")

    try:
        retail = page.locator('.productDiscountInfo__retail').first
        if retail.count():
            text = retail.inner_text().strip()
            match = re.search(r'R\$\s*([\d.,]+)', text)
            if match:
                num_str = match.group(1).replace('.', '').replace(',', '.')
                preco_original = float(num_str)
    except Exception as e:
        log(f"Erro ao extrair preço original: {e}")

    return preco_atual, preco_original

def extrair_descricao(page) -> str:
    try:
        meta = page.locator('meta[name="description"]').first
        if meta.count():
            content = meta.get_attribute('content')
            if content and len(content) > 20:
                return content[:500]
    except:
        pass
    try:
        desc = page.locator('.product-intro__description-content').first
        if desc.count():
            return desc.inner_text().strip()[:500]
    except:
        pass
    return ""

def extrair_categoria_shein(page) -> str:
    try:
        items = page.locator('.bread-crumb__item-link')
        if items.count() == 0:
            return ""
        categoria = items.last.inner_text().strip()
        if "Sapato" in categoria or "Tênis" in categoria:
            return "Calçados"
        return categoria
    except:
        return ""

def extrair_imagem_alta_resolucao(page, nome_produto: str) -> str:
    img_url = None
    try:
        container = page.locator('.normal-picture__content-list .crop-image-container').first
        if container.count():
            img_url = container.get_attribute('data-before-crop-src')
            if img_url:
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                if '_thumbnail_' in img_url:
                    img_url = re.sub(r'_thumbnail_\d+x\d+', '_thumbnail_900x', img_url)
                img_url = re.sub(r'_220x293', '_900x', img_url)
                log(f"DEBUG: Imagem via data-before-crop-src: {img_url}")

        if not img_url:
            img_elem = page.locator('.crop-image-container__img').first
            if img_elem.count():
                img_url = img_elem.get_attribute('src')
                if not img_url:
                    img_url = img_elem.get_attribute('data-src')
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url
                log(f"DEBUG: Imagem via src: {img_url}")

        if not img_url:
            img_elem = page.locator('.normal-picture__content-list .crop-image-container__img').first
            if img_elem.count():
                img_url = img_elem.get_attribute('src') or img_elem.get_attribute('data-src')
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url

        if img_url:
            img_url = img_url.split('?')[0]
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = requests.get(img_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content))
                filename = sanitize_filename(nome_produto) + ".png"
                filepath = IMAGENS_DIR / filename
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(filepath, 'PNG', quality=90)
                return filename
    except Exception as e:
        log(f"Erro ao extrair imagem: {e}")
    return ""

def carregar_json_existente():
    produtos_por_link = {}
    if JSON_PATH.exists():
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                dados = json.load(f)
                if isinstance(dados, list):
                    for prod in dados:
                        if 'link' in prod:
                            produtos_por_link[prod['link']] = prod
        except Exception as e:
            log(f"Erro ao carregar JSON: {e}")
    return produtos_por_link

def salvar_json(produtos_por_link):
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(list(produtos_por_link.values()), f, indent=2, ensure_ascii=False)

def aguardar_captcha(page):
    captcha_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[src*='captcha']",
        ".g-recaptcha",
        "#captcha",
        ".captcha-container",
        ".challenge-container"
    ]
    captcha_detected = False
    for selector in captcha_selectors:
        if page.locator(selector).count():
            captcha_detected = True
            break

    if not captcha_detected:
        try:
            page.wait_for_selector('.product-intro__head-name h1, h1.fsp-element', timeout=5000)
            return
        except:
            captcha_detected = True

    if captcha_detected:
        log("⚠️ Captcha detectado! Por favor, resolva-o manualmente no navegador.")
        log("Aguardando resolução do captcha...")
        try:
            page.wait_for_selector('.product-intro__head-name h1, h1.fsp-element', timeout=0)
            log("✅ Captcha resolvido. Continuando extração...")
        except Exception:
            page.wait_for_selector('.product-intro__head-name h1, h1.fsp-element', timeout=0)
            log("✅ Captcha resolvido. Continuando extração...")
        random_delay(2, 4)

def processar_produto(page, link: str, produtos_por_link):
    max_tentativas = 2
    for tentativa in range(1, max_tentativas + 1):
        log(f"Acessando: {link} (tentativa {tentativa}/{max_tentativas})")
        try:
            page.goto(link, timeout=60000, wait_until="domcontentloaded")
            random_delay(2, 4)

            try:
                cookie_btn = page.locator('.cmp_c_1100 .cmp_c_2')
                if cookie_btn.count() and cookie_btn.is_visible():
                    cookie_btn.click(force=True)
                    log("Cookies aceitos.")
                    random_delay(1, 2)
            except:
                pass

            try:
                close_btn = page.locator('.dialog-header-v2__close-btn span')
                if close_btn.count() and close_btn.is_visible():
                    close_btn.click(force=True)
                    log("Modal de cupons fechado.")
                    random_delay(1, 2)
            except:
                pass

            aguardar_captcha(page)

            try:
                page.wait_for_selector('.product-intro__head-name h1, h1.fsp-element', timeout=20000)
                break
            except Exception as e:
                log(f"Timeout aguardando título (tentativa {tentativa}): {e}")
                if tentativa == max_tentativas:
                    log(f"Falha definitiva para {link}")
                    return None
                log("Recarregando página...")
                page.reload(wait_until="domcontentloaded")
                random_delay(3, 5)
                continue
        except Exception as e:
            log(f"Erro ao carregar página (tentativa {tentativa}): {e}")
            if tentativa == max_tentativas:
                return None
            random_delay(3, 5)

    nome = extrair_nome(page)
    if not nome:
        log(f"Nome não encontrado para {link}")
        return None

    preco_atual, preco_original = extrair_precos(page)
    if preco_atual is None or preco_atual == 0:
        log(f"Preço não encontrado para {link}")
        return None

    descricao = extrair_descricao(page) or nome
    categoria_original = extrair_categoria_shein(page)
    imagem_filename = extrair_imagem_alta_resolucao(page, nome)

    categorias_existentes = [prod.get('categoria', '') for prod in produtos_por_link.values() if prod.get('categoria')]
    categoria_sugerida = obter_categoria_llm(nome, descricao, categorias_existentes)
    if categoria_sugerida:
        log(f"🤖 IA sugeriu categoria: '{categoria_sugerida}' (original: '{categoria_original}')")
        categoria = categoria_sugerida
    else:
        categoria = categoria_original if categoria_original else "Geral"
        if not categoria_sugerida:
            log(f"ℹ️ Usando categoria original: '{categoria}'")

    produto = {
        "id": extrair_id_produto(link),
        "nome": nome,
        "preco": round(preco_atual, 2),
        "preco_original": round(preco_original, 2) if preco_original else None,
        "descricao": descricao,
        "imagem": imagem_filename,
        "link": link,
        "categoria": categoria
    }

    preco_original_str = f"R$ {preco_original:.2f}" if preco_original else "N/A"
    log(f"✔ Extraído: {nome} - R$ {preco_atual:.2f} | Original: {preco_original_str} | Categoria: {categoria}")
    return produto

def main():
    kill_chrome_processes()

    if not LINKS_TXT.exists():
        log(f"Arquivo de links não encontrado: {LINKS_TXT}")
        return

    with open(LINKS_TXT, 'r', encoding='utf-8') as f:
        links = [linha.strip() for linha in f if linha.strip().startswith('http')]

    if not links:
        log("Nenhum link válido encontrado.")
        return

    log(f"Total de links a processar: {len(links)}")
    produtos_por_link = carregar_json_existente()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE_DIR),
            headless=False,
            viewport={'width': 1920, 'height': 1080},
            user_agent=random.choice(USER_AGENTS),
            locale='pt-BR',
            timezone_id='America/Sao_Paulo',
            extra_http_headers={
                'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
                'Referer': 'https://www.google.com/'
            },
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-infobars',
                '--disable-dev-shm-usage'
            ]
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en'] });
        """)

        page = context.new_page()

        for idx, link in enumerate(links, 1):
            log(f"\n[{idx}/{len(links)}] Processando...")
            try:
                produto = processar_produto(page, link, produtos_por_link)
                if produto:
                    produtos_por_link[link] = produto
                    salvar_json(produtos_por_link)
                    log(f"✅ Salvo/atualizado: {produto['nome']}")
                else:
                    log(f"❌ Falha ao extrair dados de {link}")
            except Exception as e:
                log(f"❌ Erro crítico em {link}: {e}")
            random_delay(5, 10)

        log(f"\n✅ Concluído. Total de produtos no JSON: {len(produtos_por_link)}")
        input("Pressione ENTER para fechar o navegador...")
        context.close()

if __name__ == "__main__":
    main()