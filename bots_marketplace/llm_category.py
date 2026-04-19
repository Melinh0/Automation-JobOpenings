import os
import json
import re
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

def expand_path(path_str: str) -> Path:
    """Expande variáveis de ambiente (ex: %VAR%) e retorna um Path."""
    if not path_str:
        return Path()
    expanded = os.path.expandvars(path_str)
    return Path(expanded)

# ================= CONFIGURAÇÕES (lidas do .env) =================
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")
OLLAMA_API_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_MODELS_FILE = expand_path(os.getenv("OLLAMA_MODELS_FILE", ""))

# Lista de JSONs de produtos (separados por ; no .env)
produtos_json_env = os.getenv("PRODUTOS_JSONS", "")
PRODUTOS_JSONS = [expand_path(p.strip()) for p in produtos_json_env.split(";") if p.strip()]

def carregar_lista_modelos():
    """Carrega a lista completa de modelos do arquivo."""
    if OLLAMA_MODELS_FILE and OLLAMA_MODELS_FILE.exists():
        try:
            with open(OLLAMA_MODELS_FILE, 'r', encoding='utf-8') as f:
                models = json.load(f)
                if isinstance(models, list) and models:
                    return models
        except Exception as e:
            print(f"[LLM] Erro ao carregar modelos: {e}")
    return ["llama3.2"]

MODELOS = carregar_lista_modelos()
modelos_falhos = set()

def carregar_contexto_produtos():
    """
    Carrega todos os produtos dos JSONs e retorna uma string com exemplos
    de produtos e suas categorias (até um limite para não estourar token).
    """
    exemplos = []
    for json_path in PRODUTOS_JSONS:
        if json_path and json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, list):
                        for prod in dados:
                            nome = prod.get('nome', '')
                            categoria = prod.get('categoria', '')
                            if nome and categoria:
                                # Limita nome a 100 caracteres
                                nome_curto = nome[:100] + "..." if len(nome) > 100 else nome
                                exemplos.append(f"- Produto: {nome_curto} | Categoria: {categoria}")
            except Exception as e:
                print(f"[LLM] Erro ao carregar {json_path.name}: {e}")
    # Limitar a 20 exemplos para não estourar o contexto
    if len(exemplos) > 20:
        exemplos = exemplos[:20]
    return "\n".join(exemplos)

def obter_categoria_llm(nome, descricao, categorias_existentes):
    """
    Consulta a API do Ollama tentando vários modelos até obter resposta.
    Inclui contexto dos produtos já existentes (nomes e categorias) como exemplos.
    Retorna categoria ou string vazia.
    """
    if not nome:
        return ""
    if not OLLAMA_API_KEY:
        print("[LLM] ⚠️ OLLAMA_API_KEY não configurada. Pulando categorização.")
        return ""

    desc = descricao[:500] if descricao else ""
    cats = [c for c in set(categorias_existentes) if c and c.strip()]
    cats_str = ", ".join(cats) if cats else "nenhuma ainda"

    # Carrega exemplos de produtos já classificados
    exemplos_str = carregar_contexto_produtos()
    contexto_exemplos = f"""
Aqui estão alguns exemplos de produtos já classificados no sistema:
{exemplos_str}
""" if exemplos_str else ""

    prompt = f"""
Você é um assistente que classifica produtos em categorias padronizadas.
{contexto_exemplos}
Produto atual: "{nome}"
Descrição: "{desc}"
Categorias já existentes no sistema (você pode reutilizá-las): {cats_str}

Responda APENAS com o nome da categoria mais adequada para este produto.
- Se possível, use uma das categorias existentes.
- Se nenhuma se encaixar, crie uma nova categoria curta e genérica (ex: "Eletrônicos", "Roupas", "Calçados", "Casa", "Beleza", etc.).
- Não inclua explicações, apenas o nome da categoria.
"""

    headers = {
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
        "Content-Type": "application/json"
    }

    for modelo in MODELOS:
        if modelo in modelos_falhos:
            continue
        print(f"[LLM] Tentando modelo: {modelo}")
        payload = {
            "model": modelo,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "max_tokens": 20}
        }
        try:
            response = requests.post(OLLAMA_API_URL, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                categoria = data.get("response", "").strip()
                categoria = re.sub(r'[^\w\s]', '', categoria).strip()
                if categoria:
                    print(f"[LLM] Modelo '{modelo}' retornou: '{categoria}'")
                    return categoria
                else:
                    print(f"[LLM] Modelo '{modelo}' retornou resposta vazia. Tentando próximo...")
            else:
                print(f"[LLM] Modelo '{modelo}' falhou com status {response.status_code}")
        except Exception as e:
            print(f"[LLM] Modelo '{modelo}' gerou exceção: {e}")
        modelos_falhos.add(modelo)
        time.sleep(0.5)

    print("[LLM] Nenhum modelo funcionou. Usando fallback vazio.")
    return ""