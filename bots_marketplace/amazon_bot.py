import os
import re
import json
import time
import random
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO

# ================= CONFIGURAÇÕES =================
LINKS_TXT = Path(r"C:\Users\yagom\Documents\GitHub\Automation-JobOpenings\txt\amazon_links.txt")
IMAGENS_DIR = Path(r"C:\Users\yagom\Documents\GitHub\garimpointeligente\public\images\amazon_imagens")
JSON_PATH = Path(r"C:\Users\yagom\Documents\GitHub\garimpointeligente\src\data\produtos_amazon.json")

IMAGENS_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

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

def extrair_id_produto(link: str) -> str:
    match = re.search(r'/(?:dp|product)/([A-Z0-9]{10})', link)
    if match:
        return match.group(1)
    return link.rstrip('/').split('/')[-1]

def extrair_nome(page) -> str:
    try:
        title = page.locator('#productTitle').first
        if title.count():
            return title.inner_text().strip()
        title = page.locator('h1.a-size-large').first
        if title.count():
            return title.inner_text().strip()
    except Exception as e:
        log(f"Erro ao extrair nome: {e}")
    return ""

def limpar_preco(texto: str) -> float:
    texto = re.sub(r'R\$', '', texto).strip()
    texto = re.sub(r'[^\d,\.]', '', texto)
    texto = texto.replace(',', '.')
    if texto.count('.') > 1:
        partes = texto.split('.')
        texto = ''.join(partes[:-1]) + '.' + partes[-1]
    try:
        return float(texto)
    except:
        return 0.0

def extrair_precos(page) -> tuple:
    preco_atual = None
    preco_anterior = None

    # Preço atual via whole+fraction (prioridade)
    try:
        container = page.locator('#corePriceDisplay_desktop_feature_div').first
        if container.count():
            whole = container.locator('.a-price-whole').first
            fraction = container.locator('.a-price-fraction').first
            if whole.count() and fraction.count():
                w = whole.inner_text().strip()
                f = fraction.inner_text().strip()
                preco_atual = limpar_preco(f"{w}.{f}")
                log(f"DEBUG: Preço atual via whole+fraction = {preco_atual}")
    except Exception as e:
        log(f"DEBUG: Erro no whole+fraction: {e}")

    if preco_atual is None or preco_atual == 0:
        try:
            price_apex = page.locator('.apex-pricetopay-value').first
            if price_apex.count():
                text = price_apex.inner_text().strip()
                preco_atual = limpar_preco(text)
                log(f"DEBUG: Preço atual via .apex-pricetopay-value = {preco_atual}")
        except:
            pass

    if preco_atual is None or preco_atual == 0:
        try:
            offscreen = page.locator('.a-price .a-offscreen').first
            if offscreen.count():
                text = offscreen.inner_text().strip()
                if text and text != " ":
                    preco_atual = limpar_preco(text)
                    log(f"DEBUG: Preço atual via .a-offscreen = {preco_atual}")
        except:
            pass

    # Preço anterior
    try:
        old_offscreen = page.locator('.basisPrice .a-text-price .a-offscreen').first
        if old_offscreen.count():
            text = old_offscreen.inner_text().strip()
            if text:
                preco_anterior = limpar_preco(text)
                log(f"DEBUG: Preço anterior via .basisPrice .a-offscreen = {preco_anterior}")
    except:
        pass

    if preco_anterior is None:
        try:
            strike = page.locator('.basisPrice .a-text-price').first
            if strike.count():
                text = strike.inner_text().strip()
                match = re.search(r'R\$\s*([\d\.,]+)', text)
                if match:
                    preco_anterior = limpar_preco(match.group(1))
                    log(f"DEBUG: Preço anterior via regex = {preco_anterior}")
        except:
            pass

    return preco_atual, preco_anterior

def extrair_categoria_amazon(page) -> str:
    """Extrai a categoria mais específica do breadcrumb da Amazon."""
    try:
        links = page.locator('#wayfinding-breadcrumbs_feature_div ul li a')
        if links.count() == 0:
            return ""
        categoria = links.last.inner_text().strip()
        # Mapeia para nosso padrão
        if "Notebook" in categoria or "Computador" in categoria:
            return "Informática"
        if "Suporte" in categoria or "Acessórios" in categoria:
            return "Acessórios de Informática"
        return categoria
    except:
        return ""

def extrair_descricao(page) -> str:
    try:
        bullets = page.locator('#feature-bullets ul li span.a-list-item')
        if bullets.count():
            items = bullets.all_inner_texts()
            desc = " ".join(items).strip()
            if desc:
                return desc[:1000]
    except:
        pass
    try:
        meta = page.locator('meta[name="description"]').first
        if meta.count():
            content = meta.get_attribute('content')
            if content and len(content) > 20:
                return content[:500]
    except:
        pass
    return ""

def extrair_imagem_alta_resolucao(page, nome_produto: str) -> str:
    img_url = None
    try:
        landing = page.locator('#landingImage')
        if landing.count():
            img_url = landing.get_attribute('data-old-hires')
            if not img_url:
                img_url = landing.get_attribute('src')
            if not img_url:
                srcset = landing.get_attribute('srcset')
                if srcset:
                    urls = re.findall(r'(https?://[^\s]+) \d+w', srcset)
                    if urls:
                        img_url = urls[-1]
        if not img_url:
            thumbs = page.locator('#altImages img')
            if thumbs.count():
                for i in range(thumbs.count()):
                    url = thumbs.nth(i).get_attribute('src')
                    if url and 'http' in url:
                        img_url = re.sub(r'/_AC_US\d+_\.jpg', '', url)
                        if img_url.endswith('.jpg'):
                            break
        if img_url:
            img_url = re.sub(r'\._AC_[A-Z0-9]+_\.', '.', img_url)
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
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

def processar_produto(page, link: str):
    max_tentativas = 3
    for tentativa in range(1, max_tentativas + 1):
        log(f"Acessando: {link} (tentativa {tentativa}/{max_tentativas})")
        try:
            page.goto(link, timeout=60000, wait_until="domcontentloaded")
            random_delay(2, 4)

            if 'amzn.to' in page.url or 'amzn.com' in page.url:
                log("Link encurtado detectado, aguardando redirecionamento...")
                page.wait_for_url(lambda url: 'amzn.to' not in url and 'amzn.com' not in url, timeout=15000)
                random_delay(1, 2)

            log(f"URL final: {page.url}")

            try:
                cookie_btn = page.locator('button[data-testid="action:understood-button"]')
                if cookie_btn.count() and cookie_btn.is_visible():
                    cookie_btn.click()
                    log("Cookies aceitos.")
                    random_delay(1, 2)
            except:
                pass

            try:
                page.wait_for_selector('#corePriceDisplay_desktop_feature_div .a-price-whole', timeout=30000)
                random_delay(1, 2)
                break
            except Exception as e:
                log(f"Timeout aguardando preço (tentativa {tentativa}): {e}")
                if tentativa == max_tentativas:
                    log(f"Falha definitiva para {link}")
                    return None
                log("Recarregando...")
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

    preco_atual, preco_anterior = extrair_precos(page)
    if preco_atual is None or preco_atual == 0:
        log(f"Preço não encontrado para {link}")
        return None

    descricao = extrair_descricao(page) or nome
    imagem_filename = extrair_imagem_alta_resolucao(page, nome)
    categoria = extrair_categoria_amazon(page)

    produto = {
        "id": extrair_id_produto(link),
        "nome": nome,
        "preco": round(preco_atual, 2),
        "descricao": descricao,
        "imagem": imagem_filename,
        "link": link,
        "categoria": categoria
    }
    if preco_anterior is not None and preco_anterior > 0:
        produto["preco_anterior"] = round(preco_anterior, 2)

    log(f"✔ Extraído: {nome} - R$ {preco_atual:.2f} | Categoria: {categoria}")
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

        log(f"\n✅ Concluído. Total de produtos no JSON: {len(produtos_por_link)}")
        input("Pressione ENTER para fechar o navegador...")
        browser.close()

if __name__ == "__main__":
    main()