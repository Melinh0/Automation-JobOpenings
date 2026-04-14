import os
import re
import time
import json
import random
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO

# ================= CONFIGURAÇÕES DE PASTAS =================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_DIR = os.path.join(BASE_DIR, "json")
TXT_DIR = os.path.join(BASE_DIR, "txt")
IMAGENS_DIR = os.path.join(BASE_DIR, "mercado_pago_imagens")
os.makedirs(JSON_DIR, exist_ok=True)
os.makedirs(TXT_DIR, exist_ok=True)
os.makedirs(IMAGENS_DIR, exist_ok=True)

PRODUTOS_JSON = os.path.join(JSON_DIR, "produtos_mercado_pago.json")
LINKS_TXT = os.path.join(TXT_DIR, "links_mercado_pago.txt")
URL_BASE = "https://www.mercadolivre.com.br/"

# Lista de user agents reais (para rotacionar)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def random_delay(min_sec=0.5, max_sec=2.0):
    """Aguarda um tempo aleatório entre min e max segundos."""
    time.sleep(random.uniform(min_sec, max_sec))

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def aceitar_cookies_stealth(page):
    """Tenta aceitar cookies com cliques suaves e espera variável."""
    selectores = [
        'button[data-testid="action:understood-button"]',
        'button:has-text("Aceitar cookies")',
        'button:has-text("Aceptar cookies")',
        'button:has-text("Entendi")'
    ]
    for selector in selectores:
        try:
            btn = page.locator(selector)
            if btn.count() and btn.is_visible():
                # Movimento do mouse até o botão
                box = btn.bounding_box()
                if box:
                    page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    random_delay(0.2, 0.5)
                btn.click()
                log("✅ Cookies aceitos.")
                random_delay(1, 1.5)
                return True
        except:
            continue
    return False

def extrair_id_produto(url):
    match = re.search(r'/p/(MLB\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'MLB-(\d+)', url)
    if match:
        return f"MLB-{match.group(1)}"
    return url

def extrair_preco(page):
    try:
        preco_elem = page.locator('.andes-money-amount__fraction')
        if preco_elem.count():
            preco_texto = preco_elem.first.inner_text().strip()
            preco_texto = preco_texto.replace('.', '').replace(',', '.')
            return float(preco_texto)
        preco_meta = page.locator('meta[itemprop="price"]')
        if preco_meta.count():
            preco_texto = preco_meta.first.get_attribute('content')
            if preco_texto:
                return float(preco_texto)
        preco_promo = page.locator('.ui-pdp-price__second-line .andes-money-amount__fraction')
        if preco_promo.count():
            preco_texto = preco_promo.first.inner_text().strip()
            preco_texto = preco_texto.replace('.', '').replace(',', '.')
            return float(preco_texto)
    except Exception as e:
        log(f"Erro ao extrair preço: {e}")
    return 0.0

def aplicar_filtros_stealth(page):
    """Aplica filtros com movimentos humanos e delays aleatórios."""
    log("Aplicando filtros (Samsung → Novo → Galaxy)")

    # Ordenar por menor preço
    try:
        ordenar_btn = page.locator('.andes-dropdown__trigger').first
        ordenar_btn.scroll_into_view_if_needed()
        random_delay(0.5, 1)
        ordenar_btn.click()
        random_delay(0.8, 1.2)
        page.locator('li:has-text("Menor preço")').click()
        log("✅ Ordenação por menor preço")
        random_delay(1.5, 2.5)
    except Exception as e:
        log(f"⚠️ Erro na ordenação: {e}")

    for filtro in ["Samsung", "Novo", "Galaxy"]:
        try:
            seletor = f'a[title="{filtro}"]'
            elem = page.locator(seletor).first
            if elem.is_visible():
                elem.scroll_into_view_if_needed()
                random_delay(0.5, 1)
                elem.click()
                log(f"✅ Filtro '{filtro}' aplicado")
                random_delay(1, 1.8)
            else:
                log(f"⚠️ Filtro '{filtro}' não encontrado")
        except Exception as e:
            log(f"⚠️ Erro no filtro {filtro}: {e}")

def scroll_aleatorio(page):
    """Rola a página de forma humana."""
    total_height = page.evaluate("document.body.scrollHeight")
    viewport_height = page.viewport_size["height"]
    max_scroll = max(0, total_height - viewport_height)
    if max_scroll > 0:
        scroll_to = random.randint(0, max_scroll)
        page.evaluate(f"window.scrollTo({{top: {scroll_to}, behavior: 'smooth'}})")
        random_delay(0.5, 1.2)

def main():
    with sync_playwright() as p:
        # Escolhe um user agent aleatório
        user_agent = random.choice(USER_AGENTS)

        browser = p.chromium.launch(
            headless=False,
            slow_mo=random.randint(50, 150),  # delay entre ações
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-infobars',
                '--disable-dev-shm-usage'
            ]
        )

        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},  # viewport fixo e comum
            user_agent=user_agent,
            locale='pt-BR',
            timezone_id='America/Sao_Paulo',
            permissions=['geolocation'],
            extra_http_headers={
                'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Referer': 'https://www.google.com/',
                'Upgrade-Insecure-Requests': '1'
            }
        )

        page = context.new_page()

        # ========== SCRIPT STEALTH PARA REMOVER VESTÍGIOS DE AUTOMAÇÃO ==========
        page.add_init_script("""
            // Remover propriedade 'webdriver'
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            // Remover 'chrome' (se existir)
            window.chrome = { runtime: {} };
            // Alterar plugins para parecer um navegador real
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            // Alterar linguagens
            Object.defineProperty(navigator, 'languages', {
                get: () => ['pt-BR', 'pt', 'en']
            });
            // Simular 'permissions'
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        # Acessar a página inicial
        log(f"Acessando {URL_BASE} com UA: {user_agent[:50]}...")
        page.goto(URL_BASE, timeout=60000, wait_until="load")  # evita networkidle
        random_delay(2, 4)

        # Aguarda o campo de busca
        try:
            page.wait_for_selector('input.nav-search-input', timeout=20000)
        except:
            log("⚠️ Campo de busca não encontrado. Tentando scroll...")
            scroll_aleatorio(page)
            page.wait_for_selector('input.nav-search-input', timeout=15000)

        aceitar_cookies_stealth(page)

        # Buscar produto
        log("Buscando por 'samsung galaxy'...")
        search_input = page.locator('input.nav-search-input')
        search_input.scroll_into_view_if_needed()
        random_delay(0.5, 1)
        search_input.click()
        random_delay(0.2, 0.5)
        search_input.type("samsung galaxy", delay=random.randint(50, 120))
        random_delay(0.5, 1)
        search_input.press("Enter")

        # Aguarda carregamento dos resultados
        page.wait_for_load_state("load", timeout=30000)
        random_delay(2, 4)

        aplicar_filtros_stealth(page)

        # Scroll aleatório na página de resultados
        scroll_aleatorio(page)
        random_delay(1, 2)

        # Preparar arquivos
        with open(LINKS_TXT, "w", encoding="utf-8") as f:
            f.write("")
        log(f"Arquivo TXT preparado: {LINKS_TXT}")

        # Carregar produtos já processados
        ids_processados = set()
        nomes_processados = set()
        urls_processadas = set()
        produtos_existentes = []
        if os.path.exists(PRODUTOS_JSON):
            try:
                with open(PRODUTOS_JSON, "r", encoding="utf-8") as f:
                    conteudo = f.read().strip()
                    if conteudo:
                        produtos_existentes = json.loads(conteudo)
                        for item in produtos_existentes:
                            ids_processados.add(item.get("id_produto", extrair_id_produto(item["url_produto"])))
                            nomes_processados.add(item["nome"].strip().lower())
                            urls_processadas.add(item["url_produto"])
            except:
                produtos_existentes = []

        pagina = 1
        while True:
            log(f"\n📄 Página {pagina}")
            try:
                page.wait_for_selector('li.ui-search-layout__item', timeout=15000)
            except:
                log("Nenhum produto encontrado. Encerrando.")
                break

            cards = page.query_selector_all('li.ui-search-layout__item')
            produtos_novos = []
            for card in cards:
                shipping = card.query_selector('.poly-component__shipping')
                if shipping and "Frete grátis" in shipping.inner_text():
                    link_elem = card.query_selector('a.poly-component__title')
                    if link_elem:
                        link = link_elem.get_attribute('href')
                        if link and link not in urls_processadas:
                            prod_id = extrair_id_produto(link)
                            if prod_id not in ids_processados:
                                produtos_novos.append((link, prod_id))

            log(f"Produtos com frete grátis (novos): {len(produtos_novos)}")

            for link, prod_id in produtos_novos:
                with context.new_page() as product_page:
                    try:
                        product_page.goto(link, timeout=45000, wait_until="load")
                        random_delay(1.5, 3)

                        # Extrair nome
                        nome_elem = product_page.query_selector('h1.ui-pdp-title')
                        nome = nome_elem.inner_text() if nome_elem else "Produto sem nome"
                        nome_norm = nome.strip().lower()

                        if nome_norm in nomes_processados:
                            log(f"⏭️ Produto já salvo (nome duplicado): {nome}")
                            continue

                        preco = extrair_preco(product_page)

                        # Imagem
                        img = product_page.query_selector('.ui-pdp-image')
                        img_url = img.get_attribute('src') if img else None
                        imagem_local = None
                        if img_url:
                            try:
                                resp = requests.get(img_url, timeout=10)
                                if resp.status_code == 200:
                                    img_pil = Image.open(BytesIO(resp.content))
                                    nome_limpo = re.sub(r'[\\/*?:"<>|]', "", nome)[:100]
                                    caminho = os.path.join(IMAGENS_DIR, f"{nome_limpo}.png")
                                    img_pil.save(caminho, "PNG")
                                    imagem_local = caminho
                            except Exception as e:
                                log(f"Erro na imagem: {e}")

                        dados = {
                            "nome": nome,
                            "url_produto": link,
                            "id_produto": prod_id,
                            "preco": preco,
                            "imagem_local": imagem_local,
                            "data_extracao": datetime.now().isoformat()
                        }
                        produtos_existentes.append(dados)

                        with open(PRODUTOS_JSON, "w", encoding="utf-8") as f:
                            json.dump(produtos_existentes, f, indent=2, ensure_ascii=False)

                        with open(LINKS_TXT, "a", encoding="utf-8") as f_txt:
                            f_txt.write(link + "\n")

                        ids_processados.add(prod_id)
                        nomes_processados.add(nome_norm)
                        urls_processadas.add(link)
                        log(f"✅ Salvo: {nome} - R$ {preco:.2f}")

                    except Exception as e:
                        log(f"Erro ao processar {link}: {e}")
                    finally:
                        product_page.close()
                    random_delay(1.5, 2.5)  # pausa entre produtos

            # Paginação
            try:
                next_btn = page.query_selector('.andes-pagination__button--next a')
                if next_btn and "disabled" not in (next_btn.get_attribute("class") or ""):
                    # Scroll suave até o botão
                    next_btn.scroll_into_view_if_needed()
                    random_delay(0.5, 1)
                    next_btn.click()
                    page.wait_for_load_state("load", timeout=30000)
                    random_delay(2, 4)
                    pagina += 1
                else:
                    break
            except Exception as e:
                log(f"Fim da paginação: {e}")
                break

        log(f"\n✅ Extração concluída. Total: {len(produtos_existentes)}")
        input("Pressione ENTER para fechar o navegador...")
        browser.close()

if __name__ == "__main__":
    main()