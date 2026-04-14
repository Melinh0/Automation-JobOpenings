import os
import re
import time
import json
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image
from io import BytesIO

# ================= CONFIGURAÇÕES DE PASTAS =================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JSON_DIR = os.path.join(BASE_DIR, "json")
TXT_DIR = os.path.join(BASE_DIR, "txt")
IMAGENS_DIR = os.path.join(BASE_DIR, "shein_imagens")

os.makedirs(JSON_DIR, exist_ok=True)
os.makedirs(TXT_DIR, exist_ok=True)
os.makedirs(IMAGENS_DIR, exist_ok=True)

PRODUTOS_JSON = os.path.join(JSON_DIR, "shein_produtos.json")
LINKS_TXT = os.path.join(TXT_DIR, "shein_links.txt")

URL_BASE = "https://br.shein.com/"
TERMO_BUSCA = "Tenis Esportivo Masculino"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def aceitar_cookies(page):
    try:
        page.wait_for_selector('.cmp_c_1100', timeout=15000)
        log("Banner de cookies detectado.")
        aceitar = page.locator('.cmp_c_1100 .cmp_c_2')
        if aceitar.count() and aceitar.is_visible():
            aceitar.click(force=True)
            log("✅ Cookies aceitos.")
            time.sleep(1)
            return True
    except PlaywrightTimeoutError:
        log("Banner de cookies não apareceu (timeout).")
    except Exception as e:
        log(f"Erro ao aceitar cookies: {e}")
    return False

def fechar_modal_cupons(page):
    try:
        page.wait_for_selector('.dialog-header-v2__close-btn', timeout=8000)
        log("Modal de cupons detectado.")
        fechar = page.locator('.dialog-header-v2__close-btn span')
        if fechar.count() and fechar.is_visible():
            fechar.click(force=True)
            log("✅ Modal de cupons fechado.")
            time.sleep(1)
            return True
    except PlaywrightTimeoutError:
        log("Modal de cupons não apareceu.")
    except Exception as e:
        log(f"Erro ao fechar modal: {e}")
    return False

def buscar_termo(page, termo):
    log(f"Buscando por '{termo}'...")
    # Tenta ativar a barra de pesquisa
    search_box = page.locator('section.search-box, .search-box')
    if search_box.count():
        search_box.first.click(force=True)
        log("Barra de pesquisa ativada.")
        time.sleep(1)
    else:
        log("Elemento search-box não encontrado.")
        return

    # Aguarda o input ficar visível (pode levar alguns segundos)
    search_input = None
    for tentativa in range(10):
        for sel in ['input.search-input', 'input[type="search"]', 'input[name="header-search"]']:
            if page.locator(sel).count():
                candidate = page.locator(sel).first
                if candidate.is_visible():
                    search_input = candidate
                    break
        if search_input:
            break
        log(f"Aguardando campo de busca ficar visível... ({tentativa+1}/10)")
        time.sleep(1)
    if not search_input:
        log("❌ Campo de busca não ficou visível após ativação.")
        page.screenshot(path="debug_shein_search_fail.png")
        return

    search_input.fill(termo)
    search_input.press("Enter")
    page.wait_for_load_state("domcontentloaded")
    time.sleep(5)
    log("✅ Busca realizada.")

def ordenar_menor_preco(page):
    try:
        # Abre o dropdown
        sort_trigger = page.locator('.sui-select__trigger').first
        sort_trigger.click(force=True)
        time.sleep(1)
        # Aguarda o menu aparecer
        page.wait_for_selector('.sui-select__menu', timeout=5000)
        # Seleciona a opção correta
        opcao = page.locator('li.sui-select-option[aria-label="Preço de Baixo Para Alto"]')
        if opcao.count():
            opcao.click(force=True)
            log("✅ Ordenação por menor preço aplicada.")
            time.sleep(2)
            return True
    except Exception as e:
        log(f"Erro ao ordenar: {e}")
    return False

def extrair_dados_produto(page, url_produto):
    try:
        nome_elem = page.locator('.product-intro__head-name h1')
        if nome_elem.count() == 0:
            nome_elem = page.locator('h1.fsp-element')
        nome = nome_elem.inner_text().strip() if nome_elem.count() else "Sem nome"

        preco_elem = page.locator('#productMainPriceId')
        if preco_elem.count() == 0:
            preco_elem = page.locator('.productPrice__main')
        preco_texto = preco_elem.inner_text().strip() if preco_elem.count() else "0"
        preco_limpo = re.sub(r'[^0-9,]', '', preco_texto).replace(',', '.')
        preco = float(preco_limpo) if preco_limpo else 0.0

        img_elem = page.locator('.crop-image-container__img').first
        if img_elem.count() == 0:
            img_elem = page.locator('.normal-picture__content-list .crop-image-container__img').first
        img_url = img_elem.get_attribute('src') if img_elem.count() else None

        return nome, preco, img_url
    except Exception as e:
        log(f"Erro ao extrair dados da página {url_produto}: {e}")
        return None, None, None

def baixar_imagem(img_url, nome_produto):
    if not img_url:
        return None
    try:
        resp = requests.get(img_url, timeout=10)
        if resp.status_code != 200:
            return None
        img = Image.open(BytesIO(resp.content))
        nome_limpo = re.sub(r'[\\/*?:"<>|]', "", nome_produto)[:100]
        caminho = os.path.join(IMAGENS_DIR, f"{nome_limpo}.png")
        img.save(caminho, "PNG")
        return caminho
    except Exception as e:
        log(f"Erro ao baixar imagem: {e}")
        return None

def processar_pagina(page, context, ids_processados, produtos_existentes):
    try:
        page.wait_for_selector('.product-card', timeout=15000)
    except:
        log("Nenhum produto encontrado nesta página.")
        return 0

    cards = page.query_selector_all('.product-card')
    log(f"Total de cards na página: {len(cards)}")
    novos = 0
    for card in cards:
        # Busca o link do produto (prioriza o goods-title-link)
        link_elem = card.query_selector('a.goods-title-link')
        if not link_elem:
            link_elem = card.query_selector('a.S-product-card__img-container')
        if link_elem:
            discount_attr = link_elem.get_attribute('data-discount')
            if discount_attr:
                try:
                    desconto = int(discount_attr)
                except:
                    desconto = 0
                if desconto >= 50:
                    href = link_elem.get_attribute('href')
                    if href and not href.startswith('http'):
                        href = "https://br.shein.com" + href
                    if href and href not in ids_processados:
                        novos += 1
                        log(f"Processando produto com desconto {desconto}%: {href}")
                        with context.new_page() as product_page:
                            try:
                                product_page.goto(href, wait_until='domcontentloaded', timeout=30000)
                                nome, preco, img_url = extrair_dados_produto(product_page, href)
                                if nome:
                                    imagem_local = baixar_imagem(img_url, nome) if img_url else None
                                    dados = {
                                        "nome": nome,
                                        "url_produto": href,
                                        "preco": preco,
                                        "imagem_local": imagem_local,
                                        "data_extracao": datetime.now().isoformat()
                                    }
                                    produtos_existentes.append(dados)
                                    with open(PRODUTOS_JSON, "w", encoding="utf-8") as f:
                                        json.dump(produtos_existentes, f, indent=2, ensure_ascii=False)
                                    ids_processados.add(href)
                                    with open(LINKS_TXT, "a", encoding="utf-8") as f_txt:
                                        f_txt.write(href + "\n")
                                    log(f"✅ Salvo: {nome} (R${preco:.2f})")
                            except Exception as e:
                                log(f"Erro ao carregar página do produto: {e}")
                            finally:
                                product_page.close()
                        time.sleep(1)
    return novos

def tem_proxima_pagina(page):
    next_btn = page.locator('button.sui-pagination__next')
    if next_btn.count():
        # Verifica se o botão não está desabilitado
        is_disabled = next_btn.get_attribute('disabled') is not None
        return not is_disabled
    return False

def ir_proxima_pagina(page):
    next_btn = page.locator('button.sui-pagination__next')
    if next_btn.count() and not next_btn.is_disabled():
        next_btn.click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)
        return True
    return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--start-maximized', '--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            viewport=None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto(URL_BASE, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)

        aceitar_cookies(page)
        fechar_modal_cupons(page)

        buscar_termo(page, TERMO_BUSCA)
        ordenar_menor_preco(page)

        # Aguarda os produtos carregarem
        page.wait_for_selector('.product-card', timeout=15000)

        # Carrega produtos já processados
        produtos_existentes = []
        ids_processados = set()
        if os.path.exists(PRODUTOS_JSON):
            try:
                with open(PRODUTOS_JSON, "r", encoding="utf-8") as f:
                    conteudo = f.read().strip()
                    if conteudo:
                        produtos_existentes = json.loads(conteudo)
                        for item in produtos_existentes:
                            ids_processados.add(item.get("url_produto"))
            except Exception as e:
                log(f"⚠️ Erro ao ler JSON: {e}")

        with open(LINKS_TXT, "w", encoding="utf-8") as f:
            f.write("")

        pagina_atual = 1
        while True:
            log(f"\n📄 Processando página {pagina_atual}...")
            novos_produtos = processar_pagina(page, context, ids_processados, produtos_existentes)
            log(f"Novos produtos salvos nesta página: {novos_produtos}")

            if not tem_proxima_pagina(page):
                log("Fim da paginação.")
                break

            ir_proxima_pagina(page)
            pagina_atual += 1

        log(f"\n✅ Extração concluída. Total de produtos salvos: {len(produtos_existentes)}")
        input("Pressione ENTER para fechar o navegador...")
        browser.close()

if __name__ == "__main__":
    main()