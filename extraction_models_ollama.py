import requests
from bs4 import BeautifulSoup
from typing import List, Set
import json
import os

def fetch_ollama_cloud_models() -> List[str]:
    """
    Extrai todos os modelos disponíveis em https://ollama.com/search?c=cloud
    Retorna uma lista de strings no formato "modelo:tag" (ex: "qwen3.5:latest", "deepseek-v3.2:cloud").
    """
    base_url = "https://ollama.com"
    search_url = f"{base_url}/search?c=cloud"
    all_models: Set[str] = set()
    page_num = 1

    while True:
        print(f"Processando página {page_num}...")
        response = requests.get(search_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # --- 1. Extrai modelos da lista principal (cada card <li x-test-model>) ---
        model_cards = soup.find_all("li", attrs={"x-test-model": True})
        for card in model_cards:
            # Nome base do modelo
            title_span = card.find("span", attrs={"x-test-search-response-title": True})
            if not title_span:
                continue
            base_name = title_span.text.strip()

            # Verifica se tem badge "cloud"
            cloud_badge = card.find("span", class_="bg-cyan-50", string="cloud")
            has_cloud = bool(cloud_badge)

            # Extrai tags de tamanho (x-test-size)
            size_spans = card.find_all("span", attrs={"x-test-size": True})
            size_tags = [span.text.strip() for span in size_spans]

            # Gera as entradas
            # Sempre inclui a tag "latest" (padrão do Ollama)
            all_models.add(f"{base_name}:latest")

            # Inclui "cloud" se existir
            if has_cloud:
                all_models.add(f"{base_name}:cloud")

            # Inclui cada tag de tamanho
            for tag in size_tags:
                all_models.add(f"{base_name}:{tag}")

        # --- 2. Extrai modelos da seção "View all" (tags adicionais, ex: glm-5.1:cloud) ---
        # Procura por links dentro de <section> que levam a "/library/...:cloud" ou similar
        tag_links = soup.select("a[href^='/library/']")
        for link in tag_links:
            href = link.get("href", "")
            # Exemplo: /library/glm-5.1:cloud ou /library/qwen3-vl:235b-cloud
            if ":" in href:
                model_tag = href.split("/library/")[-1]  # pega "glm-5.1:cloud"
                all_models.add(model_tag)

        # --- 3. Verifica se há próxima página (pagination via hx-get) ---
        next_trigger = soup.find("li", attrs={"hx-get": True})
        if not next_trigger:
            break

        next_path = next_trigger.get("hx-get")
        if not next_path or (next_path == "/search?page=2" and page_num >= 2):
            # Evita loop infinito – se já estamos na página 2 e o gatilho ainda aponta para page=2, paramos
            break

        search_url = f"{base_url}{next_path}"
        page_num += 1

    # Opcional: ordenar alfabeticamente para consistência
    return sorted(all_models)

def save_models_to_json(models: List[str], output_dir: str = "json", filename: str = "ollama_models.json"):
    """
    Salva a lista de modelos em um arquivo JSON dentro da pasta especificada.
    Cria a pasta se não existir.
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2, ensure_ascii=False)
    print(f"✅ Modelos salvos em: {filepath}")

def main():
    print("Coletando modelos do Ollama Cloud...")
    models = fetch_ollama_cloud_models()
    print(f"\nTotal de modelos encontrados: {len(models)}")

    # Salva em JSON
    save_models_to_json(models)

    # Opcional: também exibe no console (primeiros 10 como exemplo)
    print("\nPrimeiros 10 modelos:")
    for model in models[:10]:
        print(f"  {model}")

if __name__ == "__main__":
    main()