import os
import re
import json
import time
import random
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO
from llm_category import obter_categoria_llm

# Carrega variáveis do arquivo .env
load_dotenv()

def expand_path(path_str: str) -> Path:
    """Expande variáveis de ambiente (ex: %VAR%) e retorna um Path."""
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

# ================= CONFIGURAÇÕES (lidas do .env) =================
LINKS_TXT = expand_path(os.getenv("TXT_MERCADO_LIVRE", ""))
IMAGENS_DIR = expand_path(os.getenv("IMAGES_MERCADO_LIVRE", ""))
JSON_PATH = expand_path(os.getenv("JSON_MERCADO_LIVRE", ""))

# Cria os diretórios se não existirem
IMAGENS_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

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

def random_delay(min_sec=1.5, max_sec=4.0):
    time.sleep(random.uniform(min_sec, max_sec))

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip().replace(" ", "_")
    return name[:200]

def extrair_id_produto(url: str) -> str:
    match = re.search(r'/p/(MLB\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'MLB-?(\d+)', url)
    if match:
        return f"MLB{match.group(1)}"
    return url.rstrip('/').split('/')[-1]

def extrair_preco(page) -> tuple:
    preco_atual = None
    preco_anterior = None

    try:
        page.wait_for_selector('div#price', timeout=15000)
    except:
        log("Aviso: Container #price não encontrado após 15s")

    price_container = page.locator('div#price').first
    if not price_container.count():
        price_container = page.locator('.ui-pdp-price').first

    if price_container.count():
        try:
            current_elem = price_container.locator('.ui-pdp-price__second-line .andes-money-amount--cents-superscript').first
            if current_elem.is_visible():
                inteiro = current_elem.locator('.andes-money-amount__fraction').inner_text().strip()
                cents_elem = current_elem.locator('.andes-money-amount__cents')
                cents = cents_elem.inner_text().strip() if cents_elem.count() else "0"
                preco_atual = float(f"{inteiro}.{cents}")
                log(f"DEBUG: Preço atual = {preco_atual}")
            else:
                log("DEBUG: Elemento de preço atual não visível")
        except Exception as e:
            log(f"DEBUG: Erro ao extrair preço atual: {e}")

        try:
            old_elem = price_container.locator('.andes-money-amount--previous').first
            if old_elem.is_visible():
                inteiro_ant = old_elem.locator('.andes-money-amount__fraction').inner_text().strip()
                cents_ant_elem = old_elem.locator('.andes-money-amount__cents')
                cents_ant = cents_ant_elem.inner_text().strip() if cents_ant_elem.count() else "0"
                preco_anterior = float(f"{inteiro_ant}.{cents_ant}")
                log(f"DEBUG: Preço anterior = {preco_anterior}")
            else:
                log("DEBUG: Preço anterior não encontrado (produto sem desconto)")
        except Exception as e:
            log(f"DEBUG: Erro ao extrair preço anterior: {e}")
    else:
        log("DEBUG: Container de preço não encontrado")

    if preco_atual is None:
        try:
            elem = page.locator('.andes-money-amount--cents-superscript:not(.andes-money-amount--previous)').first
            if elem.is_visible():
                inteiro = elem.locator('.andes-money-amount__fraction').inner_text().strip()
                cents_elem = elem.locator('.andes-money-amount__cents')
                cents = cents_elem.inner_text().strip() if cents_elem.count() else "0"
                preco_atual = float(f"{inteiro}.{cents}")
                log(f"DEBUG: Preço atual (fallback) = {preco_atual}")
        except:
            pass

    if preco_anterior is None:
        try:
            elem_ant = page.locator('.andes-money-amount--previous').first
            if elem_ant.is_visible():
                inteiro_ant = elem_ant.locator('.andes-money-amount__fraction').inner_text().strip()
                cents_ant_elem = elem_ant.locator('.andes-money-amount__cents')
                cents_ant = cents_ant_elem.inner_text().strip() if cents_ant_elem.count() else "0"
                preco_anterior = float(f"{inteiro_ant}.{cents_ant}")
                log(f"DEBUG: Preço anterior (fallback) = {preco_anterior}")
        except:
            pass

    return preco_atual, preco_anterior

def extrair_categoria_ml(page) -> str:
    """Extrai a categoria do breadcrumb do Mercado Livre."""
    try:
        items = page.locator('.andes-breadcrumb__item')
        if items.count() == 0:
            return ""
        if items.count() >= 2:
            categoria = items.nth(items.count() - 2).inner_text().strip()
        else:
            categoria = items.last.inner_text().strip()
        if "Bebê" in categoria or "Infantil" in categoria:
            return "Infantil"
        if "Pet" in categoria or "Animal" in categoria:
            return "Pets"
        return categoria
    except:
        return ""

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
        desc = page.locator('.ui-pdp-description__content').first
        if desc.count():
            return desc.inner_text().strip()[:500]
    except:
        pass
    return ""

def extrair_imagem_alta_resolucao(page, nome_produto: str) -> str:
    img_url = None
    try:
        figura = page.locator('.ui-pdp-gallery__figure__image').first
        if figura.count():
            img_url = figura.get_attribute('data-zoom')
            if not img_url:
                img_url = figura.get_attribute('src')
            if not img_url:
                srcset = figura.get_attribute('srcset')
                if srcset:
                    urls = re.findall(r'(https?://[^\s]+) \d+w', srcset)
                    if urls:
                        img_url = urls[-1]
        if not img_url:
            imagens = page.query_selector_all('.ui-pdp-image')
            for img in imagens:
                if 'clip' not in img.get_attribute('class', ''):
                    url = img.get_attribute('data-zoom') or img.get_attribute('src')
                    if url and 'http' in url:
                        img_url = url
                        break
        if not img_url:
            img_elem = page.locator('.ui-pdp-gallery__figure img').first
            if img_elem.count():
                img_url = img_elem.get_attribute('src')
        if img_url:
            img_url = img_url.split('?')[0]
            if '_F.' in img_url or '_2X.' in img_url:
                pass
            else:
                img_url = re.sub(r'-(?:O|B|V|C|L)\.', '-F.', img_url)
                img_url = re.sub(r'/_Q_', '/_NQ_', img_url)
                img_url = img_url.replace('_R.webp', '_F.webp')
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = requests.get(img_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content))
                filename = sanitize_filename(nome_produto) + ".jpg"
                filepath = IMAGENS_DIR / filename
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(filepath, 'JPEG', quality=90)
                return filename
    except Exception as e:
        log(f"Erro na imagem: {e}")
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

def clicar_ir_para_produto(page):
    selectors = [
        'a.poly-component__link--action-link:has-text("Ir para produto")',
        'a.poly-component__link--action-link',
        'a:has-text("Ir para produto")',
        'a:has-text("Ver produto")'
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible():
                log("Botão 'Ir para produto' encontrado. Clicando...")
                with page.expect_navigation(wait_until="load", timeout=30000):
                    btn.click()
                log("Navegação concluída.")
                return True
        except:
            continue
    return False

def processar_produto(page, link: str):
    max_tentativas = 3
    for tentativa in range(1, max_tentativas + 1):
        log(f"Acessando: {link} (tentativa {tentativa}/{max_tentativas})")
        try:
            page.goto(link, timeout=60000, wait_until="domcontentloaded")
            random_delay(2, 4)

            try:
                cookie_btn = page.locator('button[data-testid="action:understood-button"]')
                if cookie_btn.count() and cookie_btn.is_visible():
                    cookie_btn.click()
                    log("Cookies aceitos.")
                    random_delay(1, 2)
            except:
                pass

            if clicar_ir_para_produto(page):
                try:
                    page.wait_for_selector('h1.ui-pdp-title, .ui-pdp-title', timeout=20000)
                except:
                    log("Aviso: Título não apareceu após navegação.")
                random_delay(1, 2)

            try:
                page.wait_for_selector('h1.ui-pdp-title, .ui-pdp-title', timeout=40000)
                break
            except Exception as e:
                log(f"Timeout aguardando título (tentativa {tentativa}): {e}")
                if tentativa == max_tentativas:
                    log(f"Falha definitiva para {link} após {max_tentativas} tentativas.")
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

    nome_elem = page.locator('h1.ui-pdp-title').first
    if nome_elem.count() == 0:
        nome_elem = page.locator('.ui-pdp-title').first
    if nome_elem.count() == 0:
        log(f"Nome não encontrado para {link}")
        return None
    nome = nome_elem.inner_text().strip()

    try:
        page.wait_for_selector('div#price .andes-money-amount__fraction', timeout=15000)
    except:
        log("Aviso: Preço não apareceu em 15 segundos")

    preco_atual, preco_anterior = extrair_preco(page)
    if preco_atual is None or preco_atual == 0:
        log(f"Preço não encontrado para {link}")
        return None

    descricao = extrair_descricao(page) or nome
    imagem_filename = extrair_imagem_alta_resolucao(page, nome)
    categoria_original = extrair_categoria_ml(page)

    produtos_existentes = list(carregar_json_existente().values())
    categorias_existentes = [p.get('categoria', '') for p in produtos_existentes if p.get('categoria')]
    if categoria_original and categoria_original not in categorias_existentes:
        categorias_existentes.append(categoria_original)

    categoria_llm = obter_categoria_llm(nome, descricao, categorias_existentes)
    categoria_final = categoria_llm if categoria_llm else categoria_original
    if categoria_llm:
        log(f"🤖 IA sugeriu categoria: '{categoria_llm}' (original: '{categoria_original}')")

    produto = {
        "id": extrair_id_produto(link),
        "nome": nome,
        "preco": round(preco_atual, 2),
        "descricao": descricao,
        "imagem": imagem_filename,
        "link": link,
        "categoria": categoria_final
    }
    if preco_anterior is not None:
        produto["preco_anterior"] = round(preco_anterior, 2)

    log(f"✔ Extraído: {nome} - R$ {preco_atual:.2f} | Categoria: {categoria_final}")
    return produto

def main():
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
        user_agent = random.choice(USER_AGENTS)
        browser = p.chromium.launch(
            headless=False,
            slow_mo=random.randint(150, 300),
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-infobars',
                '--disable-dev-shm-usage'
            ]
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=user_agent,
            locale='pt-BR',
            timezone_id='America/Sao_Paulo',
            extra_http_headers={
                'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
                'Referer': 'https://www.google.com/'
            }
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
                produto = processar_produto(page, link)
                if produto:
                    produtos_por_link[link] = produto
                    salvar_json(produtos_por_link)
                    log(f"✅ Salvo/atualizado: {produto['nome']}")
                else:
                    log(f"❌ Falha ao extrair dados de {link}")
            except Exception as e:
                log(f"❌ Erro crítico em {link}: {e}")
            random_delay(5, 10)

        log(f"\n✅ Concluído. Total: {len(produtos_por_link)}")
        input("Pressione ENTER para fechar o navegador...")
        browser.close()

if __name__ == "__main__":
    main()