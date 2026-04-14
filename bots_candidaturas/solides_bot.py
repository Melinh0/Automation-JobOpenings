import os
import sys
import time
import json
import re
import subprocess
import psutil
import traceback
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv
import pdfplumber
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv()

# ================= CONFIGURATION =================
SOLIDES_LOGIN_URL = "https://auth.vagas.solides.com.br/sign-in"
SOLIDES_JOBS_URL = "https://vagas.solides.com.br/"
SEARCH_KEYWORD = os.getenv("SOLIDES_KEYWORD", "bemol")  # default from example
CV_PDF_PATH = os.getenv("CV_PDF_PATH")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")
with open("json/ollama_models.json", "r") as f:
    OLLAMA_MODELS = json.load(f)

# Personal data (set in .env or directly)
NOME_COMPLETO = os.getenv("NOME_COMPLETO", "Yago Melo")
NOME_MAE = os.getenv("NOME_MAE", "")
NOME_PAI = os.getenv("NOME_PAI", "")
TELEFONE = os.getenv("TELEFONE", "")
EMAIL = os.getenv("SOLIDES_EMAIL", "yagomelo20022109@gmail.com")
SENHA = os.getenv("SOLIDES_PASSWORD", "G19+YtfM")
LINKEDIN = os.getenv("LINKEDIN", "")
GITHUB = os.getenv("GITHUB", "https://github.com/Melinh0")
CPF = os.getenv("CPF", "")
RG = os.getenv("RG", "30819709")
CEP = os.getenv("CEP", "60824-010")
BAIRRO = os.getenv("BAIRRO", "Parque Iracema")
RUA = os.getenv("RUA", "Rua Deputado Sebastião Brasilino de Freitas")
NUMERO = os.getenv("NUMERO", "555")
CIDADE = os.getenv("CIDADE", "Fortaleza")
ESTADO = os.getenv("ESTADO", "CE")

# Persistence
PROCESSED_JOBS_FILE = os.path.join("json", "solides_processadas.json")
KNOWLEDGE_BASE_FILE = os.path.join("json", "solides_knowledge_base.json")
MAX_KNOWLEDGE_ENTRIES = 200

# ================= FUNÇÕES AUXILIARES PARA APLICAR VAGA =================

# Variáveis globais para fallback
fallback_count = 0
MAX_FALLBACK = 5

def is_dns_error_page(page):
    """Verifica se a página atual é um erro de DNS (site não encontrado)."""
    try:
        # Verifica por padrões comuns em páginas de erro
        if "DNS_PROBE_FINISHED_NXDOMAIN" in page.content():
            return True
        if "Não é possível acessar esse site" in page.content():
            return True
        if "ERR_NAME_NOT_RESOLVED" in page.content():
            return True
        return False
    except:
        return False

def pagina_nao_encontrada(page):
    """Verifica se a página atual é um erro 404 (página não encontrada)."""
    try:
        if page.locator('h1:has-text("404")').count() > 0:
            return True
        if "Não encontramos a página" in page.content():
            return True
        if "página não encontrada" in page.content():
            return True
        return False
    except:
        return False

def is_login_page(page):
    """Retorna True se a página atual for a tela de login do Solides."""
    try:
        if "sign-in" in page.url.lower() or "login" in page.url.lower():
            return True
        # Verifica elementos comuns da página de login
        if page.locator('#username').count() > 0 or page.locator('input[name="email"]').count() > 0:
            return True
        if "Entrar com sua conta" in page.content():
            return True
        return False
    except:
        return False

def aceitar_cookies(page):
    """Tenta aceitar cookies se o banner aparecer."""
    try:
        cookie_btn = page.locator('button:has-text("Aceitar"), button:has-text("Accept")').first
        if cookie_btn.count() and cookie_btn.is_visible():
            cookie_btn.click()
            log("🍪 Cookies aceitos.")
            time.sleep(1)
            return True
        return False
    except:
        return False

# ================= UTILITIES =================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def extrair_texto_pdf(caminho):
    try:
        with pdfplumber.open(caminho) as pdf:
            texto = "\n".join(pagina.extract_text() for pagina in pdf.pages if pagina.extract_text())
        return texto
    except Exception as e:
        log(f"Erro ao ler PDF: {e}")
        return ""

def carregar_vagas_processadas():
    if os.path.exists(PROCESSED_JOBS_FILE):
        try:
            with open(PROCESSED_JOBS_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return set(dados.get("links", []))
        except:
            pass
    return set()

def salvar_vagas_processadas(links_set):
    try:
        with open(PROCESSED_JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump({"links": list(links_set)}, f, indent=2, ensure_ascii=False)
        log(f"💾 {len(links_set)} vagas processadas salvas.")
    except Exception as e:
        log(f"Erro ao salvar vagas processadas: {e}")

def carregar_conhecimento():
    if os.path.exists(KNOWLEDGE_BASE_FILE):
        try:
            with open(KNOWLEDGE_BASE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []

def salvar_conhecimento(conhecimento):
    if len(conhecimento) > MAX_KNOWLEDGE_ENTRIES:
        conhecimento = conhecimento[-MAX_KNOWLEDGE_ENTRIES:]
    try:
        with open(KNOWLEDGE_BASE_FILE, "w", encoding="utf-8") as f:
            json.dump(conhecimento, f, indent=2, ensure_ascii=False)
        log(f"💾 Base de conhecimento atualizada ({len(conhecimento)} vagas).")
    except Exception as e:
        log(f"Erro ao salvar conhecimento: {e}")

def salvar_conhecimento_vaga(url, titulo, descricao, perguntas_respostas):
    conhecimento = carregar_conhecimento()
    conhecimento = [v for v in conhecimento if v.get("url") != url]
    conhecimento.append({
        "url": url,
        "titulo": titulo,
        "descricao": descricao[:3000],
        "data": datetime.now().isoformat(),
        "perguntas": perguntas_respostas
    })
    salvar_conhecimento(conhecimento)

def similaridade(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def buscar_exemplos_similares(perguntas_atuais, conhecimento, limite=3, limiar=0.4):
    exemplos = []
    for pergunta_atual in perguntas_atuais:
        for vaga in conhecimento:
            for item in vaga.get("perguntas", []):
                pergunta_antiga = item.get("pergunta", "")
                sim = similaridade(pergunta_atual, pergunta_antiga)
                if sim >= limiar:
                    exemplos.append({
                        "pergunta_similar": pergunta_antiga,
                        "resposta_usada": item.get("resposta", ""),
                        "similaridade": sim
                    })
    unicos = {}
    for ex in exemplos:
        if ex["pergunta_similar"] not in unicos or unicos[ex["pergunta_similar"]]["similaridade"] < ex["similaridade"]:
            unicos[ex["pergunta_similar"]] = ex
    melhores = sorted(unicos.values(), key=lambda x: x["similaridade"], reverse=True)[:limite]
    return melhores

def chamar_ollama_com_fallback(messages, temperature=0.2):
    for idx, modelo in enumerate(OLLAMA_MODELS):
        try:
            log(f"🔄 Tentando modelo [{idx+1}/{len(OLLAMA_MODELS)}]: {modelo}")
            url = f"{OLLAMA_HOST}/api/chat"
            headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": modelo, "messages": messages, "stream": False, "temperature": temperature}
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                log(f"✅ Modelo {modelo} respondeu com sucesso!")
                return data["message"]["content"]
            else:
                log(f"❌ Modelo {modelo} erro {response.status_code}: {response.text[:150]}")
        except Exception as e:
            log(f"❌ Exceção no modelo {modelo}: {e}")
    log("🚫 Todos os modelos falharam. Usando fallback por regras.")
    return None

# ================= BROWSER & LOGIN =================
def encontrar_chrome_exe():
    possiveis = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        rf"C:\Users\{os.getenv('USERNAME')}\AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    for p in possiveis:
        if os.path.exists(p):
            return p
    import shutil
    return shutil.which("chrome") or shutil.which("google-chrome")

def iniciar_chrome_com_debug(porta=9223):
    # Mata processos antigos do Chrome na mesma porta
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and 'chrome.exe' in proc.info['name'].lower() and f'--remote-debugging-port={porta}' in str(cmdline):
                log(f"Matando processo Chrome antigo na porta {porta} (PID: {proc.info['pid']})")
                proc.kill()
                time.sleep(1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
    
    chrome_path = encontrar_chrome_exe()
    if not chrome_path:
        log("❌ Não foi possível encontrar o executável do Chrome.")
        return False
    
    user_data_dir = os.path.join(os.environ['TEMP'], 'chrome_solides_debug')
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    
    cmd = [
        chrome_path,
        f'--remote-debugging-port={porta}',
        f'--user-data-dir={user_data_dir}',
        '--new-window',
        '--start-maximized',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-default-apps',
        '--disable-sync',
        '--disable-extensions',
        '--disable-popup-blocking',
    ]
    
    log(f"Iniciando Chrome com debug na porta {porta}...")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Aguarda a porta ficar disponível
    for _ in range(60):  # até 30 segundos
        time.sleep(0.5)
        try:
            response = requests.get(f"http://127.0.0.1:{porta}/json/version", timeout=1)
            if response.status_code == 200:
                log("✅ Chrome com debug iniciado com sucesso.")
                return True
        except:
            continue
    log("❌ Falha ao iniciar Chrome com debug (porta não respondeu).")
    return False

def fazer_login(page):
    log("🔐 Verificando sessão no Solides...")
    # Primeiro, tenta acessar a página de vagas diretamente
    page.goto(SOLIDES_JOBS_URL, wait_until='domcontentloaded')
    page.wait_for_load_state("domcontentloaded")
    time.sleep(2)

    # Verifica se já está logado (elementos típicos da área logada)
    if page.locator('button:has-text("Candidatura rápida")').count() > 0:
        log("✅ Já está logado (botão 'Candidatura rápida' visível).")
        return True
    if "YAGO MELO DA COSTA" in page.content():
        log("✅ Nome do usuário encontrado. Já logado.")
        return True
    if "Minhas candidaturas" in page.content():
        log("✅ Texto 'Minhas candidaturas' encontrado. Já logado.")
        return True

    # Se não estiver logado, prossegue com o login
    log("🔐 Não logado. Iniciando processo de login...")
    page.goto(SOLIDES_LOGIN_URL, wait_until='domcontentloaded')
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)

    # Salva HTML da página de login para depuração
    with open("debug_login.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    log("HTML da página de login salvo em debug_login.html")

    # Tenta localizar o campo de email com seletores abrangentes
    email_input = None
    for selector in [
        'input[type="email"]',
        'input[name="email"]',
        'input[data-testid="field-email"]',
        '#email',
        'input[id*="email" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="e-mail" i]',
        '//input[@type="text"][@name="email"]',
        '//input[contains(@placeholder, "email")]',
    ]:
        try:
            elem = page.locator(selector).first if not selector.startswith('//') else page.locator(f'xpath={selector}').first
            if elem.count() and elem.is_visible():
                email_input = elem
                log(f"✅ Campo de email encontrado com seletor: {selector}")
                break
        except:
            continue

    if not email_input:
        log("❌ Campo de email não encontrado. Verifique debug_login.html.")
        return False
    email_input.fill(EMAIL)
    log("Email preenchido.")

    # Campo de senha
    senha_input = None
    for selector in [
        'input[type="password"]',
        'input[name="password"]',
        'input[data-testid="field-password"]',
        '#password',
        'input[id*="password" i]',
        'input[placeholder*="senha" i]',
        '//input[@type="password"]',
    ]:
        try:
            elem = page.locator(selector).first if not selector.startswith('//') else page.locator(f'xpath={selector}').first
            if elem.count() and elem.is_visible():
                senha_input = elem
                log(f"✅ Campo de senha encontrado com seletor: {selector}")
                break
        except:
            continue

    if not senha_input:
        log("❌ Campo de senha não encontrado.")
        return False
    senha_input.fill(SENHA)
    log("Senha preenchida.")

    # Botão de login
    login_btn = None
    for selector in [
        'button[type="submit"]',
        'button:has-text("Entrar")',
        'button:has-text("Sign in")',
        'button[data-testid="button-sign-in"]',
        '//button[contains(text(), "Entrar")]',
    ]:
        try:
            elem = page.locator(selector).first if not selector.startswith('//') else page.locator(f'xpath={selector}').first
            if elem.count() and elem.is_visible():
                login_btn = elem
                log(f"✅ Botão de login encontrado com seletor: {selector}")
                break
        except:
            continue

    if not login_btn:
        log("❌ Botão de login não encontrado.")
        return False
    login_btn.click()
    log("Login submetido. Aguardando redirecionamento...")

    # Aguarda até que a URL não seja mais a de login
    try:
        page.wait_for_url(lambda url: "sign-in" not in url and "login" not in url, timeout=15000)
        log("✅ Redirecionamento detectado.")
    except:
        log("⚠️ Redirecionamento não detectado, mas continuando...")

    # Aguarda apenas o DOM carregar (não espera network idle)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(2)

    # Verifica se o login foi bem-sucedido
    if "vagas.solides.com.br" in page.url or page.locator('button:has-text("Candidatura rápida")').count() > 0:
        log("✅ Login bem-sucedido.")
        return True
    else:
        log(f"❌ Falha no login. URL atual: {page.url}")
        return False

# ================= JOB SEARCH & FILTERS =================
def buscar_vagas_por_palavra_chave(page, keyword):
    log(f"Buscando por: {keyword}")
    search_input = page.locator('#title-field')
    search_input.wait_for(state="visible", timeout=10000)
    search_input.fill(keyword)
    buscar_btn = page.locator('#buscar-vagas-trigger')
    buscar_btn.click()
    page.wait_for_load_state("networkidle")
    time.sleep(3)  

def aplicar_filtros(page):
    log("Abrindo filtros...")
    filtro_btn = page.locator('button[data-cy="button-open-modal-filters"]')
    filtro_btn.wait_for(state="visible", timeout=10000)
    filtro_btn.click()
    log("Modal de filtros aberto. Aguardando carregamento...")

    # Aguarda o modal estar visível
    try:
        page.wait_for_selector('[data-testid="modal-body"]', timeout=5000)
        log("Modal detectado.")
    except:
        log("⚠️ Modal não detectado, continuando mesmo assim.")
    time.sleep(1)

    # Verifica se o filtro "Remoto" já está ativo (chip visível)
    chip_remoto = page.locator('#Remoto-remoto')
    if chip_remoto.count() and chip_remoto.is_visible():
        log("✅ Filtro 'Remoto' já está ativo. Fechando modal.")
        page.keyboard.press("Escape")
        return

    # Localiza o container da seção "Modalidade de trabalho"
    modalidade_container = page.locator('#filter-types-of-work')
    if modalidade_container.count() == 0:
        log("❌ Seção 'Modalidade de trabalho' não encontrada.")
        page.keyboard.press("Escape")
        return

    # Clica no container para abrir o dropdown de opções
    try:
        container_btn = modalidade_container.locator('[data-testid="container"]').first
        if container_btn.count() and container_btn.is_visible():
            container_btn.click()
            log("📂 Dropdown de modalidade aberto.")
            time.sleep(1)
        else:
            log("⚠️ Não foi possível abrir o dropdown, tentando continuar...")
    except Exception as e:
        log(f"⚠️ Erro ao abrir dropdown: {e}")

    # Localiza o campo de busca dentro do container
    search_input = modalidade_container.locator('#inputField, input[data-testid="input"]').first
    if search_input.count() == 0:
        log("❌ Campo de busca não encontrado na seção 'Modalidade de trabalho'.")
        page.keyboard.press("Escape")
        return

    # Digita "Remoto" no campo
    search_input.fill("Remoto")
    log("🔍 Buscando por 'Remoto'...")
    time.sleep(1)

    # Aguarda a opção aparecer e clica nela
    try:
        opcao_remoto = modalidade_container.locator('label[for="remoto"]').first
        if opcao_remoto.count() and opcao_remoto.is_visible():
            opcao_remoto.click()
            log("✅ Opção 'Remoto' selecionada.")
        else:
            cb_remoto = modalidade_container.locator('#remoto, input[data-testid="Remoto"]').first
            if cb_remoto.count() and cb_remoto.is_visible() and not cb_remoto.is_checked():
                cb_remoto.check()
                log("✅ Checkbox 'Remoto' marcado diretamente.")
            else:
                log("❌ Opção 'Remoto' não encontrada.")
                page.keyboard.press("Escape")
                return
    except Exception as e:
        log(f"❌ Erro ao selecionar opção: {e}")
        page.keyboard.press("Escape")
        return

    # Aguarda um pouco para o estado do checkbox ser aplicado
    time.sleep(1)

    # Clica no botão "Filtrar" usando múltiplos seletores
    log("🔍 Procurando botão 'Filtrar'...")
    filtrar_btn = None
    for selector in [
        'button[data-cy="modal-filters-button-find"]',
        'button:has-text("Filtrar")',
        'button[type="button"]:has-text("Filtrar")'
    ]:
        try:
            btn = page.locator(selector).first
            if btn.count() and btn.is_visible():
                filtrar_btn = btn
                log(f"✅ Botão 'Filtrar' encontrado com seletor: {selector}")
                break
        except:
            continue

    if filtrar_btn and filtrar_btn.count():
        # Rola até o botão se necessário
        filtrar_btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        filtrar_btn.click()
        log("Filtros aplicados. Aguardando resultados...")
    else:
        log("❌ Botão 'Filtrar' não encontrado. Tentando fechar modal.")
        page.keyboard.press("Escape")
        return

    page.wait_for_load_state("networkidle")
    time.sleep(2)

def extrair_descricao_vaga(page):
    log("Extraindo descrição da vaga...")
    try:
        # Primeiro, aguarda um elemento que indique que a página carregou
        page.wait_for_selector('h1, .vacancy-title, [class*="job-title"]', timeout=10000)
    except:
        log("⚠️ Título da vaga não encontrado, mas continuando...")
    
    # Lista de seletores comuns para a descrição
    selectors = [
        'div[class*="description"]',
        'div[class*="job-description"]',
        '.vacancy-description',
        '[data-testid="job-description"]',
        'section:has-text("Descrição")',
        'div:has-text("Responsabilidades")',
        'div:has-text("Requisitos")'
    ]
    for selector in selectors:
        try:
            elem = page.locator(selector).first
            if elem.count() and elem.is_visible():
                texto = elem.inner_text()
                if len(texto) > 50:
                    log(f"✅ Descrição encontrada com seletor: {selector}")
                    return texto[:4000]
        except:
            continue
    
    # Fallback: pegar todo o texto do corpo
    texto = page.locator('body').inner_text()
    return texto[:4000]

# ================= FORM HANDLING WITH LLM =================
def extrair_info_curriculo(contexto_cv):
    info = {
        "curso": "Tecnologia da Informação",
        "instituicao": "Instituição de ensino superior",
        "periodo": "Entre 3º e 6º período",
        "experiencia_ia": "Possuo conhecimento prático em IA.",
        "experiencia_automacao": "Experiência em automação com Python.",
        "experiencia_nocode": "Conhecimento em plataformas no-code.",
        "projetos_processos": "Tenho noções de modelagem de processos."
    }
    cv_lower = contexto_cv.lower()
    if "engenharia" in cv_lower:
        info["curso"] = "Engenharia de Software"
    elif "ciência da computação" in cv_lower:
        info["curso"] = "Ciência da Computação"
    if "ufc" in cv_lower or "universidade federal" in cv_lower:
        info["instituicao"] = "UFC"
    elif "uece" in cv_lower:
        info["instituicao"] = "UECE"
    match = re.search(r'(\d+)[º°]?\s*período', cv_lower)
    if match:
        p = int(match.group(1))
        if p <= 2:
            info["periodo"] = "1º ou 2º período"
        elif p <= 4:
            info["periodo"] = "3º ou 4º período"
        else:
            info["periodo"] = "5º ou 6º período"
    return info

def gerar_resposta_fallback(label, tipo, contexto_cv, contexto_vaga, options=None):
    label_lower = label.lower()
    # Dados pessoais
    if "nome completo" in label_lower:
        return NOME_COMPLETO
    if "nome da sua mãe" in label_lower:
        return NOME_MAE
    if "nome do pai" in label_lower:
        return NOME_PAI
    if "cpf" in label_lower:
        return CPF
    if "rg" in label_lower:
        return RG
    if "telefone" in label_lower:
        return TELEFONE
    if "e-mail" in label_lower:
        return EMAIL
    if "linkedin" in label_lower:
        return LINKEDIN
    if "github" in label_lower:
        return GITHUB
    if "pretensão salarial" in label_lower:
        return "R$ 1.500,00"
    if "estado civil" in label_lower:
        return "Solteiro(a)"
    if "cep" in label_lower:
        return CEP
    if "bairro" in label_lower:
        return BAIRRO
    if "rua" in label_lower:
        return RUA
    if "número" in label_lower or "num" in label_lower:
        return NUMERO
    if "cidade" in label_lower:
        return CIDADE
    if "estado" in label_lower and "civil" not in label_lower:
        return ESTADO
    if "cnh" in label_lower:
        return "Sim" if "categoria" not in label_lower else "B"
    if "possui graduação" in label_lower or "graduação em" in label_lower:
        return "Sim"
    if "experiência com suporte técnico" in label_lower:
        return "Sim"
    if "vídeo apresentação" in label_lower:
        return ""  # opcional
    if "link portfólio" in label_lower:
        return GITHUB
    if "indicado" in label_lower:
        return "Não"
    # Para selects/radios com opções
    if tipo == "select" and options:
        return options[0] if options else ""
    if tipo == "radio" and options:
        return options[0]
    return "Sim"

def preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, url_vaga):
    """
    Identifica todos os campos obrigatórios (com warning ou asterisco) e os preenche
    usando LLM. Retorna lista de perguntas/respostas.
    """
    log("🔍 Identificando campos obrigatórios e com erro...")
    # Lista de elementos com erro (borda vermelha, warning icon, etc.)
    # Vamos procurar por:
    # - selects com classe !border-error-500
    # - div com role="alert" contendo "obrigatório"
    # - fieldset com div role="alert"
    # Também capturamos todos os campos visíveis que são obrigatórios (asterisco no label)
    
    campos = []
    # 1. Selects com erro
    error_selects = page.locator('select.border-error-500, select[class*="error"]').all()
    for sel in error_selects:
        try:
            label = page.locator(f'label[for="{sel.get_attribute("id")}"]').inner_text() if sel.get_attribute("id") else "Campo"
            options = sel.evaluate("el => Array.from(el.options).map(opt => opt.text)")
            campos.append({"elemento": sel, "label": label, "tipo": "select", "options": options})
        except:
            pass
    
    # 2. Radio groups com erro (fieldset com texto de erro)
    error_fieldsets = page.locator('fieldset:has(div[role="alert"])').all()
    for fs in error_fieldsets:
        try:
            legend = fs.locator('legend, .text-error').first
            pergunta = legend.inner_text() if legend.count() else "Pergunta"
            radios = fs.locator('input[type="radio"]').all()
            opcoes = []
            for r in radios:
                label_for = page.locator(f'label[for="{r.get_attribute("id")}"]').first
                texto = label_for.inner_text() if label_for.count() else r.get_attribute("value")
                opcoes.append({"elemento": r, "texto": texto})
            campos.append({"tipo": "radio_group", "label": pergunta, "opcoes": opcoes, "elemento_fs": fs})
        except:
            pass
    
    # 3. Inputs/Textareas com classe de erro (border-error-500)
    error_inputs = page.locator('input.border-error-500, textarea.border-error-500').all()
    for inp in error_inputs:
        try:
            label = ""
            inp_id = inp.get_attribute("id")
            if inp_id:
                label_elem = page.locator(f'label[for="{inp_id}"]').first
                if label_elem.count():
                    label = label_elem.inner_text()
            if not label:
                label = inp.get_attribute("placeholder") or "Campo"
            campos.append({"elemento": inp, "label": label, "tipo": "input", "options": []})
        except:
            pass
    
    # 4. Adicionalmente, capturar qualquer campo com asterisco no label (obrigatório)
    asterisk_labels = page.locator('label:has-text("*")').all()
    for lbl in asterisk_labels:
        try:
            label_text = lbl.inner_text().replace("*", "").strip()
            for_id = lbl.get_attribute("for")
            if for_id:
                campo_elem = page.locator(f'#{for_id}').first
                if campo_elem.count() and campo_elem.is_visible():
                    tipo = "select" if campo_elem.get_attribute("tagName") == "SELECT" else "input"
                    if tipo == "select":
                        opts = campo_elem.evaluate("el => Array.from(el.options).map(opt => opt.text)")
                        campos.append({"elemento": campo_elem, "label": label_text, "tipo": "select", "options": opts})
                    else:
                        campos.append({"elemento": campo_elem, "label": label_text, "tipo": "input", "options": []})
        except:
            pass
    
    # Remove duplicatas (pelo elemento)
    unique = []
    seen = set()
    for c in campos:
        if id(c["elemento"]) not in seen:
            seen.add(id(c["elemento"]))
            unique.append(c)
    campos = unique
    
    if not campos:
        log("Nenhum campo obrigatório com erro encontrado.")
        return []
    
    log(f"Encontrados {len(campos)} campos para preencher.")
    
    # Preparar prompt para LLM
    perguntas_labels = [c["label"] for c in campos]
    conhecimento = carregar_conhecimento()
    exemplos = buscar_exemplos_similares(perguntas_labels, conhecimento, limite=2)
    texto_exemplos = ""
    if exemplos:
        texto_exemplos = "\nEXEMPLOS DE RESPOSTAS ANTERIORES:\n"
        for ex in exemplos:
            texto_exemplos += f"Pergunta: \"{ex['pergunta_similar']}\" -> Resposta: \"{ex['resposta_usada']}\"\n"
    
    info_cv = extrair_info_curriculo(contexto_cv)
    prompt = f"""
Você é um assistente de candidatura. Preencha os campos abaixo com base no currículo e na vaga.
Use respostas positivas, nunca diga que não tem experiência.

CURRÍCULO (resumo):
{contexto_cv[:2000]}

DESCRIÇÃO DA VAGA:
{contexto_vaga[:2000]}

DADOS PESSOAIS:
Nome: {NOME_COMPLETO}, CPF: {CPF}, RG: {RG}, Email: {EMAIL}, Telefone: {TELEFONE}
CEP: {CEP}, Bairro: {BAIRRO}, Rua: {RUA}, Número: {NUMERO}, Cidade: {CIDADE}, Estado: {ESTADO}

{texto_exemplos}

CAMPOS A PREENCHER:
{json.dumps([{"label": c["label"], "tipo": c["tipo"]} for c in campos], indent=2, ensure_ascii=False)}

Responda APENAS com um JSON array onde cada objeto tem "label" e "value". Para radios, value deve ser o texto da opção escolhida. Para selects, value deve ser o texto da opção.
Exemplo: [{{"label": "Estado Civil", "value": "Solteiro(a)"}}, {{"label": "Possui graduação?", "value": "Sim"}}]
"""
    resposta_llm = chamar_ollama_com_fallback([{"role": "user", "content": prompt}], temperature=0.3)
    acoes = []
    if resposta_llm and resposta_llm.strip().startswith("["):
        try:
            acoes = json.loads(resposta_llm.strip())
            log("✅ LLM gerou respostas.")
        except:
            log("⚠️ Resposta LLM não é JSON válido.")
    
    perguntas_respostas = []
    for campo in campos:
        label = campo["label"]
        valor = None
        for acao in acoes:
            if acao.get("label", "").strip() == label:
                valor = acao.get("value")
                break
        if valor is None:
            valor = gerar_resposta_fallback(label, campo["tipo"], contexto_cv, contexto_vaga, campo.get("options", []))
        try:
            if campo["tipo"] == "select":
                campo["elemento"].select_option(label=valor)
            elif campo["tipo"] == "radio_group":
                for opt in campo["opcoes"]:
                    if opt["texto"].strip().lower() == valor.strip().lower():
                        opt["elemento"].check(force=True)
                        break
                else:
                    # primeira opção
                    campo["opcoes"][0]["elemento"].check(force=True)
            else:  # input
                campo["elemento"].fill(str(valor))
            log(f"✅ Preenchido '{label}' -> '{valor}'")
            perguntas_respostas.append({"pergunta": label, "resposta": str(valor)})
        except Exception as e:
            log(f"❌ Erro ao preencher '{label}': {e}")
    
    return perguntas_respostas

# ================= MAIN APPLICATION FLOW =================
def aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_vaga, titulo_vaga):
    global fallback_count
    log(f"Candidatando-se a: {titulo_vaga}")
    page.goto(link_vaga)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    if is_dns_error_page(page):
        log(f"⚠️ Erro de DNS (domínio não encontrado) para a vaga: {link_vaga}")
        vagas_processadas_set.add(link_vaga)
        salvar_vagas_processadas(vagas_processadas_set)
        return False

    if pagina_nao_encontrada(page):
        log(f"⚠️ Página da vaga não encontrada (404): {link_vaga}")
        vagas_processadas_set.add(link_vaga)
        salvar_vagas_processadas(vagas_processadas_set)
        return False

    if is_login_page(page):
        log("🔐 Página de login detectada na vaga. Relogando...")
        fazer_login(page, return_url=link_vaga)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
        return aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_vaga, titulo_vaga)

    aceitar_cookies(page)

    contexto_vaga = extrair_descricao_vaga(page)
    log(f"Descrição extraída ({len(contexto_vaga)} caracteres)")

    # Botão de candidatura
    candidatar_selectors = [
        'button:has-text("Candidatura rápida")',
        'button:has-text("Candidatar")',
        'button:has-text("Candidatar-se")',
        'a:has-text("Candidatura rápida")',
        '[data-testid="apply-button"]',
        '#apply-button',
        'button[data-cy="quick-apply-button"]'
    ]
    btn_candidatar = None
    for sel in candidatar_selectors:
        elem = page.locator(sel).first
        if elem.count() and elem.is_visible():
            btn_candidatar = elem
            log(f"✅ Botão de candidatura encontrado com seletor: {sel}")
            break

    if not btn_candidatar:
        log("❌ Nenhum botão de candidatura encontrado")
        return False

    btn_candidatar.click()
    log("Clicou no botão de candidatura.")
    time.sleep(2)

    # Modal de confirmação "Sim"
    modal_sim = page.locator('div[role="dialog"] button:has-text("Sim")')
    if modal_sim.count() and modal_sim.first.is_visible():
        modal_sim.first.click()
        log("Clicou em 'Sim' no modal de confirmação.")
        time.sleep(2)
        continuar_btn = page.locator('button:has-text("Continuar")')
        if continuar_btn.count() and continuar_btn.first.is_visible():
            continuar_btn.first.click()
            log("Clicou em 'Continuar'.")
            time.sleep(2)

    # Loop principal
    max_steps = 30
    consecutive_clicks = 0
    last_button_text = ""

    for step in range(max_steps):
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except:
            pass

        if is_login_page(page):
            log("🔐 Redirecionado para login. Relogando...")
            fazer_login(page, return_url=link_vaga)
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)
            return aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_vaga, titulo_vaga)

        aceitar_cookies(page)

        if "você já se candidatou" in page.content().lower():
            log("⚠️ Vaga já candidatada anteriormente")
            vagas_processadas_set.add(link_vaga)
            salvar_vagas_processadas(vagas_processadas_set)
            return False

        # Finalização
        efetuar = page.locator('button:has-text("Efetuar candidatura")')
        if efetuar.count() and efetuar.first.is_visible():
            efetuar.first.click()
            log("Clicou em 'Efetuar candidatura'.")
            time.sleep(3)
            ok_btn = page.locator('button:has-text("Ok, entendi")')
            if ok_btn.count():
                ok_btn.first.click()
                log("🎉 Candidatura finalizada com sucesso!")
                vagas_processadas_set.add(link_vaga)
                salvar_vagas_processadas(vagas_processadas_set)
                salvar_conhecimento_vaga(link_vaga, titulo_vaga, contexto_vaga, [])
                return True

        finalizar = page.locator('button:has-text("Salvar e Finalizar")')
        if finalizar.count() and finalizar.first.is_visible():
            finalizar.first.click()
            log("Clicou em 'Salvar e Finalizar'.")
            time.sleep(2)
            ok_btn = page.locator('button:has-text("Ok, entendi")')
            if ok_btn.count():
                ok_btn.first.click()
                log("🎉 Candidatura finalizada!")
                vagas_processadas_set.add(link_vaga)
                salvar_vagas_processadas(vagas_processadas_set)
                salvar_conhecimento_vaga(link_vaga, titulo_vaga, contexto_vaga, [])
                return True

        continuar = page.locator('button:has-text("Continuar"), button:has-text("Salvar e continuar")')
        if continuar.count():
            current_text = continuar.first.inner_text()
            if current_text == last_button_text:
                consecutive_clicks += 1
            else:
                consecutive_clicks = 0
                last_button_text = current_text

            if consecutive_clicks > 3:
                log("⚠️ Muitos cliques consecutivos no mesmo botão. Abortando candidatura.")
                break

            if page.locator('.border-error-500, div[role="alert"]:has-text("obrigatório")').count() > 0:
                log("Detectados campos obrigatórios não preenchidos. Preenchendo...")
                perguntas = preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, link_vaga)  # ← corrigido (apenas uma variável)
                if perguntas:
                    salvar_conhecimento_vaga(link_vaga, titulo_vaga, contexto_vaga, perguntas)
                salvar_revisar = page.locator('button:has-text("Salvar e revisar")')
                if salvar_revisar.count():
                    salvar_revisar.first.click()
                    time.sleep(2)
                    continue
                avancar = page.locator('button:has-text("Avançar")')
                if avancar.count():
                    avancar.first.click()
                    time.sleep(2)
                    continue

            url_before = page.url
            continuar.first.click(force=True)
            log("➡️ Clicou em 'Continuar/Salvar'")
            for _ in range(10):
                time.sleep(0.5)
                if page.url != url_before:
                    log("✅ Redirecionamento detectado.")
                    break
                if continuar.count() == 0 or not continuar.first.is_visible():
                    log("✅ Botão 'Continuar' não está mais visível.")
                    break
            else:
                log("⚠️ Nenhuma mudança detectada após clique.")
            time.sleep(2)
            continue

        proximo = page.locator('button:has-text("Próximo")')
        if proximo.count() and proximo.first.is_visible():
            proximo.first.click()
            log("Clicou em 'Próximo'.")
            time.sleep(2)
            continue

        responder = page.locator('button:has-text("Responder agora")')
        if responder.count():
            responder.first.click()
            page.wait_for_selector('input, textarea, select', timeout=10000)
            log("📝 Clicou em 'Responder agora'.")
            time.sleep(2)
            perguntas = preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, link_vaga)  # ← corrigido
            if perguntas:
                salvar_conhecimento_vaga(link_vaga, titulo_vaga, contexto_vaga, perguntas)
            continue

        if page.locator('text="Candidatura enviada"').count():
            log("Mensagem de confirmação encontrada.")
            vagas_processadas_set.add(link_vaga)
            salvar_vagas_processadas(vagas_processadas_set)
            return True

        if fallback_count < MAX_FALLBACK and not is_login_page(page):
            botoes = page.locator('button:not(:has-text("Cancelar"))')
            if botoes.count():
                fallback_count += 1
                try:
                    botoes.first.click(force=True)
                    log("⚠️ Fallback: clicou em botão genérico.")
                    time.sleep(2)
                    continue
                except:
                    pass
        else:
            break

    log("❌ Não foi possível concluir a candidatura após várias tentativas.")
    return False

def processar_vagas(page, contexto_cv, vagas_processadas_set, keyword):
    # Aguarda a presença de pelo menos um card de vaga (ou mensagem de "nenhuma vaga")
    try:
        page.wait_for_selector('a[href*="/vaga/"], .vacancy-card, [data-cy="vacancy-card"]', timeout=10000)
    except:
        log("Nenhuma vaga encontrada ou página sem resultados.")
        return

    # Coleta links de vagas usando múltiplos seletores
    links = []
    # Tenta vários seletores comuns
    for selector in [
        'a[href*="/vaga/"]',
        'a[data-cy="vacancy-card"]',
        '.vacancy-card a',
        'li a[href*="/vaga/"]'
    ]:
        elements = page.locator(selector).all()
        for el in elements:
            href = el.get_attribute("href")
            if href:
                full_link = href if href.startswith("http") else f"https://vagas.solides.com.br{href}"
                if full_link not in vagas_processadas_set:
                    links.append(full_link)
        if links:
            break  # já encontrou links, não precisa tentar outros seletores

    # Remove duplicatas mantendo ordem
    links = list(dict.fromkeys(links))
    log(f"Encontrados {len(links)} links de vagas não processadas.")

    for link in links:
        # Tenta extrair o título da vaga (pode falhar, mas não é crítico)
        try:
            titulo = page.locator(f'a[href="{link}"]').first.inner_text() if page.locator(f'a[href="{link}"]').count() else "Vaga"
        except:
            titulo = "Vaga"
        if aplicar_vaga(page, contexto_cv, vagas_processadas_set, link, titulo):
            log(f"✅ Sucesso na vaga: {titulo}")
        else:
            log(f"❌ Falha na vaga: {titulo}")
        # Voltar para página de busca
        page.goto(SOLIDES_JOBS_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        buscar_vagas_por_palavra_chave(page, keyword)
        aplicar_filtros(page)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        break  # Após processar uma vaga, recomeça a coleta para evitar stale elements

def main():
    try:
        os.makedirs("json", exist_ok=True)
        if not iniciar_chrome_com_debug(9223):
            log("Falha ao iniciar Chrome. Tentando conectar a instância existente...")
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
                page = browser.contexts[0].pages[0]
                log("✅ Conectado ao Chrome existente.")
            except Exception as e:
                log(f"Nenhuma instância encontrada: {e}. Abrindo novo navegador...")
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()

            if not fazer_login(page):
                log("❌ Falha no login. Abortando.")
                return

            if "vagas.solides.com.br" not in page.url:
                page.goto(SOLIDES_JOBS_URL)
                page.wait_for_load_state("networkidle")
                time.sleep(2)

            contexto_cv = extrair_texto_pdf(CV_PDF_PATH)
            if not contexto_cv:
                log("❌ Falha ao carregar currículo. Abortando.")
                return
            log("Currículo carregado.")

            vagas_processadas = carregar_vagas_processadas()
            log(f"Vagas já processadas: {len(vagas_processadas)}")

            # Divide as keywords (separadas por vírgula) e itera sobre cada uma
            keywords = [kw.strip() for kw in SEARCH_KEYWORD.split(",") if kw.strip()]
            if not keywords:
                keywords = ["BI"]  # fallback

            for keyword in keywords:
                log(f"\n{'='*50}\n🔍 BUSCANDO POR: '{keyword}'\n{'='*50}")
                buscar_vagas_por_palavra_chave(page, keyword)
                aplicar_filtros(page)

                # Processa páginas de resultados
                while True:
                    processar_vagas(page, contexto_cv, vagas_processadas, keyword)
                    # Tenta ir para próxima página
                    next_btn = page.locator('nav button[aria-label="Próxima página"]')
                    if next_btn.count() and not next_btn.first.is_disabled():
                        next_btn.first.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                    else:
                        log(f"Fim da paginação para '{keyword}'.")
                        break
            log("✅ Processamento concluído.")
    except KeyboardInterrupt:
        log("Interrompido pelo usuário.")
    except Exception as e:
        log(f"Erro: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()