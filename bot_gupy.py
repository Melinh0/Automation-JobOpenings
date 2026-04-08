from playwright.sync_api import sync_playwright
import time
from bs4 import BeautifulSoup
import requests
import json
import pdfplumber
import re
from datetime import datetime
import traceback
import os
from difflib import SequenceMatcher  
import subprocess   
import psutil
from dotenv import load_dotenv
import os

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# ================= CONFIGURAÇÕES =================
GUPY_SEARCH_URL = os.getenv("GUPY_SEARCH_URL", "https://portal.gupy.io/job-search/sortBy=publishedDate")
KEYWORDS = [kw.strip() for kw in os.getenv("KEYWORDS", "Segurança,Python,dados,Engenheiro de dados,IA,BI,Automação,estagiário backend,cientista,JR,desenvolvedor,analista,backend").split(",")]
CV_PDF_PATH = os.getenv("CV_PDF_PATH", r"c:\Users\yagom\Downloads\Currículo_Vagas(Português).pdf")

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")
OLLAMA_HOST = "https://ollama.com"
OLLAMA_MODELS = [
    "qwen3-coder-next:latest",
    "qwen3-coder-next:cloud",
    "qwen3-coder-next:q4_K_M",
    "qwen3-coder-next:q8_0",
    "qwen3.5:latest",
    "qwen3.5:0.8b",
    "qwen3.5:2b",
    "qwen3.5:4b",
    "qwen3.5:9b",
    "qwen3.5:27b",
    "qwen3.5:35b",
    "qwen3.5:122b",
    "qwen3.5:cloud",
    "qwen3.5:397b-cloud",
    "deepseek-v3.2:cloud",
    "mistral-large-3:675b-cloud",
    "phi4:14b-cloud",
    "gemma4:latest",
    "gemma4:e2b",
    "gemma4:e4b",
    "gemma4:26b",
    "gemma4:31b",
    "minimax-m2.7:cloud",
    "qwen3-vl:latest",
    "qwen3-vl:2b",
    "qwen3-vl:4b",
    "qwen3-vl:8b",
    "qwen3-vl:30b",
    "qwen3-vl:32b",
    "qwen3-vl:235b",
    "qwen3-vl:235b-cloud",
    "qwen3-vl:235b-instruct-cloud",
    "nemotron:70b-cloud",
    "granite3.1-dense:8b-cloud",
    "aya:35b-cloud",
    "falcon3:10b-cloud",
    "exaone:32b-cloud",
    "llama3.2:3b"
]

fallback_count = 0
MAX_FALLBACK = 5

NOME_COMPLETO = os.getenv("NOME_COMPLETO")
NOME_MAE = os.getenv("NOME_MAE")
NOME_PAI = os.getenv("NOME_PAI")
TELEFONE = os.getenv("TELEFONE")
EMAIL = os.getenv("GUPY_EMAIL")
SENHA = os.getenv("GUPY_PASSWORD")
LINKEDIN = os.getenv("LINKEDIN")
GITHUB = os.getenv("GITHUB")
CPF = os.getenv("CPF")
RG = os.getenv("RG")

# ================= FUNÇÃO PARA INICIAR O CHROME COM DEBUG =================
def encontrar_chrome_exe():
    possiveis_caminhos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(os.getenv("USERNAME")),
    ]
    for caminho in possiveis_caminhos:
        if os.path.exists(caminho):
            return caminho
    import shutil
    return shutil.which("chrome") or shutil.which("google-chrome")

def iniciar_chrome_com_debug(porta=9222):
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
    
    user_data_dir = os.path.join(os.environ['TEMP'], 'chrome_gupy_debug')
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
    
    # Aguarda a porta ficar disponível (usando IPv4 explicitamente)
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

def goto_with_retry(page, url, max_retries=3, timeout=60000):
    for attempt in range(max_retries):
        try:
            log(f"Carregando {url} (tentativa {attempt+1}/{max_retries})")
            page.goto(url, timeout=timeout, wait_until='domcontentloaded')
            page.wait_for_load_state('networkidle', timeout=15000)
            return True
        except Exception as e:
            log(f"Erro: {e}")
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 5
                log(f"Aguardando {wait}s antes de nova tentativa...")
                time.sleep(wait)
            else:
                log(f"❌ Falha após {max_retries} tentativas.")
                raise
    return False

# ================= FUNÇÕES DE PERSISTÊNCIA (vagas já candidatadas) =================
ARQUIVO_VAGAS_PROCESSADAS = "json\vagas_processadas.json"

def carregar_vagas_processadas():
    if os.path.exists(ARQUIVO_VAGAS_PROCESSADAS):
        try:
            with open(ARQUIVO_VAGAS_PROCESSADAS, "r", encoding="utf-8") as f:
                dados = json.load(f)
                return set(dados.get("links", []))
        except Exception as e:
            log(f"Erro ao carregar vagas processadas: {e}")
    return set()

def salvar_vagas_processadas(links_set):
    try:
        with open(ARQUIVO_VAGAS_PROCESSADAS, "w", encoding="utf-8") as f:
            json.dump({"links": list(links_set)}, f, indent=2, ensure_ascii=False)
        log(f"💾 {len(links_set)} vagas processadas salvas.")
    except Exception as e:
        log(f"Erro ao salvar vagas processadas: {e}")

# ================= FUNÇÕES DE CONHECIMENTO (RAG) =================
ARQUIVO_CONHECIMENTO = "json\knowledge_base.json"
MAX_VAGAS_NA_BASE = 200  # mantém apenas as últimas 200 vagas

def is_dns_error_page(page):
    """Retorna True se a página atual for uma página de erro DNS (site não encontrado)."""
    try:
        # Verifica pelo título ou pelo conteúdo da página
        if "DNS_PROBE_FINISHED_NXDOMAIN" in page.content():
            return True
        if "Não é possível acessar esse site" in page.content():
            return True
        if "taking-people" in page.url and "inactive" in page.url:
            return True
        return False
    except:
        return False

def tem_erro_no_formulario(page):
    """Verifica se há alguma mensagem de erro visível no formulário."""
    try:
        # Procura por mensagens de erro comuns
        erros = page.locator('.error-message, .Mui-error, .radio-group__error-message, [class*="error"]')
        if erros.count() > 0 and erros.first.is_visible():
            log(f"⚠️ Erro(s) detectado(s) no formulário: {erros.first.inner_text()}")
            return True
        return False
    except:
        return False

def carregar_conhecimento():
    """Carrega a base de conhecimento (lista de vagas com perguntas e respostas)."""
    if os.path.exists(ARQUIVO_CONHECIMENTO):
        try:
            with open(ARQUIVO_CONHECIMENTO, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"Erro ao carregar base de conhecimento: {e}")
    return []  # lista de dicionários

def salvar_conhecimento(conhecimento):
    """Salva a base de conhecimento, mantendo apenas as últimas MAX_VAGAS_NA_BASE entradas."""
    if len(conhecimento) > MAX_VAGAS_NA_BASE:
        conhecimento = conhecimento[-MAX_VAGAS_NA_BASE:]
    try:
        with open(ARQUIVO_CONHECIMENTO, "w", encoding="utf-8") as f:
            json.dump(conhecimento, f, indent=2, ensure_ascii=False)
        log(f"💾 Base de conhecimento atualizada ({len(conhecimento)} vagas).")
    except Exception as e:
        log(f"Erro ao salvar base de conhecimento: {e}")

def similaridade(a, b):
    """Retorna a similaridade entre duas strings (0 a 1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def confirmar_modal_se_existir(page):
    """
    Verifica se há um modal de confirmação (com botão Confirmar) e clica nele.
    Retorna True se clicou, False caso contrário.
    """
    try:
        # Procura por qualquer diálogo visível que contenha um botão Confirmar
        modal = page.locator('div[role="dialog"]:has(button:has-text("Confirmar"))')
        if modal.count() == 0:
            # Fallback: botão Confirmar que não esteja dentro de um formulário comum
            modal = page.locator('button:has-text("Confirmar")').first
            if modal.count() == 0 or not modal.is_visible():
                return False
        
        # Se o modal existe e está visível
        if modal.is_visible():
            log("📢 Modal de confirmação detectado.")
            # Tenta encontrar o botão Confirmar dentro do modal
            btn_confirmar = modal.locator('button:has-text("Confirmar")')
            if btn_confirmar.count() == 0:
                btn_confirmar = page.locator('button:has-text("Confirmar")').first
            
            if btn_confirmar.count() and btn_confirmar.is_visible():
                btn_confirmar.click(force=True)
                log("✅ Confirmado envio das respostas.")
                time.sleep(2)
                # Aguarda o modal desaparecer
                page.wait_for_selector('div[role="dialog"]', state='hidden', timeout=5000)
                return True
        return False
    except Exception as e:
        log(f"Erro ao confirmar modal: {e}")
        return False

def buscar_exemplos_similares(perguntas_atuais, conhecimento, limite=3, limiar=0.4):
    """
    Dada uma lista de perguntas atuais, retorna até `limite` exemplos de perguntas
    anteriores (com suas respostas) que sejam semelhantes a alguma pergunta atual.
    """
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
    # Remove duplicatas (baseado na pergunta) e ordena por similaridade
    unicos = {}
    for ex in exemplos:
        if ex["pergunta_similar"] not in unicos or unicos[ex["pergunta_similar"]]["similaridade"] < ex["similaridade"]:
            unicos[ex["pergunta_similar"]] = ex
    melhores = sorted(unicos.values(), key=lambda x: x["similaridade"], reverse=True)[:limite]
    return melhores

def salvar_conhecimento_vaga(url, titulo, descricao, perguntas_respostas, html_formulario=""):
    conhecimento = carregar_conhecimento()
    conhecimento = [v for v in conhecimento if v.get("url") != url]
    conhecimento.append({
        "url": url,
        "titulo": titulo,
        "descricao": descricao[:3000],
        "data": datetime.now().isoformat(),
        "perguntas": perguntas_respostas,
        "html_formulario": html_formulario[:5000]  # salva o HTML
    })
    salvar_conhecimento(conhecimento)

# ================= FUNÇÕES =================
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

def ir_para_pagina_vagas(page):
    """Navega para a página inicial do Gupy e clica em 'Explorar todas as vagas'."""
    log("🌐 Navegando para a página inicial do Gupy...")
    page.goto("https://portal.gupy.io/")
    page.wait_for_load_state("networkidle", timeout=15000)
    time.sleep(2)

    log("🔍 Procurando link 'Explorar todas as vagas'...")
    explorar_btn = page.locator('a:has-text("Explorar todas as vagas")').first
    if explorar_btn.count() == 0:
        explorar_btn = page.locator('a[href="/job-search/sortBy=publishedDate"]').first

    if explorar_btn.count() and explorar_btn.is_visible():
        explorar_btn.click()
        log("✅ Clicou em 'Explorar todas as vagas'.")
        # Aguarda a URL conter "/job-search" (SPA, sem expect_navigation)
        try:
            page.wait_for_url(lambda url: "/job-search" in url, timeout=15000)
            log("✅ URL confirmada: contém /job-search")
        except:
            log("⚠️ URL não mudou para /job-search, mas continuando...")
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
        return True
    else:
        log("❌ Link 'Explorar todas as vagas' não encontrado.")
        return False

def is_name_not_resolved_error(error):
    """Verifica se o erro é relacionado a DNS/name not resolved."""
    error_msg = str(error).lower()
    return "err_name_not_resolved" in error_msg or "err_name_not_resolved" in error_msg

def extrair_contexto_vaga(page):
    log("Extraindo contexto da vaga...")
    try:
        page.wait_for_selector('[data-testid="text-section"]', timeout=5000)
    except:
        log("⚠️ Seções da vaga não carregaram completamente")
    html = page.content()
    soup = BeautifulSoup(html, 'html.parser')
    secoes = soup.select('[data-testid="text-section"]')
    textos = []
    for secao in secoes:
        titulo = secao.select_one('h2')
        conteudo = secao.get_text(separator=" ", strip=True)
        if titulo:
            textos.append(f"{titulo.get_text(strip=True)}:\n{conteudo}")
        else:
            textos.append(conteudo)
    return "\n\n".join(textos)[:4000]

def clicar_candidatar(page):
    log("Procurando botão 'Candidatar-se'...")
    seletores = [
        '[data-testid="job-cta-link"]',
        '#fixed-applyButton',
        'a:has-text("Candidatar-se")',
        'button:has-text("Candidatar-se")'
    ]
    for sel in seletores:
        try:
            btn = page.locator(sel).first
            if btn.count():
                btn.wait_for(state="visible", timeout=5000)
                btn.click(force=True)
                log(f"Clicou usando seletor: {sel}")
                return True
        except Exception as e:
            log(f"Falha no seletor {sel}: {e}")
    log("Tentando clique via JS...")
    page.evaluate("""
        () => {
            const btn = document.querySelector('[data-testid="job-cta-link"], #fixed-applyButton');
            if (btn) btn.click();
        }
    """)
    time.sleep(2)
    return True

def chamar_ollama_com_fallback(messages, temperature=0.2):
    for idx, modelo in enumerate(OLLAMA_MODELS):
        try:
            log(f"🔄 Tentando modelo [{idx+1}/{len(OLLAMA_MODELS)}]: {modelo}")
            url = f"{OLLAMA_HOST}/api/chat"
            headers = {
                "Authorization": f"Bearer {OLLAMA_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": modelo,
                "messages": messages,
                "stream": False,
                "temperature": temperature
            }
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

def determinar_salario(contexto_cv, contexto_vaga):
    """
    Usa a LLM para calcular a pretensão salarial ideal com base no currículo,
    na vaga e nos salários anteriores do candidato.
    """
    salarios_anteriores = [700, 800, 1400, 2400]
    prompt = f"""
Você é um especialista em negociação salarial. Com base no currículo e na descrição da vaga abaixo, defina uma pretensão salarial justa e competitiva para o candidato.

**Currículo (resumo):**
{contexto_cv[:2000]}

**Descrição da vaga:**
{contexto_vaga[:2000]}

**Salários anteriores do candidato (em R$):** {', '.join(str(s) for s in salarios_anteriores)}

**Regras:**
- Considere o nível da vaga (estágio, Júnior, Pleno, Sênior), localização (remoto, presencial, região), responsabilidades e requisitos.
- Avalie o mercado atual para a função e localização.
- Proponha um valor que seja atrativo para a empresa e justo para o candidato, considerando sua experiência.
- Se for estágio, o valor deve ficar entre R$ 800 e R$ 1.500.
- Se for Júnior, entre R$ 2.000 e R$ 3.500.
- Se for Pleno, entre R$ 4.000 e R$ 7.000.
- Se for Sênior, entre R$ 7.000 e R$ 12.000.
- Responda APENAS com o valor no formato "R$ X.XXX,XX" (ex: R$ 2.500,00).
"""
    resposta = chamar_ollama_com_fallback([{"role": "user", "content": prompt}], temperature=0.3)
    if resposta and re.search(r'R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}', resposta):
        match = re.search(r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})', resposta)
        if match:
            return f"R$ {match.group(1)}"
    # Fallback caso a LLM falhe
    return determinar_salario(contexto_cv, contexto_vaga)  # função antiga

def gerar_resposta_fallback(label, tipo, contexto_cv, contexto_vaga, options=None):
    label_lower = label.lower()
    # Dados pessoais fixos
    if "nome completo" in label_lower:
        return NOME_COMPLETO
    if "nome da sua mãe" in label_lower or "nome da mae" in label_lower:
        return NOME_MAE
    if "nome do pai" in label_lower or "nome do seu pai" in label_lower:
        return NOME_PAI
    if "cpf" in label_lower:
        return CPF
    if "rg" in label_lower:
        return RG
    if "telefone" in label_lower or "celular" in label_lower:
        return TELEFONE
    if "e-mail" in label_lower or "email" in label_lower:
        return EMAIL
    if "linkedin" in label_lower:
        return LINKEDIN
    if "github" in label_lower:
        return GITHUB
    if "pretensão salarial" in label_lower or "salário" in label_lower or "remuneração" in label_lower:
        return determinar_salario(contexto_cv, contexto_vaga)
    
    # Perguntas abertas – respostas sempre positivas e baseadas no currículo
    if "sobre você" in label_lower or "apresente" in label_lower or "apresentação" in label_lower:
        return f"Me chamo {NOME_COMPLETO}. Tenho sólida experiência em desenvolvimento Python, análise de dados com Power BI e automação de processos, conforme detalhado no meu currículo. Sou proativo, aprendo rápido e busco aplicar minhas habilidades para gerar resultados significativos."
    if "por que quer trabalhar" in label_lower or "motivação" in label_lower:
        return "Admiro a inovação e o crescimento da empresa. Meu currículo demonstra que estou sempre buscando desafios e aprendizado contínuo, e acredito que posso contribuir com soluções criativas e eficiência operacional."
    if "expectativa salarial" in label_lower:
        return determinar_salario(contexto_cv, contexto_vaga)
    if "disponibilidade" in label_lower:
        return "Imediata"
    if "estado" in label_lower or "uf" in label_lower:
        return "Ceará"
    if "cidade" in label_lower:
        return "Fortaleza"
    
    # TRATAMENTO ESPECÍFICO PARA ÚLTIMA REMUNERAÇÃO
    if "última remuneração" in label_lower or "ultima remuneracao" in label_lower or "salário anterior" in label_lower or "ultimo salario" in label_lower:
        # Histórico real do candidato
        salarios = [700, 800, 1400, 2400]
        ultimo_salario = max(salarios)
        return f"Minha última remuneração foi de R$ {ultimo_salario},00, atuando como profissional de tecnologia. Atualmente estou em projeto acadêmico no LARCES/UECE, onde continuo desenvolvendo habilidades em IA, automação e cibersegurança, sempre buscando evolução profissional."
    
    # Para selects, radios, checkboxes – primeira opção válida
    if tipo == "select" and options:
        return options[0]
    if tipo == "radio" and options:
        return options[0]["value"] if isinstance(options[0], dict) else options[0]
    if tipo == "checkbox":
        return "true"
    
    # Qualquer outro campo – resposta genérica positiva
    return "Minhas experiências e habilidades descritas no currículo me tornam um excelente candidato para esta posição."

# MELHORIA: extração de info do currículo com frases sempre positivas e sem "não tenho"
def extrair_info_curriculo(contexto_cv):
    info = {
        "curso": "",
        "instituicao": "",
        "periodo": "",
        "experiencia_ia": "",
        "experiencia_automacao": "",
        "experiencia_nocode": "",
        "projetos_processos": ""
    }
    cv_lower = contexto_cv.lower()
    
    if "engenharia" in cv_lower:
        info["curso"] = "Engenharia de Software"
    elif "ciência da computação" in cv_lower:
        info["curso"] = "Ciência da Computação"
    elif "sistemas de informação" in cv_lower:
        info["curso"] = "Sistemas de Informação"
    else:
        info["curso"] = "Tecnologia da Informação"
    
    if "ufc" in cv_lower or "universidade federal" in cv_lower:
        info["instituicao"] = "UFC"
    elif "uece" in cv_lower:
        info["instituicao"] = "UECE"
    elif "ifce" in cv_lower:
        info["instituicao"] = "IFCE"
    else:
        info["instituicao"] = "Instituição de ensino superior"
    
    match = re.search(r'(\d+)[º°]?\s*período', cv_lower)
    if match:
        periodo = int(match.group(1))
        if periodo <= 2:
            info["periodo"] = "1º ou 2º período."
        elif periodo <= 4:
            info["periodo"] = "3º ou 4º período."
        elif periodo <= 6:
            info["periodo"] = "5º ou 6º período."
        else:
            info["periodo"] = "7º ou 8º período."
    else:
        info["periodo"] = "Entre o 3º e 6º período (cursando)."
    
    # Sempre respostas positivas
    if "inteligência artificial" in cv_lower or "machine learning" in cv_lower or "ia" in cv_lower:
        info["experiencia_ia"] = "Possuo conhecimento prático em IA, com projetos acadêmicos aplicados."
    else:
        info["experiencia_ia"] = "Estou constantemente me atualizando em IA e aplico conceitos em meus projetos."
    
    if "automação" in cv_lower or "automacao" in cv_lower or "rpa" in cv_lower:
        info["experiencia_automacao"] = "Experiência comprovada em automação com Python, otimizando processos."
    else:
        info["experiencia_automacao"] = "Tenho familiaridade com automação de tarefas e utilizo scripts para ganho de eficiência."
    
    if "no-code" in cv_lower or "nocode" in cv_lower or "bubble" in cv_lower or "make" in cv_lower:
        info["experiencia_nocode"] = "Já utilizei ferramentas no-code para prototipagem rápida e soluções ágeis."
    else:
        info["experiencia_nocode"] = "Possuo conhecimento em plataformas no-code e estou apto a aprender novas ferramentas rapidamente."
    
    if "mapeamento" in cv_lower or "melhoria de processos" in cv_lower or "bpm" in cv_lower:
        info["projetos_processos"] = "Sim, realizei projetos práticos de mapeamento e melhoria de processos."
    else:
        info["projetos_processos"] = "Tenho noções de modelagem de processos e aplico essa visão em meus projetos."
    
    return info

def preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, url_vaga=None):
    """
    Preenche o formulário e retorna a lista de perguntas e respostas utilizadas.
    Retorna: lista de dicts [{"pergunta": str, "resposta": str, "tipo": str, "opcoes": list}]
    """
    log("Extraindo estrutura do formulário (modo robusto)...")
    
    try:
        page.wait_for_selector('fieldset, input, textarea, select', timeout=10000)
        time.sleep(1)
    except:
        log("⚠️ Nenhum elemento de formulário encontrado após espera.")
    
    campos_simples = []
    radio_groups = []
    checkbox_groups = []

    # ---------- RADIOS ----------
    radio_fieldsets = page.locator('fieldset:has(input[type="radio"])').all()
    for fs in radio_fieldsets:
        try:
            pergunta_elem = fs.locator('label.radio-group__label, legend, .radio-group__label').first
            pergunta = pergunta_elem.inner_text().strip() if pergunta_elem.count() else "Pergunta sem título"
            opcoes = []
            radios = fs.locator('input[type="radio"]').all()
            for radio in radios:
                texto_opcao = ""
                parent_label = radio.locator('xpath=ancestor::label')
                if parent_label.count():
                    texto_opcao = parent_label.first.inner_text().strip()
                else:
                    span = radio.locator('xpath=following-sibling::span[1]')
                    if span.count():
                        texto_opcao = span.first.inner_text().strip()
                    else:
                        texto_opcao = radio.get_attribute("value") or "opção"
                if texto_opcao:
                    opcoes.append({
                        "texto": texto_opcao,
                        "elemento": radio,
                        "label": parent_label.first if parent_label.count() else None
                    })
            if opcoes:
                radio_groups.append({
                    "pergunta": pergunta,
                    "opcoes": opcoes
                })
                log(f"   - Radio detectado: '{pergunta}' com {len(opcoes)} opções")
        except Exception as e:
            log(f"Erro ao processar fieldset de radio: {e}")

    # ---------- CHECKBOXES ----------
    checkbox_fieldsets = page.locator('fieldset:has(input[type="checkbox"])').all()
    for fs in checkbox_fieldsets:
        try:
            legend = fs.locator('legend').first
            pergunta = legend.inner_text().strip() if legend.count() else "Checkbox sem título"
            opcoes = []
            checkboxes = fs.locator('input[type="checkbox"]').all()
            for cb in checkboxes:
                texto_opcao = ""
                cb_id = cb.get_attribute("id")
                if cb_id:
                    label_by_for = page.locator(f'label[for="{cb_id}"]').first
                    if label_by_for.count():
                        texto_opcao = label_by_for.inner_text().strip()
                if not texto_opcao:
                    parent_label = cb.locator('xpath=ancestor::label')
                    if parent_label.count():
                        texto_opcao = parent_label.first.inner_text().strip()
                if not texto_opcao:
                    span = cb.locator('xpath=following-sibling::span[1]')
                    if span.count():
                        texto_opcao = span.first.inner_text().strip()
                if not texto_opcao:
                    texto_opcao = cb.get_attribute("value") or "opção"
                if texto_opcao:
                    opcoes.append({
                        "texto": texto_opcao,
                        "elemento": cb,
                        "label": page.locator(f'label[for="{cb_id}"]').first if cb_id else None
                    })
            if opcoes:
                checkbox_groups.append({
                    "pergunta": pergunta,
                    "opcoes": opcoes
                })
                log(f"   - Checkbox detectado: '{pergunta}' com {len(opcoes)} opções")
        except Exception as e:
            log(f"Erro ao processar fieldset de checkbox: {e}")

    # ---------- CAMPOS SIMPLES (input, textarea, select) ----------
    elementos = page.locator('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]):not([type="file"]), textarea, select').all()
    for elem in elementos:
        try:
            if elem.get_attribute("disabled") or elem.get_attribute("readonly"):
                continue
            if not elem.is_visible():
                continue
            label = ""
            elem_id = elem.get_attribute("id")
            if elem_id:
                label_elem = page.locator(f'label[for="{elem_id}"]').first
                if label_elem.count():
                    label = label_elem.inner_text().strip()
            if not label:
                aria_label = elem.get_attribute("aria-label")
                if aria_label:
                    label = aria_label.strip()
            if not label:
                placeholder = elem.get_attribute("placeholder")
                if placeholder:
                    label = placeholder.strip()
            if not label:
                parent_div = elem.locator('xpath=../preceding-sibling::div[1]').first
                if parent_div.count():
                    label = parent_div.inner_text().strip()
            if not label:
                label = "Campo sem rótulo"
            tipo = elem.get_attribute("type")
            if not tipo:
                tag = elem.evaluate("el => el.tagName.toLowerCase()")
                if tag == "textarea":
                    tipo = "textarea"
                elif tag == "select":
                    tipo = "select"
                else:
                    tipo = "text"
            options = []
            if tipo == "select":
                options = elem.evaluate("el => Array.from(el.options).map(opt => opt.text)")
            campos_simples.append({
                "element": elem,
                "label": label,
                "type": tipo,
                "options": options
            })
        except Exception as e:
            log(f"Erro ao analisar campo simples: {e}")

    if not campos_simples and not radio_groups and not checkbox_groups:
        log("❌ Nenhum campo editável encontrado.")
        return [], ""

    log(f"✅ {len(campos_simples)} campos simples, {len(radio_groups)} radios, {len(checkbox_groups)} checkboxes.")

    info_curriculo = extrair_info_curriculo(contexto_cv)

    # ========== PREPARAR PROMPT E CHAMAR LLM ==========
    todas_perguntas = []
    for c in campos_simples:
        todas_perguntas.append(c["label"])
    for rg in radio_groups:
        todas_perguntas.append(rg["pergunta"])
    for cg in checkbox_groups:
        todas_perguntas.append(cg["pergunta"])

    conhecimento = carregar_conhecimento()
    exemplos = buscar_exemplos_similares(todas_perguntas, conhecimento, limite=3, limiar=0.4)

    texto_exemplos = ""
    if exemplos:
        texto_exemplos = "\n\n📚 **EXEMPLOS DE RESPOSTAS ANTERIORES QUE DERAM CERTO:**\n"
        for i, ex in enumerate(exemplos, 1):
            texto_exemplos += f"{i}. Pergunta similar: \"{ex['pergunta_similar']}\"\n   Resposta usada: \"{ex['resposta_usada']}\"\n"
        log(f"📚 Encontrados {len(exemplos)} exemplos similares na base de conhecimento.")
    else:
        log("📚 Nenhum exemplo similar encontrado na base de conhecimento.")

    # Montar prompt para LLM (incluindo exemplos)
    prompt_campos = []
    for c in campos_simples:
        prompt_campos.append({
            "label": c["label"],
            "type": c["type"],
            "options": c["options"][:5] if c["options"] else []
        })
    for rg in radio_groups:
        prompt_campos.append({
            "label": rg["pergunta"],
            "type": "radio-group",
            "options": [opt["texto"] for opt in rg["opcoes"]]
        })
    for cg in checkbox_groups:
        prompt_campos.append({
            "label": cg["pergunta"],
            "type": "checkbox-group",
            "options": [opt["texto"] for opt in cg["opcoes"]]
        })

    system_prompt = f"""
Você é um assistente de candidatura especializado. Responda cada campo com base APENAS no currículo e na vaga fornecidos.

📄 CURRÍCULO COMPLETO:
{contexto_cv[:3000]}

📊 INFORMAÇÕES EXTRAÍDAS DO CURRÍCULO:
- Curso: {info_curriculo['curso']}
- Instituição: {info_curriculo['instituicao']}
- Período estimado: {info_curriculo['periodo']}
- Experiência em IA: {info_curriculo['experiencia_ia']}
- Experiência em Automação: {info_curriculo['experiencia_automacao']}
- Experiência em No-code: {info_curriculo['experiencia_nocode']}
- Projetos de processos: {info_curriculo['projetos_processos']}

🏢 DESCRIÇÃO DA VAGA:
{contexto_vaga[:3000]}

{texto_exemplos}

📋 CAMPOS DO FORMULÁRIO:
{json.dumps(prompt_campos, indent=2, ensure_ascii=False)}

**REGRAS OBRIGATÓRIAS (NUNCA VIOLAR):**
1. NUNCA use palavras ou frases como: "não tenho", "não sei", "não informado", "nenhuma", "vazio", "sem experiência". 
2. Sempre valorize seu currículo. Se a pergunta for sobre algo que você não tem experiência direta, responda destacando seu aprendizado rápido, familiaridade com a área ou projetos relacionados.
3. Para campos de texto livre, escreva respostas elaboradas (mínimo 2 frases) mostrando entusiasmo e alinhamento com a vaga, citando habilidades reais do currículo.
4. Para "radio-group" e "checkbox-group", escolha APENAS opções da lista "options". Retorne o TEXTO EXATO.
5. Para "pretensão salarial": use estágio=1200, jr=2000, pleno=3500, senior=5000.
6. Para dados pessoais fixos: nome completo = {NOME_COMPLETO}, mãe = {NOME_MAE}, pai = {NOME_PAI}, CPF = {CPF}, RG = {RG}, telefone = {TELEFONE}, email = {EMAIL}, LinkedIn = {LINKEDIN}, GitHub = {GITHUB}.
7. Use as informações extraídas do currículo sempre que possível. Se faltar algum dado, deduza de forma positiva e razoável.
8. Inspire-se nos exemplos fornecidos, mas adapte ao contexto atual.
9. Para perguntas sobre "última remuneração" ou "salário anterior", NUNCA responda "não informado", "estágio/projeto acadêmico" sem valor numérico. Use o maior salário do histórico do candidato (R$ 2.400) como referência e contextualize de forma positiva.

FORMATO DE RESPOSTA (APENAS JSON, sem texto extra):
[
  {{"label": "1. Está matriculado em curso de nível superior? *", "value": "Sim"}},
  {{"label": "2. Possui experiência com Python?", "value": "Sim"}},
  {{"label": "3. Certificações que possui (selecione todas que se aplicam):", "value": ["ITIL 4 Foundation", "Python avançado"]}}
]
"""
    resposta_llm = chamar_ollama_com_fallback([
        {"role": "user", "content": system_prompt}
    ], temperature=0.3)

    acoes = []
    if resposta_llm and resposta_llm.startswith("["):
        try:
            clean = re.sub(r"```json|```", "", resposta_llm).strip()
            acoes = json.loads(clean)
            log("✅ LLM retornou respostas personalizadas.")
            for acao in acoes:
                if "value" in acao and isinstance(acao["value"], str):
                    valor = acao["value"].lower()
                    if any(neg in valor for neg in ["não tenho", "não sei", "não informado", "nenhuma", "vazio", "sem experiência"]):
                        log(f"⚠️ Resposta negativa detectada: {acao['value']}. Substituindo por fallback positivo.")
                        acao["value"] = gerar_resposta_fallback(acao["label"], "text", contexto_cv, contexto_vaga)
        except:
            log("⚠️ Resposta da LLM não é JSON válido. Usando fallback.")
            acoes = []

    # ========== PREENCHER CAMPOS ==========
    perguntas_respostas = []

    # 1. Campos simples
    for campo in campos_simples:
        label = campo["label"]
        tipo = campo["type"]
        elem = campo["element"]
        valor = None
        for acao in acoes:
            if acao.get("label", "").strip() == label:
                valor = acao.get("value")
                break
        if valor is None:
            valor = gerar_resposta_fallback(label, tipo, contexto_cv, contexto_vaga, campo["options"])
        try:
            if tipo == "select":
                if valor in campo["options"]:
                    elem.select_option(label=valor)
                else:
                    elem.select_option(index=0)
                log(f"✅ Select '{label}' -> '{valor}'")
            else:
                elem.fill(str(valor))
                log(f"✅ Campo '{label}' preenchido")
            perguntas_respostas.append({
                "pergunta": label,
                "resposta": str(valor),
                "tipo": tipo,
                "opcoes": campo["options"]
            })
        except Exception as e:
            log(f"❌ Erro ao preencher '{label}': {e}")

    # 2. Radios
    for rg in radio_groups:
        pergunta = rg["pergunta"]
        opcoes = rg["opcoes"]
        valor = None
        for acao in acoes:
            if acao.get("label", "").strip() == pergunta:
                valor = acao.get("value")
                break
        if not valor:
            pergunta_lower = pergunta.lower()
            textos_opcoes = [opt["texto"] for opt in opcoes]
            if "matriculado em curso de nível superior" in pergunta_lower:
                valor = "Sim" if "Sim" in textos_opcoes else textos_opcoes[0]
            elif "instituição de ensino é" in pergunta_lower:
                if "ufc" in contexto_cv.lower() or "universidade federal" in contexto_cv.lower():
                    valor = "Pública" if "Pública" in textos_opcoes else textos_opcoes[0]
                else:
                    valor = "Privada" if "Privada" in textos_opcoes else textos_opcoes[0]
            elif "qual período" in pergunta_lower:
                valor = info_curriculo["periodo"]
            elif "inteligência artificial" in pergunta_lower:
                valor = info_curriculo["experiencia_ia"]
            elif "automação de processos" in pergunta_lower:
                valor = info_curriculo["experiencia_automacao"]
            elif "plataformas no-code" in pergunta_lower:
                valor = info_curriculo["experiencia_nocode"]
            elif "projetos acadêmicos ou práticos de mapeamento" in pergunta_lower:
                valor = "Sim" if "Sim" in info_curriculo["projetos_processos"] else "Tenho conhecimento na área"
            else:
                valor = opcoes[0]["texto"]
            log(f"⚠️ Fallback para radio '{pergunta}': '{valor}'")
        escolhida = None
        for opt in opcoes:
            if opt["texto"].strip().lower() == valor.strip().lower():
                escolhida = opt
                break
        if escolhida:
            try:
                if escolhida["label"] and escolhida["label"].count():
                    escolhida["label"].click(force=True)
                else:
                    escolhida["elemento"].check(force=True)
                log(f"✅ Radio '{pergunta}' -> '{escolhida['texto']}'")
                perguntas_respostas.append({
                    "pergunta": pergunta,
                    "resposta": escolhida["texto"],
                    "tipo": "radio",
                    "opcoes": [opt["texto"] for opt in opcoes]
                })
            except Exception as e:
                log(f"❌ Erro ao marcar radio '{pergunta}': {e}")
        else:
            log(f"⚠️ Opção '{valor}' não encontrada. Usando primeira opção.")
            try:
                if opcoes[0]["label"] and opcoes[0]["label"].count():
                    opcoes[0]["label"].click(force=True)
                else:
                    opcoes[0]["elemento"].check(force=True)
                log(f"✅ Radio '{pergunta}' -> '{opcoes[0]['texto']}' (fallback)")
                perguntas_respostas.append({
                    "pergunta": pergunta,
                    "resposta": opcoes[0]["texto"],
                    "tipo": "radio",
                    "opcoes": [opt["texto"] for opt in opcoes]
                })
            except:
                pass

    # 3. Checkboxes
    for cg in checkbox_groups:
        pergunta = cg["pergunta"]
        opcoes = cg["opcoes"]
        valores = []
        for acao in acoes:
            if acao.get("label", "").strip() == pergunta:
                valores = acao.get("value", [])
                if isinstance(valores, str):
                    valores = [valores]
                break
        if not valores:
            # Fallback: tenta "Nenhum(a) acima" ou primeira opção
            opcao_nenhuma = None
            for opt in opcoes:
                texto_lower = opt["texto"].lower()
                if "nenhum" in texto_lower or "nenhuma" in texto_lower:
                    opcao_nenhuma = opt
                    break
            if opcao_nenhuma:
                valores = [opcao_nenhuma["texto"]]
                log(f"⚠️ Fallback para checkbox '{pergunta}': marcando '{opcao_nenhuma['texto']}'")
            else:
                valores = [opcoes[0]["texto"]]
                log(f"⚠️ Fallback para checkbox '{pergunta}': marcando primeira opção '{opcoes[0]['texto']}'")
        respostas_marcadas = []
        for opt in opcoes:
            deve_marcar = opt["texto"] in valores
            try:
                if deve_marcar:
                    if opt["label"] and opt["label"].count():
                        opt["label"].click(force=True)
                    else:
                        opt["elemento"].check(force=True)
                    log(f"✅ Checkbox '{pergunta}' -> '{opt['texto']}' marcado")
                    respostas_marcadas.append(opt["texto"])
                else:
                    if opt["elemento"].is_checked():
                        opt["elemento"].uncheck(force=True)
            except Exception as e:
                log(f"❌ Erro ao processar checkbox '{opt['texto']}': {e}")
        if respostas_marcadas:
            perguntas_respostas.append({
                "pergunta": pergunta,
                "resposta": ", ".join(respostas_marcadas),
                "tipo": "checkbox",
                "opcoes": [opt["texto"] for opt in opcoes]
            })
        time.sleep(0.5)

    # Captura o HTML do formulário (apenas para salvar na base de conhecimento)
    html_formulario = ""
    try:
        form_container = page.locator('form, .MuiPaper-root, [role="dialog"], .sc-eldPxv, .sc-koXPp').first
        if form_container.count():
            html_formulario = form_container.inner_html()[:5000]
    except:
        pass

    time.sleep(1)
    return perguntas_respostas, html_formulario

def buscar_vagas_por_palavra_chave(page, palavra_chave):
    """Busca por palavra-chave abrindo o drawer de busca de forma confiável."""
    log(f"Buscando por: {palavra_chave}")

    # Verifica login e reloga se necessário
    verificar_e_relogar_se_necessario(page)

    # Fecha qualquer drawer aberto
    close_btn = page.locator('button[aria-label="Fechar o menu lateral"]')
    if close_btn.count() and close_btn.is_visible():
        close_btn.click()
        time.sleep(0.5)

    # Abre o drawer de busca
    search_btn = page.locator('button[data-testid="search-button"]')
    if search_btn.count() == 0:
        search_btn = page.locator('button[aria-label="Buscar"]')
    if search_btn.count() and search_btn.is_visible():
        search_btn.click()
        log("Botão de busca clicado.")
        time.sleep(1)
    else:
        log("❌ Botão de busca não encontrado.")
        return

    try:
        page.wait_for_selector('#search-drawer[aria-hidden="false"]', timeout=5000)
        log("Drawer de busca aberto.")
    except:
        log("⚠️ Drawer não abriu normalmente. Tentando continuar...")

    search_input = page.locator('#search-drawer input[name="searchTerm"]')
    try:
        search_input.wait_for(state="visible", timeout=10000)
    except:
        log("⚠️ Campo de busca não ficou visível. Tentando recarregar a página...")
        page.reload()
        time.sleep(3)
        if search_btn.count() and search_btn.is_visible():
            search_btn.click()
            time.sleep(1)
        page.wait_for_selector('#search-drawer[aria-hidden="false"]', timeout=5000)
        search_input = page.locator('#search-drawer input[name="searchTerm"]')
        search_input.wait_for(state="visible", timeout=10000)

    search_input.fill('')
    time.sleep(0.3)
    search_input.fill(palavra_chave)
    log(f"Termo '{palavra_chave}' inserido.")

    submit_btn = page.locator('#search-drawer button[aria-label="Buscar vaga"]')
    if submit_btn.count() == 0:
        submit_btn = page.locator('#search-drawer form button').first
    if submit_btn.count() and submit_btn.is_visible():
        submit_btn.click()
    else:
        search_input.press('Enter')

    log("Busca submetida. Aguardando resultados...")
    time.sleep(3)
    page.wait_for_load_state("networkidle", timeout=10000)
    
def is_logged_in(page):
    """Retorna True se o usuário estiver logado (mais robusto)."""
    try:
        # 1. Se o botão "Entrar" estiver visível, NÃO está logado
        entrar_btn = page.locator('button[data-testid="header-login-button"], #button-login, .button-login')
        if entrar_btn.count() > 0 and entrar_btn.first.is_visible():
            return False

        # 2. Se o avatar/menu do usuário estiver presente (desktop ou mobile), está logado
        menu_icon = page.locator('[data-testid="menu-avatar-desktop"], [data-testid="menu-avatar-mobile"]').first
        if menu_icon.count() and menu_icon.is_visible():
            aria_label = menu_icon.get_attribute("aria-label") or ""
            # Se o aria-label contém "logado" ou não contém "deslogado", considera logado
            if "logado" in aria_label or "deslogado" not in aria_label:
                return True

        # 3. Tenta detectar o avatar do usuário (imagem)
        avatar = page.locator('[data-testid="menu-avatar"] img, [data-testid="avatar"]')
        if avatar.count() > 0 and avatar.first.is_visible():
            return True

        # 4. Na página de vaga, se o botão "Candidatar-se" está visível, geralmente significa que está logado
        #    (pois o Gupy redireciona para login se não estiver)
        candidatar_btn = page.locator('[data-testid="job-cta-link"], #fixed-applyButton, a:has-text("Candidatar-se")').first
        if candidatar_btn.count() and candidatar_btn.is_visible():
            return True

        # 5. Se a URL é de busca de vagas e não há botão "Entrar", assume logado
        if "job-search" in page.url and not entrar_btn.count():
            return True

        # 6. Verifica se há um cookie de sessão (opcional, mas útil)
        cookies = page.context.cookies()
        for cookie in cookies:
            if "session" in cookie["name"].lower() or "token" in cookie["name"].lower():
                return True

        return False
    except:
        return False

def is_login_page(page):
    """Retorna True se a página atual for a tela de login do Gupy."""
    try:
        if "signin" in page.url.lower():
            return True
        if page.locator('#username').count() and page.locator('#button-signin').count():
            return True
        if "Entrar com sua conta" in page.content():
            return True
        return False
    except:
        return False

def aplicar_filtros(page):
    log("Aplicando filtros...")
    filtrar_btn = page.locator('button:has-text("Filtrar")').first
    if filtrar_btn.count():
        filtrar_btn.click()
        log("Botão 'Filtrar' clicado.")
        try:
            page.wait_for_selector('div.MuiDrawer-root h2:has-text("Filtrar")', timeout=8000)
            log("Modal de filtros aberto.")
        except:
            log("⚠️ Modal de filtros não detectado pelo título. Tentando prosseguir mesmo assim.")
        time.sleep(1)
    else:
        log("Botão 'Filtrar' não encontrado.")
        return

    try:
        radio_mais_recentes = page.locator('input[name="sortBy"][value=""]')
        if radio_mais_recentes.count() and not radio_mais_recentes.first.is_checked():
            radio_mais_recentes.first.click()
            log("Selecionado 'Mais recentes'")
        else:
            log("'Mais recentes' já está selecionado.")
    except Exception as e:
        log(f"Erro ao selecionar ordenação: {e}")

    try:
        remote_cb = page.locator('input[name="remote"]')
        if remote_cb.count() and not remote_cb.first.is_checked():
            remote_cb.first.click()
            log("Selecionado 'Remoto'")
        hybrid_cb = page.locator('input[name="hybrid"]')
        if hybrid_cb.count() and not hybrid_cb.first.is_checked():
            hybrid_cb.first.click()
            log("Selecionado 'Híbrido'")
    except Exception as e:
        log(f"Erro ao marcar modelo de trabalho: {e}")

    try:
        combobox = page.locator('div[role="combobox"]').filter(has_text="tipo de vaga").first
        if combobox.count() == 0:
            combobox = page.locator('[id^="select-ds"]').first
        if combobox.count():
            combobox.click()
            log("Combobox de tipos de vaga aberto.")
            page.wait_for_selector('ul[role="listbox"]', timeout=5000)
            time.sleep(0.5)
            selecionar_todos = page.locator('li:has-text("Selecionar todos")')
            if selecionar_todos.count():
                cb_todos = selecionar_todos.locator('input[type="checkbox"]')
                if cb_todos.count():
                    cb_todos.first.click()
                else:
                    selecionar_todos.first.click()
                log("✅ Marcado 'Selecionar todos' para tipos de vaga")
            else:
                checkboxes = page.locator('ul[role="listbox"] input[type="checkbox"]').all()
                for cb in checkboxes:
                    if not cb.is_checked():
                        cb.click()
                log(f"✅ Selecionados {len(checkboxes)} tipos de vaga manualmente.")
            page.keyboard.press("Escape")
            time.sleep(0.5)
        else:
            log("⚠️ Combobox de tipos de vaga não encontrado. Pulando...")
    except Exception as e:
        log(f"Erro ao selecionar tipos de vaga: {e}")

    try:
        aplicar = page.locator('div.MuiDrawer-root button:has-text("Filtrar")').last
        if aplicar.count() == 0:
            aplicar = page.locator('button:has-text("Filtrar")').last
        aplicar.click()
        log("Filtros aplicados.")
        time.sleep(3)
    except Exception as e:
        log(f"Erro ao clicar em aplicar filtros: {e}")

def extrair_info_vaga(card_html):
    soup = BeautifulSoup(card_html, 'html.parser')
    tipo = "Não informado"
    modelo = "Não informado"
    local = "Não informado"
    badges = soup.select('.sc-23336bc7-2')
    for badge in badges:
        texto = badge.get_text(strip=True)
        if "Efetivo" in texto or "Estágio" in texto or "PJ" in texto or "Terceiro" in texto:
            tipo = texto
        elif "Remoto" in texto:
            modelo = "Remoto"
        elif "Híbrido" in texto:
            modelo = "Híbrido"
        elif "Presencial" in texto:
            modelo = "Presencial"
        location_span = badge.select_one('[data-testid="job-location"]')
        if location_span:
            local = location_span.get_text(strip=True)
    return tipo, modelo, local

def priorizar_vaga(tipo, modelo, local):
    if modelo == "Remoto":
        if "Estágio" in tipo:
            return 1
        elif "Efetivo" in tipo:
            return 2
        elif "PJ" in tipo:
            return 3
        elif "Terceiro" in tipo:
            return 4
        else:
            return 6
    elif modelo == "Híbrido" and "Fortaleza" in local:
        return 5
    else:
        return 99

def aceitar_cookies(page):
    try:
        seletores = [
            '#dm876A',
            'button:has-text("Accept Cookies")',
            'button:has-text("Accept")',
            'button:has-text("Aceitar")',
            '.cc-btn.cc-dismiss',
            'button.cc-dismiss',
            'div[aria-label="cookieconsent"] button.cc-dismiss',
            'button:has-text("Aceitar cookies")'
        ]
        for sel in seletores:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(force=True, timeout=3000)
                log(f"🍪 Cookies aceitos via seletor: {sel}")
                return True
        return False
    except Exception as e:
        log(f"⚠️ Erro ao tentar aceitar cookies: {e}")
        return False

def confirmar_perguntas_eliminatorias(page):
    """Verifica se o modal de revisão de perguntas eliminatórias está aberto e clica em Confirmar."""
    try:
        # Detecta o modal pelo ID ou pelo título
        modal = page.locator('#eliminatory-questions-modal')
        if modal.count() == 0:
            # Tenta por texto alternativo
            modal = page.locator('div[role="dialog"]:has-text("Revisão das perguntas eliminatórias")')
        if modal.count() == 0:
            return False
        
        log("📋 Modal de revisão de perguntas eliminatórias detectado.")
        # Aguarda um pouco para garantir que está tudo carregado
        time.sleep(1)
        
        # Procura o botão Confirmar (pode ser o único com texto "Confirmar" dentro do modal)
        btn_confirmar = modal.locator('button:has-text("Confirmar")')
        if btn_confirmar.count() == 0:
            # Tenta fora do modal (fallback)
            btn_confirmar = page.locator('button:has-text("Confirmar")')
        
        if btn_confirmar.count() and btn_confirmar.is_visible():
            btn_confirmar.click(force=True)
            log("✅ Confirmado envio das respostas eliminatórias.")
            time.sleep(2)
            # Aguarda o modal fechar
            page.wait_for_selector('#eliminatory-questions-modal', state='hidden', timeout=5000)
            return True
        else:
            log("⚠️ Botão Confirmar não encontrado no modal.")
            return False
    except Exception as e:
        log(f"Erro ao confirmar perguntas eliminatórias: {e}")
        return False

def personalizar_candidatura(page, contexto_cv, contexto_vaga):
    log("🎯 Iniciando personalização da candidatura...")
    try:
        page.wait_for_selector('button#dialog-save-personalization-step', timeout=8000)
        time.sleep(1)
    except:
        log("⚠️ Botão 'Personalizar candidatura' não encontrado. Tentando finalizar diretamente.")
        finalizar = page.locator('button:has-text("Finalizar candidatura")')
        if finalizar.count():
            finalizar.first.click()
            log("🎉 Candidatura finalizada!")
            return True
        return False

    personalizar_btn = page.locator('button#dialog-save-personalization-step')
    if personalizar_btn.count():
        personalizar_btn.first.click()
        log("✅ Clicou em 'Personalizar candidatura'")
        time.sleep(3)
    else:
        log("❌ Botão 'Personalizar candidatura' não encontrado")
        return False

    log("Preenchendo apresentação pessoal...")
    textarea = page.locator('textarea#personalization-step-text-area')
    if textarea.count():
        prompt_apresentacao = f"""
Com base no currículo abaixo e na descrição da vaga, escreva uma breve apresentação pessoal (máx 500 caracteres) destacando as habilidades mais relevantes para a vaga. Seja específico e mostre entusiasmo.

Currículo:
{contexto_cv[:1500]}

Vaga:
{contexto_vaga[:1500]}

Responda apenas com o texto da apresentação, sem explicações adicionais.
"""
        resposta = chamar_ollama_com_fallback([
            {"role": "user", "content": prompt_apresentacao}
        ], temperature=0.5)
        if resposta and len(resposta.strip()) > 20:
            apresentacao = resposta.strip()[:1500]
        else:
            apresentacao = f"Me chamo {NOME_COMPLETO}. Tenho experiência em desenvolvimento Python, análise de dados com Power BI e automação de processos. Busco aplicar esses conhecimentos para gerar valor na empresa e crescer profissionalmente."
        textarea.fill(apresentacao)
        log("✅ Apresentação preenchida")
    else:
        log("⚠️ Textarea de apresentação não encontrado")

    log("Selecionando habilidades relevantes...")
    skills = page.locator('[data-testid="candidate-skill"]')
    count = skills.count()
    if count:
        skill_names = []
        for i in range(count):
            name = skills.nth(i).locator('.sc-hmdomO').inner_text()
            skill_names.append((i, name))
        keywords = re.findall(r'\b\w+\b', contexto_vaga.lower())
        relevant_indices = []
        for idx, name in skill_names:
            name_lower = name.lower()
            score = sum(1 for kw in keywords if kw in name_lower)
            relevant_indices.append((score, idx))
        relevant_indices.sort(reverse=True)
        selected = relevant_indices[:3]
        for _, idx in selected:
            skills.nth(idx).click()
            log(f"✅ Habilidade selecionada: {skill_names[idx][1]}")
        time.sleep(1)
    else:
        log("⚠️ Nenhum botão de habilidade encontrado")

    finalizar = page.locator('button:has-text("Finalizar candidatura")')
    if finalizar.count():
        finalizar.first.click()
        log("🎉 Candidatura finalizada com sucesso!")
        return True
    else:
        log("❌ Botão 'Finalizar candidatura' não encontrado")
        return False

def pagina_nao_encontrada(page):
    """Verifica se a página atual é um erro 404 (página não encontrada)."""
    try:
        # Verifica pela imagem 404 ou pelo texto
        img_404 = page.locator('img[alt*="página não encontrada"], img[alt*="page not found"]')
        if img_404.count() and img_404.is_visible():
            return True
        texto_404 = page.locator('h1:has-text("Não encontramos a página")')
        if texto_404.count() and texto_404.is_visible():
            return True
        # Verifica se a URL contém "404" ou se o título da página indica erro
        if "404" in page.url or "not-found" in page.url:
            return True
        return False
    except:
        return False

def aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_atual, titulo_vaga=""):
    global fallback_count
    log("Iniciando candidatura...")

    # Verifica se a página é de erro DNS
    if is_dns_error_page(page):
        log(f"⚠️ Erro de DNS (domínio não encontrado) para a vaga: {link_atual}")
        vagas_processadas_set.add(link_atual)
        salvar_vagas_processadas(vagas_processadas_set)
        return False

    if pagina_nao_encontrada(page):
        log(f"⚠️ Página da vaga não encontrada (404): {link_atual}")
        vagas_processadas_set.add(link_atual)
        salvar_vagas_processadas(vagas_processadas_set)
        return False

    page.wait_for_load_state("networkidle")
    
    # Verifica login novamente após carregar a página da vaga
    if is_login_page(page):
        log("🔐 Página de login detectada na vaga. Relogando e tentando novamente...")
        fazer_login(page, return_url=link_atual)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
        return aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_atual, titulo_vaga)
    
    time.sleep(2)
    aceitar_cookies(page)
    contexto_vaga = extrair_contexto_vaga(page)
    log(f"📄 Contexto da vaga extraído ({len(contexto_vaga)} chars)")

    if not clicar_candidatar(page):
        log("❌ Botão de candidatura não encontrado")
        return False
    log("✅ Clicou em 'Candidatar-se'")
    time.sleep(3)

    max_iter = 30
    personalization_done = False
    consecutive_clicks = 0
    last_button_text = ""

    for step in range(max_iter):
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except:
            pass

        # Verifica se foi redirecionado para login durante o fluxo
        if is_login_page(page):
            log("🔐 Redirecionado para login durante a candidatura. Relogando...")
            fazer_login(page, return_url=link_atual)
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)
            return aplicar_vaga(page, contexto_cv, vagas_processadas_set, link_atual, titulo_vaga)

        aceitar_cookies(page)
        html = page.content().lower()
        if "você já se candidatou" in html:
            log("⚠️ Vaga já candidatada anteriormente")
            vagas_processadas_set.add(link_atual)
            salvar_vagas_processadas(vagas_processadas_set)
            return False

        if not personalization_done and page.locator('button#dialog-save-personalization-step').count() > 0:
            log("📢 Modal de personalização detectado!")
            if personalizar_candidatura(page, contexto_cv, contexto_vaga):
                log("🎉 Candidatura finalizada com sucesso!")
                vagas_processadas_set.add(link_atual)
                salvar_vagas_processadas(vagas_processadas_set)
                salvar_conhecimento_vaga(link_atual, titulo_vaga, contexto_vaga, [])
                return True
            else:
                personalization_done = True
                continue

        if confirmar_modal_se_existir(page):
            continue

        # Botão de finalização (primeira tentativa)
        finalizar = page.locator('button:has-text("Finalizar candidatura"), button:has-text("Enviar candidatura")')
        if finalizar.count():
            try:
                finalizar.first.click(force=True)
                log("🎉 Candidatura finalizada com sucesso!")
                vagas_processadas_set.add(link_atual)
                salvar_vagas_processadas(vagas_processadas_set)
                salvar_conhecimento_vaga(link_atual, titulo_vaga, contexto_vaga, [])
                return True
            except Exception as e:
                log(f"Erro ao finalizar candidatura: {e}")

        # Botão "Continuar" / "Salvar e continuar"
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

            if tem_erro_no_formulario(page):
                log("⚠️ Formulário com erros. Tentando corrigir...")
                time.sleep(2)
                continue

            try:
                selects = page.locator('select').all()
                for sel in selects:
                    if sel.get_attribute("value") == "":
                        sel.select_option(index=0)

                url_before = page.url
                continuar.first.click(force=True)
                log("➡️ Clicou em 'Continuar/Salvar'")

                # Aguarda mudança de URL ou desaparecimento do botão
                for _ in range(10):
                    time.sleep(0.5)
                    if page.url != url_before:
                        log("✅ Redirecionamento detectado após clique.")
                        break
                    if continuar.count() == 0 or not continuar.first.is_visible():
                        log("✅ Botão 'Continuar' não está mais visível.")
                        break
                else:
                    if tem_erro_no_formulario(page):
                        log("⚠️ Erro de validação no formulário. Tentando novamente...")
                        continue
                    log("⚠️ Nenhuma mudança detectada após clique. Continuando...")

                time.sleep(2)
                continue
            except Exception as e:
                log(f"Erro ao clicar em continuar: {e}")

        # Botão "Responder agora"
        responder = page.locator('button:has-text("Responder agora")')
        if responder.count():
            try:
                responder.first.click(force=True)
                page.wait_for_selector('input, textarea, select', timeout=10000)
                log("📝 Clicou em 'Responder agora'")
                time.sleep(2)
                perguntas_respostas, html_form = preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, link_atual)
                salvar_conhecimento_vaga(link_atual, titulo_vaga, contexto_vaga, perguntas_respostas, html_form)
                for _ in range(5):
                    if confirmar_modal_se_existir(page):
                        break
                    time.sleep(1)
                continue
            except Exception as e:
                log(f"Erro ao responder formulário: {e}")

        # Caso haja campos de texto/textarea (formulário não detectado pelo botão "Responder agora")
        if page.locator('textarea, input[type="text"]').count() > 0:
            log("✍️ Formulário detectado, preenchendo...")
            try:
                perguntas_respostas, html_form = preencher_formulario_dinamico(page, contexto_cv, contexto_vaga, link_atual)
                salvar_conhecimento_vaga(link_atual, titulo_vaga, contexto_vaga, perguntas_respostas, html_form)
                for _ in range(5):
                    if confirmar_modal_se_existir(page):
                        break
                    time.sleep(1)
                salvar = page.locator('button:has-text("Salvar e continuar")')
                if salvar.count():
                    salvar.first.click(force=True)
                    time.sleep(2)
                    continue
            except Exception as e:
                log(f"Erro ao preencher formulário: {e}")

        if confirmar_perguntas_eliminatorias(page):
            continue

        # Fallback genérico – evita clicar em botões na página de login
        if fallback_count < MAX_FALLBACK and not is_login_page(page):
            botoes = page.locator('button:not(:has-text("Cancelar"))')
            if botoes.count():
                fallback_count += 1
                try:
                    botoes.first.click(force=True)
                    log("⚠️ Fallback: clicou em botão genérico")
                    time.sleep(2)
                    continue
                except:
                    pass
        else:
            break

    log("❌ Não foi possível concluir a candidatura")
    return False

def ir_para_proxima_pagina(page):
    try:
        next_btn = page.locator('nav[aria-label="navegação de paginação"] button[aria-label="Próxima página"]')
        if next_btn.count() == 0:
            log("⚠️ Botão 'Próxima página' não encontrado. Verificando se é o fim da paginação.")
            return False
        if next_btn.first.is_disabled():
            log("🏁 Não há próxima página. Encerrando busca.")
            return False
        next_btn.first.click()
        log("⏩ Navegando para a próxima página...")
        time.sleep(3)
        page.wait_for_load_state("networkidle", timeout=10000)
        aceitar_cookies(page)
        return True
    except Exception as e:
        log(f"Erro ao tentar ir para próxima página: {e}")
        return False

# ================= NOVA FUNÇÃO DE LOGIN =================
def fazer_login(page, return_url=None):
    """
    Realiza login acessando diretamente a página de login da Gupy.
    Aguarda o redirecionamento natural na mesma aba e, se necessário,
    navega para a URL de destino.
    """
    log("🔐 Iniciando processo de login (acesso direto)...")

    # Passo 1: ir para a página de login
    login_url = "https://login.gupy.io/candidates/signin"
    log(f"🌐 Navegando para {login_url}")
    page.goto(login_url)
    page.wait_for_load_state("networkidle", timeout=15000)
    time.sleep(1)

    # Passo 2: preencher credenciais
    try:
        page.wait_for_selector('#username', timeout=15000)
    except:
        log("❌ Página de login não carregou corretamente.")
        return False

    email_input = page.locator('#username')
    email_input.fill(EMAIL)
    log("Email preenchido.")

    senha_input = page.locator('#password-input')
    if senha_input.count() == 0:
        senha_input = page.locator('input[name="password"]')
    senha_input.fill(SENHA)
    log("Senha preenchida.")

    # Passo 3: submeter o login e aguardar navegação
    login_btn = page.locator('#button-signin')
    if login_btn.count() == 0:
        login_btn = page.locator('button[type="submit"]:has-text("Acessar")')

    # Clique e aguarda a navegação (mesma aba)
    try:
        with page.expect_navigation(timeout=15000):
            login_btn.first.click()
        log("✅ Navegação após login detectada.")
    except Exception as e:
        log(f"⚠️ Navegação não detectada: {e}. Tentando continuar...")

    # Aguarda um pouco para permitir redirecionamentos adicionais
    time.sleep(3)
    
    # Aguarda a página estabilizar (sem mais navegações por 2 segundos)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except:
        pass

    # Passo 4: verificar a URL atual após todos os redirecionamentos
    current_url = page.url
    log(f"📍 URL após login (final): {current_url}")

    # Se já estivermos na página de busca ou na URL retornada, não fazemos nada
    target_url = return_url if return_url else GUPY_SEARCH_URL
    if "job-search" in current_url or current_url == target_url:
        log("✅ Já estamos na página desejada.")
    else:
        log(f"🌐 Navegando para a URL desejada: {target_url}")
        page.goto(target_url)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)

    # Verifica se realmente está logado
    if is_logged_in(page):
        log("✅ Login finalizado com sucesso.")
        return True
    else:
        log("❌ Falha no login. Verifique credenciais ou CAPTCHA.")
        return False

def verificar_e_relogar_se_necessario(page, return_url=None):
    """Verifica se o usuário está deslogado e realiza login novamente se necessário."""
    if not is_logged_in(page):
        log("🔐 Sessão expirada ou não logado. Realizando login...")
        return fazer_login(page, return_url)
    return False

def main():
    try:
        if not iniciar_chrome_com_debug(9222):
            log("❌ Falha ao iniciar Chrome com debug.")
            return

        contexto_cv = extrair_texto_pdf(CV_PDF_PATH)
        if not contexto_cv:
            log("❌ Falha ao carregar o currículo.")
            return
        log("Currículo carregado com sucesso.")
        
        vagas_processadas = carregar_vagas_processadas()
        log(f"📂 Carregadas {len(vagas_processadas)} vagas já processadas.")
        
        log("Conectando ao Chrome via CDP...")
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            except Exception as e:
                log(f"❌ Erro ao conectar: {e}")
                return
            
            page = None
            for ctx in browser.contexts:
                for page_candidate in ctx.pages:
                    if "devtools" not in page_candidate.url.lower():
                        page = page_candidate
                        break
                if page:
                    break
            
            if not page:
                log("❌ Nenhuma aba válida encontrada.")
                return
            
            log(f"✅ Conectado! Página atual: {page.url}")
            page.bring_to_front()
            page.set_default_timeout(60000)
            
            # Realizar login seguindo o novo fluxo
            if not fazer_login(page):
                log("❌ Não foi possível fazer login. Abortando.")
                return

            # A página já deve estar na URL de busca (job-search), mas garantimos:
            if "job-search" not in page.url:
                log("Navegando para a página de busca...")
                page.goto(GUPY_SEARCH_URL)
                page.wait_for_load_state("networkidle", timeout=15000)

            # Agora sim, iniciar busca por palavras-chave
            for palavra in KEYWORDS:
                log(f"\n{'='*50}\n🔍 BUSCANDO: '{palavra}'\n{'='*50}")
                aceitar_cookies(page)
                page.bring_to_front()
                time.sleep(0.5)
                buscar_vagas_por_palavra_chave(page, palavra)
                aplicar_filtros(page)

                pagina_atual = 1
                while True:
                    log(f"--- Página {pagina_atual} para '{palavra}' ---")
                    soup = BeautifulSoup(page.content(), 'html.parser')
                    cards = soup.select('a[href*="/job/"]')
                    log(f"Encontrados {len(cards)} cards.")

                    vagas_priorizadas = []
                    for card in cards:
                        link = card.get('href')
                        if not link.startswith('http'):
                            link = f"https://portal.gupy.io{link}"
                        if link in vagas_processadas:
                            continue
                        titulo = card.get_text(strip=True).lower()
                        if not any(kw.lower() in titulo for kw in KEYWORDS):
                            continue
                        tipo, modelo, local = extrair_info_vaga(str(card))
                        score = priorizar_vaga(tipo, modelo, local)
                        if score < 99:
                            vagas_priorizadas.append((score, link, titulo, tipo, modelo, local))

                    vagas_priorizadas.sort(key=lambda x: x[0])
                    log(f"Vagas priorizadas: {len(vagas_priorizadas)}")

                    if vagas_priorizadas:
                        for score, link, titulo, _, _, _ in vagas_priorizadas:
                            log(f"Candidatando para: {titulo} (Score={score})")
                            try:
                                page.goto(link, timeout=30000)
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception as e:
                                if "ERR_NAME_NOT_RESOLVED" in str(e) or "net::ERR_NAME_NOT_RESOLVED" in str(e):
                                    log(f"⚠️ Link inválido (DNS não resolvido): {link}")
                                    vagas_processadas.add(link)
                                    salvar_vagas_processadas(vagas_processadas)
                                    
                                    # Tenta voltar para a página de busca de forma robusta
                                    try:
                                        # Aguarda um pouco para a página de erro estabilizar
                                        time.sleep(2)
                                        # Força a navegação com wait_until='domcontentloaded' para evitar esperar por recursos que não existem
                                        page.goto(GUPY_SEARCH_URL, timeout=30000, wait_until='domcontentloaded')
                                        page.wait_for_load_state("networkidle", timeout=15000)
                                    except Exception as nav_error:
                                        log(f"⚠️ Erro ao voltar para a página de busca: {nav_error}")
                                        # Se falhar, tenta recarregar a página atual (pode ser a página de erro)
                                        try:
                                            page.reload()
                                            time.sleep(2)
                                            page.goto(GUPY_SEARCH_URL, timeout=30000, wait_until='domcontentloaded')
                                        except:
                                            log("❌ Não foi possível recuperar a página de busca. Recriando a página...")
                                            # Último recurso: recriar a página (fechar a atual e abrir nova)
                                            # Como estamos usando uma única página, podemos tentar navegar para "about:blank" primeiro
                                            page.goto("about:blank")
                                            page.goto(GUPY_SEARCH_URL, timeout=30000)
                                    
                                    # Reaplica os filtros e recarrega a busca
                                    buscar_vagas_por_palavra_chave(page, palavra)
                                    aplicar_filtros(page)
                                    break  # Sai do for para recomeçar a coleta de cards
                                else:
                                    raise  # relança outros erros

                            # Se chegou aqui, a página carregou sem erro de DNS
                            page.bring_to_front()
                            time.sleep(3)
                            aceitar_cookies(page)
                            if aplicar_vaga(page, contexto_cv, vagas_processadas, link, titulo):
                                log("✅ Sucesso na candidatura!")
                            else:
                                log("❌ Falha ou vaga já candidatada.")
                            page.goto(GUPY_SEARCH_URL)
                            time.sleep(5)
                            aceitar_cookies(page)
                            page.bring_to_front()
                            buscar_vagas_por_palavra_chave(page, palavra)
                            aplicar_filtros(page)
                            time.sleep(3)
                            break
                        continue

                    if ir_para_proxima_pagina(page):
                        pagina_atual += 1
                        time.sleep(2)
                        continue
                    else:
                        log(f"🚫 Nenhuma vaga prioritária para '{palavra}'.")
                        break

            log("\n✅ Processamento concluído.")
    except KeyboardInterrupt:
        log("\n⚠️ Interrompido pelo usuário.")
        if 'vagas_processadas' in locals():
            salvar_vagas_processadas(vagas_processadas)
    except Exception as e:
        log(f"❌ Erro: {e}")
        traceback.print_exc()
        if 'vagas_processadas' in locals():
            salvar_vagas_processadas(vagas_processadas)

if __name__ == "__main__":
    main()