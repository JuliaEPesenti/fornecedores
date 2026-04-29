from flask import Flask, request, jsonify, send_from_directory, session
import psycopg2, psycopg2.extras, requests, re, smtplib, hashlib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from functools import wraps

app = Flask(__name__, static_folder="static")
app.secret_key = "fornecedores_secret_2024"

DATABASE_URL = os.environ.get("DATABASE_URL")
DB = "fornecedores.db"

# ─── Banco ────────────────────────────────────────────────────────────────────
def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def criar_banco():
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                nome     TEXT NOT NULL,
                email    TEXT NOT NULL UNIQUE,
                senha    TEXT NOT NULL,
                perfil   TEXT DEFAULT 'usuario',
                ativo    INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subcategorias (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                nome         TEXT NOT NULL,
                categoria_id INTEGER,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fornecedores (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                nome           TEXT NOT NULL,
                categoria_id   INTEGER,
                subcategoria_id INTEGER,
                contato        TEXT DEFAULT '',
                email          TEXT DEFAULT '',
                cidade         TEXT DEFAULT '',
                site           TEXT DEFAULT '',
                whatsapp       TEXT DEFAULT '',
                ativo          INTEGER DEFAULT 1,
                criado_em      TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (categoria_id)    REFERENCES categorias(id),
                FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historico (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tabela     TEXT,
                registro_id INTEGER,
                acao       TEXT,
                detalhe    TEXT,
                usuario    TEXT,
                criado_em  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fila_aprovacao (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nome      TEXT,
                categoria TEXT,
                contato   TEXT DEFAULT '',
                email     TEXT DEFAULT '',
                cidade    TEXT DEFAULT '',
                site      TEXT DEFAULT '',
                status    TEXT DEFAULT 'pendente',
                criado_em TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_busca (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria       TEXT NOT NULL,
                cidade          TEXT DEFAULT '',
                intervalo_horas INTEGER DEFAULT 24,
                ultima_busca    TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_email (
                id       INTEGER PRIMARY KEY,
                host     TEXT DEFAULT '',
                porta    INTEGER DEFAULT 587,
                usuario  TEXT DEFAULT '',
                senha    TEXT DEFAULT '',
                remetente TEXT DEFAULT ''
            )
        """)
        # Admin padrão
        senha_hash = hashlib.sha256("admin123".encode()).hexdigest()
        conn.execute("INSERT OR IGNORE INTO usuarios (nome,email,senha,perfil) VALUES (?,?,?,?)",
                     ("Administrador","admin@sistema.com", senha_hash, "admin"))
        conn.commit()
    print("Banco pronto!")

def registrar_historico(tabela, registro_id, acao, detalhe, usuario="sistema"):
    with conectar() as conn:
        conn.execute("INSERT INTO historico (tabela,registro_id,acao,detalhe,usuario) VALUES (?,?,?,?,?)",
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
        u = conn.execute("SELECT * FROM usuarios WHERE email=? AND senha=? AND ativo=1",
                         (d.get("email",""), senha_hash)).fetchone()
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
        rows = conn.execute("SELECT id,nome,email,perfil,ativo FROM usuarios ORDER BY nome").fetchall()
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
            cur = conn.execute("INSERT INTO usuarios (nome,email,senha,perfil) VALUES (?,?,?,?)",
                               (d["nome"], d["email"], senha_hash, d.get("perfil","usuario")))
            conn.commit()
        registrar_historico("usuarios", cur.lastrowid, "criou", f"Usuário {d['nome']}", usuario_logado())
        return jsonify({"mensagem": "Usuário criado!", "id": cur.lastrowid}), 201
    except:
        return jsonify({"erro": "E-mail já cadastrado"}), 400

@app.route("/usuarios/<int:id>", methods=["DELETE"])
@requer_login
@requer_admin
def deletar_usuario(id):
    with conectar() as conn:
        conn.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (id,))
        conn.commit()
    registrar_historico("usuarios", id, "desativou", "Usuário desativado", usuario_logado())
    return jsonify({"mensagem": "Usuário desativado!"})

# ─── Categorias ───────────────────────────────────────────────────────────────
@app.route("/categorias", methods=["GET"])
@requer_login
def listar_categorias():
    with conectar() as conn:
        cats = conn.execute("SELECT * FROM categorias ORDER BY nome").fetchall()
        result = []
        for c in cats:
            subs = conn.execute("SELECT * FROM subcategorias WHERE categoria_id=? ORDER BY nome", (c["id"],)).fetchall()
            result.append({**dict(c), "subcategorias": [dict(s) for s in subs]})
    return jsonify(result)

@app.route("/categorias", methods=["POST"])
@requer_login
def criar_categoria():
    d = request.json
    if not d.get("nome"): return jsonify({"erro": "Nome obrigatório"}), 400
    try:
        with conectar() as conn:
            cur = conn.execute("INSERT INTO categorias (nome) VALUES (?)", (d["nome"],))
            conn.commit()
        registrar_historico("categorias", cur.lastrowid, "criou", f"Categoria {d['nome']}", usuario_logado())
        return jsonify({"mensagem": "Categoria criada!", "id": cur.lastrowid}), 201
    except:
        return jsonify({"erro": "Categoria já existe"}), 400

@app.route("/categorias/<int:id>", methods=["DELETE"])
@requer_login
@requer_admin
def deletar_categoria(id):
    with conectar() as conn:
        conn.execute("DELETE FROM subcategorias WHERE categoria_id=?", (id,))
        conn.execute("DELETE FROM categorias WHERE id=?", (id,))
        conn.commit()
    return jsonify({"mensagem": "Categoria removida!"})

@app.route("/subcategorias", methods=["POST"])
@requer_login
def criar_subcategoria():
    d = request.json
    if not d.get("nome") or not d.get("categoria_id"): return jsonify({"erro": "Nome e categoria obrigatórios"}), 400
    with conectar() as conn:
        cur = conn.execute("INSERT INTO subcategorias (nome,categoria_id) VALUES (?,?)", (d["nome"], d["categoria_id"]))
        conn.commit()
    registrar_historico("subcategorias", cur.lastrowid, "criou", f"Subcategoria {d['nome']}", usuario_logado())
    return jsonify({"mensagem": "Subcategoria criada!", "id": cur.lastrowid}), 201

@app.route("/subcategorias/<int:id>", methods=["DELETE"])
@requer_login
@requer_admin
def deletar_subcategoria(id):
    with conectar() as conn:
        conn.execute("DELETE FROM subcategorias WHERE id=?", (id,))
        conn.commit()
    return jsonify({"mensagem": "Removida!"})

# ─── Fornecedores ─────────────────────────────────────────────────────────────
@app.route("/fornecedores", methods=["GET"])
@requer_login
def listar():
    cat   = request.args.get("categoria_id","")
    subcat= request.args.get("subcategoria_id","")
    cidade= request.args.get("cidade","")
    busca = request.args.get("busca","")
    sql   = """SELECT f.*, c.nome as categoria_nome, s.nome as subcategoria_nome
               FROM fornecedores f
               LEFT JOIN categorias c ON f.categoria_id = c.id
               LEFT JOIN subcategorias s ON f.subcategoria_id = s.id
               WHERE f.ativo=1"""
    params = []
    if cat:    sql += " AND f.categoria_id=?";    params.append(cat)
    if subcat: sql += " AND f.subcategoria_id=?"; params.append(subcat)
    if cidade: sql += " AND f.cidade=?";          params.append(cidade)
    if busca:  sql += " AND (f.nome LIKE ? OR f.cidade LIKE ? OR c.nome LIKE ?)"; params += [f"%{busca}%"]*3
    sql += " ORDER BY f.nome"
    with conectar() as conn:
        rows = conn.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/fornecedores", methods=["POST"])
@requer_login
def cadastrar():
    d = request.json
    if not d.get("nome"): return jsonify({"erro": "Nome obrigatório"}), 400
    with conectar() as conn:
        cur = conn.execute("""INSERT INTO fornecedores (nome,categoria_id,subcategoria_id,contato,email,cidade,site,whatsapp)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (d["nome"], d.get("categoria_id"), d.get("subcategoria_id"),
                            d.get("contato",""), d.get("email",""), d.get("cidade",""),
                            d.get("site",""), d.get("whatsapp","")))
        conn.commit()
    registrar_historico("fornecedores", cur.lastrowid, "cadastrou", f"Fornecedor {d['nome']}", usuario_logado())
    return jsonify({"mensagem": "Cadastrado!", "id": cur.lastrowid}), 201

@app.route("/fornecedores/<int:id>", methods=["PUT"])
@requer_login
def editar(id):
    d = request.json
    with conectar() as conn:
        conn.execute("""UPDATE fornecedores SET nome=?,categoria_id=?,subcategoria_id=?,
                        contato=?,email=?,cidade=?,site=?,whatsapp=? WHERE id=?""",
                     (d.get("nome"), d.get("categoria_id"), d.get("subcategoria_id"),
                      d.get("contato",""), d.get("email",""), d.get("cidade",""),
                      d.get("site",""), d.get("whatsapp",""), id))
        conn.commit()
    registrar_historico("fornecedores", id, "editou", f"Fornecedor {d.get('nome')}", usuario_logado())
    return jsonify({"mensagem": "Atualizado!"})

@app.route("/fornecedores/<int:id>", methods=["DELETE"])
@requer_login
def deletar(id):
    with conectar() as conn:
        f = conn.execute("SELECT nome FROM fornecedores WHERE id=?", (id,)).fetchone()
        conn.execute("UPDATE fornecedores SET ativo=0 WHERE id=?", (id,))
        conn.commit()
    registrar_historico("fornecedores", id, "removeu", f"Fornecedor {f['nome'] if f else id}", usuario_logado())
    return jsonify({"mensagem": "Removido!"})

# ─── E-mail ───────────────────────────────────────────────────────────────────
@app.route("/email/config", methods=["GET"])
@requer_login
@requer_admin
def get_email_config():
    with conectar() as conn:
        cfg = conn.execute("SELECT id,host,porta,usuario,remetente FROM config_email WHERE id=1").fetchone()
    return jsonify(dict(cfg) if cfg else {})

@app.route("/email/config", methods=["POST"])
@requer_login
@requer_admin
def salvar_email_config():
    d = request.json
    with conectar() as conn:
        conn.execute("DELETE FROM config_email")
        conn.execute("INSERT INTO config_email (id,host,porta,usuario,senha,remetente) VALUES (1,?,?,?,?,?)",
                     (d.get("host",""), d.get("porta",587), d.get("usuario",""), d.get("senha",""), d.get("remetente","")))
        conn.commit()
    return jsonify({"mensagem": "Configuração de e-mail salva!"})

@app.route("/email/enviar", methods=["POST"])
@requer_login
def enviar_email():
    d = request.json
    destinatario = d.get("para","")
    assunto      = d.get("assunto","")
    corpo        = d.get("corpo","")
    if not destinatario or not assunto or not corpo:
        return jsonify({"erro": "Preencha todos os campos"}), 400
    with conectar() as conn:
        cfg = conn.execute("SELECT * FROM config_email WHERE id=1").fetchone()
    if not cfg or not cfg["host"]:
        return jsonify({"erro": "Configure o servidor de e-mail primeiro nas Configurações"}), 400
    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["remetente"]
        msg["To"]      = destinatario
        msg["Subject"] = assunto
        msg.attach(MIMEText(corpo, "plain", "utf-8"))
        with smtplib.SMTP(cfg["host"], cfg["porta"], timeout=10) as server:
            server.starttls()
            server.login(cfg["usuario"], cfg["senha"])
            server.send_message(msg)
        registrar_historico("fornecedores", 0, "enviou e-mail", f"Para: {destinatario} | Assunto: {assunto}", usuario_logado())
        return jsonify({"mensagem": "E-mail enviado com sucesso!"})
    except Exception as e:
        return jsonify({"erro": f"Erro ao enviar: {str(e)}"}), 500

# ─── Histórico ────────────────────────────────────────────────────────────────
@app.route("/historico")
@requer_login
def listar_historico():
    with conectar() as conn:
        rows = conn.execute("SELECT * FROM historico ORDER BY criado_em DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])

# ─── Stats ────────────────────────────────────────────────────────────────────
@app.route("/stats")
@requer_login
def stats():
    with conectar() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM fornecedores WHERE ativo=1").fetchone()[0]
        pendente = conn.execute("SELECT COUNT(*) FROM fila_aprovacao WHERE status='pendente'").fetchone()[0]
        cats     = conn.execute("SELECT COUNT(*) FROM categorias").fetchone()[0]
    return jsonify({"total": total, "pendentes": pendente, "categorias": cats})

# ─── Fila ─────────────────────────────────────────────────────────────────────
@app.route("/fila")
@requer_login
def listar_fila():
    with conectar() as conn:
        rows = conn.execute("SELECT * FROM fila_aprovacao WHERE status='pendente' ORDER BY criado_em DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/fila/<int:id>/aprovar", methods=["POST"])
@requer_login
def aprovar(id):
    with conectar() as conn:
        item = conn.execute("SELECT * FROM fila_aprovacao WHERE id=?", (id,)).fetchone()
        if not item: return jsonify({"erro": "Não encontrado"}), 404
        conn.execute("INSERT INTO fornecedores (nome,contato,email,cidade,site) VALUES (?,?,?,?,?)",
                     (item["nome"],item["contato"],item["email"],item["cidade"],item["site"]))
        conn.execute("UPDATE fila_aprovacao SET status='aprovado' WHERE id=?", (id,))
        conn.commit()
    registrar_historico("fornecedores", id, "aprovou da fila", f"Fornecedor {item['nome']}", usuario_logado())
    return jsonify({"mensagem": "Aprovado!"})

@app.route("/fila/<int:id>/rejeitar", methods=["POST"])
@requer_login
def rejeitar(id):
    with conectar() as conn:
        conn.execute("UPDATE fila_aprovacao SET status='rejeitado' WHERE id=?", (id,))
        conn.commit()
    return jsonify({"mensagem": "Rejeitado!"})

@app.route("/fila/aprovar-todos", methods=["POST"])
@requer_login
def aprovar_todos():
    with conectar() as conn:
        itens = conn.execute("SELECT * FROM fila_aprovacao WHERE status='pendente'").fetchall()
        for item in itens:
            conn.execute("INSERT INTO fornecedores (nome,contato,email,cidade,site) VALUES (?,?,?,?,?)",
                         (item["nome"],item["contato"],item["email"],item["cidade"],item["site"]))
        conn.execute("UPDATE fila_aprovacao SET status='aprovado' WHERE status='pendente'")
        conn.commit()
    return jsonify({"mensagem": f"{len(itens)} aprovados!"})

# ─── Busca web ─────────────────────────────────────────────────────────────────
SERPAPI_KEY = "b9a563933a5d7e17d2a195ee8f5908663400dfbc6d5b1604fd9a67ab7b05e3a5"

def buscar_fornecedores_web(categoria, cidade=""):
    local = f" {cidade}" if cidade else " Brasil"
    query = f"empresa fornecedor {categoria}{local} CNPJ contato"
    url   = "https://serpapi.com/search"
    params = {
        "q":       query,
        "hl":      "pt",
        "gl":      "br",
        "num":     20,
        "api_key": SERPAPI_KEY,
    }
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

            resultados.append({"nome": nome, "categoria": categoria, "contato": tel,
                                "email": email, "cidade": cidade, "site": site})
        return resultados
    except Exception as e:
        print(f"Erro na busca: {e}")
        return []

def salvar_na_fila(resultados, categoria):
    with conectar() as conn:
        ex = {r[0].lower() for r in conn.execute("SELECT nome FROM fila_aprovacao WHERE categoria=?", (categoria,))}
        ex |= {r[0].lower() for r in conn.execute("SELECT nome FROM fornecedores WHERE ativo=1")}
        novos = 0
        for r in resultados:
            if r["nome"].lower() not in ex:
                conn.execute("INSERT INTO fila_aprovacao (nome,categoria,contato,email,cidade,site) VALUES (?,?,?,?,?,?)",
                             (r["nome"],r["categoria"],r["contato"],r["email"],r["cidade"],r["site"]))
                ex.add(r["nome"].lower()); novos += 1
        conn.commit()
    return novos

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
        rows = conn.execute("SELECT * FROM config_busca ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/config-busca", methods=["POST"])
@requer_login
def criar_config():
    d = request.json
    if not d.get("categoria"): return jsonify({"erro": "Categoria obrigatória"}), 400
    with conectar() as conn:
        cur = conn.execute("INSERT INTO config_busca (categoria,cidade,intervalo_horas) VALUES (?,?,?)",
                           (d["categoria"], d.get("cidade",""), d.get("intervalo_horas",24)))
        conn.commit()
    return jsonify({"mensagem": "Configuração salva!", "id": cur.lastrowid}), 201

@app.route("/config-busca/<int:id>", methods=["DELETE"])
@requer_login
def deletar_config(id):
    with conectar() as conn:
        conn.execute("DELETE FROM config_busca WHERE id=?", (id,))
        conn.commit()
    return jsonify({"mensagem": "Removido!"})

def busca_automatica():
    with conectar() as conn:
        configs = conn.execute("SELECT * FROM config_busca").fetchall()
    for cfg in configs:
        if cfg["ultima_busca"]:
            diff = (datetime.now() - datetime.fromisoformat(cfg["ultima_busca"])).total_seconds() / 3600
            if diff < cfg["intervalo_horas"]: continue
        resultados = buscar_fornecedores_web(cfg["categoria"], cfg["cidade"])
        salvar_na_fila(resultados, cfg["categoria"])
        with conectar() as conn:
            conn.execute("UPDATE config_busca SET ultima_busca=? WHERE id=?",
                         (datetime.now().isoformat(timespec="seconds"), cfg["id"]))
            conn.commit()

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    criar_banco()
    scheduler = BackgroundScheduler()
    scheduler.add_job(busca_automatica, "interval", minutes=30)
    scheduler.start()
    print("Acesse: http://localhost:5000")
    print("Login padrão: admin@sistema.com / admin123")
    try:
        app.run(debug=False, use_reloader=False, port=5000)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


