import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from shopee_affiliate import client

load_dotenv()

# ================= CONFIGURAÇÕES =================
JSON_PATH = Path(os.getenv("JSON_SHOPEE", "./shopee_produtos.json"))
IMAGES_DIR = Path(os.getenv("IMAGES_SHOPEE", "./shopee_images"))
LINKS_FILE = Path(os.getenv("TXT_SHOPEE", "./shopee_links.txt"))

# Lê as credenciais do arquivo .env
PARTNER_ID = os.getenv("SHOPEE_PARTNER_ID")
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY")

# Cria os diretórios se não existirem
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ================= FUNÇÕES =================
def load_json():
    """Carrega o JSON existente ou cria uma lista vazia."""
    if JSON_PATH.exists():
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_json(data):
    """Salva os dados no arquivo JSON."""
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def download_image(image_url, filename):
    """Baixa e salva a imagem do produto."""
    try:
        response = requests.get(image_url, stream=True, timeout=15)
        response.raise_for_status()
        filepath = IMAGES_DIR / filename
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"❌ Erro ao baixar imagem: {e}")
        return False

def read_links():
    """Lê os links de um arquivo TXT."""
    if not LINKS_FILE.exists():
        print(f"Arquivo de links não encontrado: {LINKS_FILE}")
        return []
    with open(LINKS_FILE, 'r', encoding='utf-8') as f:
        return [linha.strip() for linha in f if linha.strip().startswith('http')]

def process_product(produto_api, link_original):
    """Estrutura os dados no formato desejado e baixa a imagem."""
    if not produto_api:
        return None

    # Usa o ID da API como identificador único
    product_id = str(produto_api.get('item_id')) # Ajuste o campo conforme a API retornar

    # Gera um nome de arquivo único para a imagem
    img_filename = f"{product_id}.jpg"
    img_url = produto_api.get('image', '')
    if img_url:
        download_image(img_url, img_filename)

    product_data = {
        "id": product_id,
        "nome": produto_api.get('name', ''),
        "preco": float(produto_api.get('price', 0.0)),
        "descricao": produto_api.get('description', ''),
        "imagem": img_filename,
        "link": link_original,
        "categoria": produto_api.get('category', 'Geral') # Ajuste o campo
    }
    return product_data

# ================= MAIN =================
def main():
    if not PARTNER_ID or not PARTNER_KEY:
        print("❌ Credenciais SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY não encontradas no arquivo .env.")
        return

    lista_links = read_links()
    if not lista_links:
        print("Nenhum link encontrado.")
        return

    print(f"🔗 Total de links: {len(lista_links)}")
    print("🚀 Conectando à API de Afiliados Shopee...")
    cliente = client.create_sync_client(partner_id=PARTNER_ID, partner_key=PARTNER_KEY)

    produtos_existentes = load_json()
    ids_existentes = {p['id'] for p in produtos_existentes}

    for idx, link in enumerate(lista_links, 1):
        print(f"\n[{idx}/{len(lista_links)}] Processando: {link}")
        try:
            # Obtém os detalhes do produto via API
            resultado_api = cliente.get_product_offer(url=link)

            # Extrai a informação do produto da resposta da API
            # Este caminho pode variar. Ajuste de acordo com a resposta real.
            info_produto = resultado_api.get('data', {}).get('product', {})
            if not info_produto:
                print(f"⚠️ Não foi possível obter detalhes para {link}. Pulando...")
                continue

            # Converte para o formato do seu JSON
            novo_produto = process_product(info_produto, link)

            if novo_produto:
                if novo_produto['id'] in ids_existentes:
                    for i, p in enumerate(produtos_existentes):
                        if p['id'] == novo_produto['id']:
                            produtos_existentes[i] = novo_produto
                            break
                else:
                    produtos_existentes.append(novo_produto)
                    ids_existentes.add(novo_produto['id'])
                save_json(produtos_existentes)
                print(f"✅ Produto '{novo_produto['nome']}' processado com sucesso!")
        except Exception as e:
            print(f"❌ Erro crítico para o link {link}: {e}")

    print("\n🎉 Processamento finalizado!")

if __name__ == "__main__":
    main()