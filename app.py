from flask import Flask, request, jsonify, send_from_directory, session
import psycopg2, psycopg2.extras, requests, re, smtplib, hashlib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from functools import wraps

app = Flask(__name__, static_folder="static")
app.secret_key = "fornecedores_secret_2024"

DATABASE_URL = os.environ.get("DATABASE_URL")

# ─── Banco ────────────────────────────────────────────────────────────────────
def conectar():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def criar_banco():
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id     SERIAL PRIMARY KEY,
                nome   TEXT NOT NULL,
                email  TEXT NOT NULL UNIQUE,
                senha  TEXT NOT NULL,
                perfil TEXT DEFAULT 'usuario',
                ativo  INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id   SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subcategorias (
                id           SERIAL PRIMARY KEY,
                nome         TEXT NOT NULL,
                categoria_id INTEGER REFERENCES categorias(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fornecedores (
                id              SERIAL PRIMARY KEY,
                nome            TEXT NOT NULL,
                categoria_id    INTEGER REFERENCES categorias(id),
                subcategoria_id INTEGER REFERENCES subcategorias(id),
                contato         TEXT DEFAULT '',
                email           TEXT DEFAULT '',
                cidade          TEXT DEFAULT '',
                estado          TEXT DEFAULT '',
                endereco        TEXT DEFAULT '',
                cnpj            TEXT DEFAULT '',
                situacao_cnpj   TEXT DEFAULT '',
                site            TEXT DEFAULT '',
                whatsapp        TEXT DEFAULT '',
                ativo           INTEGER DEFAULT 1,
                criado_em       TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historico (
                id          SERIAL PRIMARY KEY,
                tabela      TEXT,
                registro_id INTEGER,
                acao        TEXT,
                detalhe     TEXT,
                usuario     TEXT,
                criado_em   TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fila_aprovacao (
                id        SERIAL PRIMARY KEY,
                nome      TEXT,
                categoria TEXT,
                contato   TEXT DEFAULT '',
                email     TEXT DEFAULT '',
                cidade    TEXT DEFAULT '',
                estado    TEXT DEFAULT '',
                cnpj      TEXT DEFAULT '',
                situacao_cnpj TEXT DEFAULT '',
                site      TEXT DEFAULT '',
                status    TEXT DEFAULT 'pendente',
                criado_em TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config_busca (
                id              SERIAL PRIMARY KEY,
                categoria       TEXT NOT NULL,
                cidade          TEXT DEFAULT '',
                intervalo_horas INTEGER DEFAULT 24,
                ultima_busca    TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config_email (
                id        INTEGER PRIMARY KEY DEFAULT 1,
                host      TEXT DEFAULT '',
                porta     INTEGER DEFAULT 587,
                usuario   TEXT DEFAULT '',
                senha     TEXT DEFAULT '',
                remetente TEXT DEFAULT ''
            )
        """)
        # Admin padrão
        senha_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cur.execute("""
            INSERT INTO usuarios (nome,email,senha,perfil)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (email) DO NOTHING
        """, ("Administrador", "admin@sistema.com", senha_hash, "admin"))
        conn.commit()
    print("Banco pronto!")

def registrar_historico(tabela, registro_id, acao, detalhe, usuario="sistema"):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO historico (tabela,registro_id,acao,detalhe,usuario) VALUES (%s,%s,%s,%s,%s)",
                    (tabela, registro_id, acao, detalhe, usuario))
        conn.commit()

def usuario_logado():
    return session.get("usuario_nome", "desconhecido")

# ─── Auth ─────────────────────────────────────────────────────────────────────
def requer_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("usuario_id"):
            return jsonify({"erro": "Não autenticado"}), 401
        return f(*args, **kwargs)
    return decorated

def requer_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("perfil") != "admin":
            return jsonify({"erro": "Acesso negado"}), 403
        return f(*args, **kwargs)
    return decorated

@app.route("/auth/login", methods=["POST"])
def login():
    d = request.json
    senha_hash = hashlib.sha256(d.get("senha","").encode()).hexdigest()
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM usuarios WHERE email=%s AND senha=%s AND ativo=1",
                    (d.get("email",""), senha_hash))
        u = cur.fetchone()
    if not u:
        return jsonify({"erro": "E-mail ou senha incorretos"}), 401
    session["usuario_id"]   = u["id"]
    session["usuario_nome"] = u["nome"]
    session["perfil"]       = u["perfil"]
    return jsonify({"mensagem": "Login realizado!", "nome": u["nome"], "perfil": u["perfil"]})

@app.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"mensagem": "Logout realizado!"})

@app.route("/auth/me")
def me():
    if session.get("usuario_id"):
        return jsonify({"logado": True, "nome": session["usuario_nome"], "perfil": session["perfil"]})
    return jsonify({"logado": False})

# ─── Usuários ─────────────────────────────────────────────────────────────────
@app.route("/usuarios", methods=["GET"])
@requer_login
@requer_admin
def listar_usuarios():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id,nome,email,perfil,ativo FROM usuarios ORDER BY nome")
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/usuarios", methods=["POST"])
@requer_login
@requer_admin
def criar_usuario():
    d = request.json
    if not d.get("nome") or not d.get("email") or not d.get("senha"):
        return jsonify({"erro": "Nome, e-mail e senha obrigatórios"}), 400
    senha_hash = hashlib.sha256(d["senha"].encode()).hexdigest()
    try:
        with conectar() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO usuarios (nome,email,senha,perfil) VALUES (%s,%s,%s,%s)",
                        (d["nome"], d["email"], senha_hash, d.get("perfil","usuario")))
            conn.commit()
        return jsonify({"mensagem": "Usuário criado!"}), 201
    except Exception as e:
        return jsonify({"erro": "E-mail já cadastrado"}), 400

@app.route("/usuarios/<int:id>", methods=["DELETE"])
@requer_login
@requer_admin
def deletar_usuario(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE usuarios SET ativo=0 WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Desativado!"})

# ─── Stats ────────────────────────────────────────────────────────────────────
@app.route("/stats")
@requer_login
def stats():
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fornecedores WHERE ativo=1")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM categorias")
        cats = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fila_aprovacao WHERE status='pendente'")
        pendentes = cur.fetchone()[0]
    return jsonify({"total": total, "categorias": cats, "pendentes": pendentes})

# ─── Categorias ───────────────────────────────────────────────────────────────
@app.route("/categorias", methods=["GET"])
@requer_login
def listar_cats():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM categorias ORDER BY nome")
        cats = cur.fetchall()
        resultado = []
        for c in cats:
            cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT * FROM subcategorias WHERE categoria_id=%s ORDER BY nome", (c["id"],))
            subs = cur2.fetchall()
            resultado.append({**dict(c), "subcategorias": [dict(s) for s in subs]})
    return jsonify(resultado)

@app.route("/categorias", methods=["POST"])
@requer_login
def criar_cat():
    d = request.json
    if not d.get("nome"): return jsonify({"erro": "Nome obrigatório"}), 400
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO categorias (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (d["nome"],))
        conn.commit()
    return jsonify({"mensagem": "Categoria criada!"}), 201

@app.route("/categorias/<int:id>", methods=["DELETE"])
@requer_login
@requer_admin
def deletar_cat(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subcategorias WHERE categoria_id=%s", (id,))
        cur.execute("DELETE FROM categorias WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Removida!"})

@app.route("/subcategorias", methods=["POST"])
@requer_login
def criar_subcat():
    d = request.json
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO subcategorias (nome,categoria_id) VALUES (%s,%s)", (d["nome"], d["categoria_id"]))
        conn.commit()
    return jsonify({"mensagem": "Subcategoria criada!"}), 201

@app.route("/subcategorias/<int:id>", methods=["DELETE"])
@requer_login
def deletar_subcat(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subcategorias WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Removida!"})

# ─── Fornecedores ─────────────────────────────────────────────────────────────
@app.route("/fornecedores", methods=["GET"])
@requer_login
def listar_forn():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT f.*, c.nome as categoria_nome, s.nome as subcategoria_nome
            FROM fornecedores f
            LEFT JOIN categorias c ON f.categoria_id = c.id
            LEFT JOIN subcategorias s ON f.subcategoria_id = s.id
            WHERE f.ativo = 1
            ORDER BY f.nome
        """)
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/fornecedores", methods=["POST"])
@requer_login
def criar_forn():
    d = request.json
    if not d.get("nome"): return jsonify({"erro": "Nome obrigatório"}), 400
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO fornecedores
            (nome,categoria_id,subcategoria_id,contato,whatsapp,email,cidade,estado,endereco,cnpj,site)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (d["nome"], d.get("categoria_id"), d.get("subcategoria_id"),
             d.get("contato",""), d.get("whatsapp",""), d.get("email",""),
             d.get("cidade",""), d.get("estado",""), d.get("endereco",""),
             d.get("cnpj",""), d.get("site","")))
        conn.commit()
    registrar_historico("fornecedores", 0, "cadastrou fornecedor", d["nome"], usuario_logado())
    return jsonify({"mensagem": "Fornecedor cadastrado!"}), 201

@app.route("/fornecedores/<int:id>", methods=["PUT"])
@requer_login
def editar_forn(id):
    d = request.json
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("""UPDATE fornecedores SET
            nome=%s, categoria_id=%s, subcategoria_id=%s, contato=%s,
            whatsapp=%s, email=%s, cidade=%s, estado=%s, endereco=%s, cnpj=%s, site=%s
            WHERE id=%s""",
            (d["nome"], d.get("categoria_id"), d.get("subcategoria_id"),
             d.get("contato",""), d.get("whatsapp",""), d.get("email",""),
             d.get("cidade",""), d.get("estado",""), d.get("endereco",""),
             d.get("cnpj",""), d.get("site",""), id))
        conn.commit()
    registrar_historico("fornecedores", id, "editou fornecedor", d["nome"], usuario_logado())
    return jsonify({"mensagem": "Atualizado!"})

@app.route("/fornecedores/<int:id>", methods=["DELETE"])
@requer_login
def deletar_forn(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE fornecedores SET ativo=0 WHERE id=%s", (id,))
        conn.commit()
    registrar_historico("fornecedores", id, "removeu fornecedor", f"id={id}", usuario_logado())
    return jsonify({"mensagem": "Removido!"})

# ─── Histórico ────────────────────────────────────────────────────────────────
@app.route("/historico", methods=["GET"])
@requer_login
def listar_historico():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM historico ORDER BY criado_em DESC LIMIT 100")
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

# ─── Fila de aprovação ────────────────────────────────────────────────────────
@app.route("/fila", methods=["GET"])
@requer_login
def listar_fila():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM fila_aprovacao WHERE status='pendente' ORDER BY criado_em DESC")
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/fila/<int:id>/aprovar", methods=["POST"])
@requer_login
def aprovar_fila(id):
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM fila_aprovacao WHERE id=%s", (id,))
        item = cur.fetchone()
        if item:
            cur2 = conn.cursor()
            cur2.execute("""INSERT INTO fornecedores 
                (nome,contato,whatsapp,email,cidade,estado,site,cnpj,situacao_cnpj)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (item["nome"],item["contato"],item.get("whatsapp",""),
                 item["email"],item["cidade"],item.get("estado",""),
                 item["site"],item.get("cnpj",""),item.get("situacao_cnpj","")))
            cur2.execute("UPDATE fila_aprovacao SET status='aprovado' WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Aprovado!"})

@app.route("/fila/<int:id>/rejeitar", methods=["POST"])
@requer_login
def rejeitar_fila(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE fila_aprovacao SET status='rejeitado' WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Rejeitado!"})

@app.route("/fila/aprovar-todos", methods=["POST"])
@requer_login
def aprovar_todos():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM fila_aprovacao WHERE status='pendente'")
        itens = cur.fetchall()
        cur2 = conn.cursor()
        for item in itens:
            cur2.execute("""INSERT INTO fornecedores 
                (nome,contato,whatsapp,email,cidade,estado,site,cnpj,situacao_cnpj)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (item["nome"],item["contato"],item.get("whatsapp",""),
                 item["email"],item["cidade"],item.get("estado",""),
                 item["site"],item.get("cnpj",""),item.get("situacao_cnpj","")))
        cur2.execute("UPDATE fila_aprovacao SET status='aprovado' WHERE status='pendente'")
        conn.commit()
    return jsonify({"mensagem": f"{len(itens)} aprovados!"})

# ─── E-mail ───────────────────────────────────────────────────────────────────
@app.route("/email/config", methods=["GET"])
@requer_login
@requer_admin
def get_config_email():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM config_email WHERE id=1")
        cfg = cur.fetchone()
    return jsonify(dict(cfg) if cfg else {})

@app.route("/email/config", methods=["POST"])
@requer_login
@requer_admin
def set_config_email():
    d = request.json
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO config_email (id,host,porta,usuario,senha,remetente)
            VALUES (1,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
            host=EXCLUDED.host, porta=EXCLUDED.porta, usuario=EXCLUDED.usuario,
            senha=EXCLUDED.senha, remetente=EXCLUDED.remetente""",
            (d.get("host",""), d.get("porta",587), d.get("usuario",""), d.get("senha",""), d.get("remetente","")))
        conn.commit()
    return jsonify({"mensagem": "Configuração salva!"})

@app.route("/email/enviar", methods=["POST"])
@requer_login
def enviar_email():
    d = request.json
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM config_email WHERE id=1")
        cfg = cur.fetchone()
    if not cfg or not cfg["host"]:
        return jsonify({"erro": "Configure o servidor SMTP primeiro"}), 400
    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["remetente"]
        msg["To"]      = d["para"]
        msg["Subject"] = d["assunto"]
        msg.attach(MIMEText(d["corpo"], "plain"))
        with smtplib.SMTP(cfg["host"], cfg["porta"]) as s:
            s.starttls()
            s.login(cfg["usuario"], cfg["senha"])
            s.send_message(msg)
        return jsonify({"mensagem": "E-mail enviado com sucesso!"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ─── Busca web ────────────────────────────────────────────────────────────────
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "b9a563933a5d7e17d2a195ee8f5908663400dfbc6d5b1604fd9a67ab7b05e3a5")

# ─── Enriquecimento CNPJ ──────────────────────────────────────────────────────
def consultar_cnpj(cnpj):
    """Consulta CNPJ na API pública da Receita Federal e retorna dados enriquecidos."""
    cnpj_limpo = re.sub(r'\D', '', cnpj)
    if len(cnpj_limpo) != 14:
        return None
    try:
        url = f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        d = resp.json()
        situacao = d.get("descricao_situacao_cadastral", "")
        nome     = d.get("razao_social", "")
        fantasia = d.get("nome_fantasia", "")
        email    = d.get("email", "")
        cidade   = d.get("estabelecimento", {}).get("cidade", {}).get("nome", "")
        estado   = d.get("estabelecimento", {}).get("estado", {}).get("sigla", "")
        endereco = d.get("estabelecimento", {}).get("logradouro", "")
        numero   = d.get("estabelecimento", {}).get("numero", "")
        if endereco and numero:
            endereco = f"{endereco}, {numero}"
        telefones = d.get("estabelecimento", {}).get("ddd1","") + d.get("estabelecimento", {}).get("telefone1","")
        whatsapp  = re.sub(r'\D', '', telefones) if telefones else ""
        return {
            "nome":          fantasia or nome,
            "situacao_cnpj": "ATIVA" if "ATIVA" in situacao.upper() else situacao,
            "email":         email.lower() if email else "",
            "cidade":        cidade,
            "estado":        estado,
            "endereco":      endereco,
            "contato":       telefones,
            "whatsapp":      whatsapp,
        }
    except Exception as e:
        print(f"Erro ao consultar CNPJ: {e}")
        return None

def extrair_cnpj_do_texto(texto):
    """Tenta extrair CNPJ de um texto (snippet de busca)."""
    m = re.search(r'\d{2}[\.\-]?\d{3}[\.\-]?\d{3}[\/\-]?\d{4}[\-\.]?\d{2}', texto)
    return m.group() if m else None

def buscar_fornecedores_web(categoria, cidade=""):
    local  = f" {cidade}" if cidade else " Brasil"
    query  = f"empresa fornecedor {categoria}{local} CNPJ contato"
    url    = "https://serpapi.com/search"
    params = {"q": query, "hl": "pt", "gl": "br", "num": 20, "api_key": SERPAPI_KEY}
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        resultados = []
        ignorar = ["wikipedia","youtube","instagram","facebook","linkedin","olx","mercado","google","tiktok"]
        for item in data.get("organic_results", []):
            nome = re.sub(r"\s*[\|–-]\s*.{0,40}$", "", item.get("title","")).strip()
            site = item.get("link","")
            desc = item.get("snippet","")
            if any(s in nome.lower() for s in ignorar): continue
            if any(s in site.lower()  for s in ignorar): continue
            if len(nome) < 4 or len(nome) > 90: continue
            tel = ""; m = re.search(r"\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}", desc)
            if m: tel = m.group()
            email = ""; m2 = re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", desc)
            if m2: email = m2.group()
            cnpj = extrair_cnpj_do_texto(desc) or ""
            situacao_cnpj = ""
            # Se achou telefone, já coloca como whatsapp também (só números)
            whatsapp = re.sub(r'\D', '', tel) if tel else ""
            # Enriquecer com dados da Receita Federal se tiver CNPJ
            if cnpj:
                dados = consultar_cnpj(cnpj)
                if dados:
                    email         = dados.get("email") or email
                    tel           = dados.get("contato") or tel
                    whatsapp      = dados.get("whatsapp") or whatsapp
                    situacao_cnpj = dados.get("situacao_cnpj") or ""
                    cidade        = dados.get("cidade") or cidade
            resultados.append({"nome": nome, "categoria": categoria, "contato": tel,
                                "email": email, "cidade": cidade, "site": site,
                                "cnpj": cnpj, "situacao_cnpj": situacao_cnpj, "whatsapp": whatsapp})
        return resultados
    except Exception as e:
        print(f"Erro na busca: {e}")
        return []

def salvar_na_fila(resultados, categoria):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("SELECT LOWER(nome) FROM fila_aprovacao WHERE categoria=%s", (categoria,))
        ex = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT LOWER(nome) FROM fornecedores WHERE ativo=1")
        ex |= {r[0] for r in cur.fetchall()}
        novos = 0
        for r in resultados:
            if r["nome"].lower() not in ex:
                cur.execute("INSERT INTO fila_aprovacao (nome,categoria,contato,email,cidade,site,cnpj,situacao_cnpj,whatsapp) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (r["nome"],r["categoria"],r["contato"],r["email"],r["cidade"],r["site"],
                             r.get("cnpj",""),r.get("situacao_cnpj",""),r.get("whatsapp","")))
                ex.add(r["nome"].lower()); novos += 1
        conn.commit()
    return novos

@app.route("/cnpj/<cnpj>", methods=["GET"])
@requer_login
def buscar_cnpj(cnpj):
    dados = consultar_cnpj(cnpj)
    if not dados:
        return jsonify({"erro": "CNPJ não encontrado ou inválido"}), 404
    return jsonify(dados)

@app.route("/buscar", methods=["POST"])
@requer_login
def buscar_manual():
    d = request.json
    cat, cidade = d.get("categoria",""), d.get("cidade","")
    if not cat: return jsonify({"erro": "Informe a categoria"}), 400
    resultados = buscar_fornecedores_web(cat, cidade)
    novos = salvar_na_fila(resultados, cat)
    return jsonify({"encontrados": len(resultados), "novos_na_fila": novos})

@app.route("/config-busca", methods=["GET"])
@requer_login
def listar_configs():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM config_busca ORDER BY id")
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/config-busca", methods=["POST"])
@requer_login
def criar_config():
    d = request.json
    if not d.get("categoria"): return jsonify({"erro": "Categoria obrigatória"}), 400
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO config_busca (categoria,cidade,intervalo_horas) VALUES (%s,%s,%s)",
                    (d["categoria"], d.get("cidade",""), d.get("intervalo_horas",24)))
        conn.commit()
    return jsonify({"mensagem": "Configuração salva!"}), 201

@app.route("/config-busca/<int:id>", methods=["DELETE"])
@requer_login
def deletar_config(id):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM config_busca WHERE id=%s", (id,))
        conn.commit()
    return jsonify({"mensagem": "Removido!"})

def busca_automatica():
    with conectar() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM config_busca")
        configs = cur.fetchall()
    for cfg in configs:
        if cfg["ultima_busca"]:
            try:
                diff = (datetime.now() - datetime.fromisoformat(cfg["ultima_busca"])).total_seconds() / 3600
                if diff < cfg["intervalo_horas"]: continue
            except: pass
        resultados = buscar_fornecedores_web(cfg["categoria"], cfg["cidade"])
        salvar_na_fila(resultados, cfg["categoria"])
        with conectar() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE config_busca SET ultima_busca=%s WHERE id=%s",
                        (datetime.now().isoformat(timespec="seconds"), cfg["id"]))
            conn.commit()

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

criar_banco()
scheduler = BackgroundScheduler()
scheduler.add_job(busca_automatica, "interval", minutes=30)
scheduler.start()

if __name__ == "__main__":
    print("Acesse: http://localhost:5000")
    try:
        app.run(debug=False, use_reloader=False, port=5000)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
