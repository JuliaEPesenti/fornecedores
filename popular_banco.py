"""
Execute UMA VEZ para popular o banco com dados de exemplo.
Comando: python popular_banco.py
"""
import sqlite3, hashlib

DB = "fornecedores.db"
conn = sqlite3.connect(DB)

# Tabelas
conn.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE, senha TEXT NOT NULL,
        perfil TEXT DEFAULT 'usuario', ativo INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS subcategorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
        categoria_id INTEGER, FOREIGN KEY (categoria_id) REFERENCES categorias(id)
    );
    CREATE TABLE IF NOT EXISTS fornecedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
        categoria_id INTEGER, subcategoria_id INTEGER,
        contato TEXT DEFAULT '', email TEXT DEFAULT '',
        cidade TEXT DEFAULT '', site TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
        ativo INTEGER DEFAULT 1, criado_em TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tabela TEXT, registro_id INTEGER,
        acao TEXT, detalhe TEXT, usuario TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS fila_aprovacao (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, categoria TEXT,
        contato TEXT DEFAULT '', email TEXT DEFAULT '', cidade TEXT DEFAULT '',
        site TEXT DEFAULT '', status TEXT DEFAULT 'pendente',
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS config_busca (
        id INTEGER PRIMARY KEY AUTOINCREMENT, categoria TEXT NOT NULL,
        cidade TEXT DEFAULT '', intervalo_horas INTEGER DEFAULT 24, ultima_busca TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS config_email (
        id INTEGER PRIMARY KEY, host TEXT DEFAULT '', porta INTEGER DEFAULT 587,
        usuario TEXT DEFAULT '', senha TEXT DEFAULT '', remetente TEXT DEFAULT ''
    );
""")

# Admin padrão
senha = hashlib.sha256("admin123".encode()).hexdigest()
conn.execute("INSERT OR IGNORE INTO usuarios (nome,email,senha,perfil) VALUES (?,?,?,?)",
             ("Administrador","admin@sistema.com", senha, "admin"))

# Categorias e subcategorias
categorias = {
    "Metalurgia":       ["Aço", "Alumínio", "Ferro", "Cobre"],
    "Tecnologia":       ["Hardware", "Software", "Redes", "Suporte TI"],
    "Logística":        ["Transporte", "Armazenagem", "Courier"],
    "Química":          ["Solventes", "Tintas", "Lubrificantes"],
    "Agropecuária":     ["Sementes", "Fertilizantes", "Máquinas Agrícolas"],
    "Elétrica":         ["Cabos", "Painéis", "Iluminação"],
    "Madeira e Móveis": ["Madeira Bruta", "MDF", "Móveis Planejados"],
}

cat_ids = {}
for cat_nome in categorias:
    cur = conn.execute("INSERT OR IGNORE INTO categorias (nome) VALUES (?)", (cat_nome,))
    conn.commit()
    row = conn.execute("SELECT id FROM categorias WHERE nome=?", (cat_nome,)).fetchone()
    cat_ids[cat_nome] = row[0]
    for sub in categorias[cat_nome]:
        conn.execute("INSERT OR IGNORE INTO subcategorias (nome,categoria_id) VALUES (?,?)", (sub, row[0]))

# Fornecedores de exemplo
fornecedores = [
    ("AçoMax Ltda",    "Metalurgia",  "Aço",        "(11) 99000-1111", "acomax@email.com",   "São Paulo",      "", "11990001111"),
    ("QuimiPro",       "Química",     "Tintas",      "(21) 98000-2222", "quimipro@email.com", "Rio de Janeiro", "", ""),
    ("MadeiraBella",   "Madeira e Móveis","MDF",     "(41) 97000-3333", "madeira@email.com",  "Curitiba",       "", "41970003333"),
    ("TechSupply",     "Tecnologia",  "Hardware",    "(11) 96000-4444", "tech@email.com",     "São Paulo",      "https://techsupply.com.br", ""),
    ("AgroFértil",     "Agropecuária","Fertilizantes","(62) 95000-5555","agro@email.com",     "Goiânia",        "", ""),
    ("EletroWatt",     "Elétrica",    "Cabos",       "(31) 93000-7777", "eletro@email.com",   "Belo Horizonte", "", "31930007777"),
    ("LogiTrans",      "Logística",   "Transporte",  "(11) 92000-8888", "logi@email.com",     "Guarulhos",      "", "11920008888"),
    ("MetalForm",      "Metalurgia",  "Ferro",       "(11) 90000-0000", "metal@email.com",    "Santo André",    "", ""),
    ("DataSoft",       "Tecnologia",  "Software",    "(41) 89000-1212", "data@email.com",     "Curitiba",       "https://datasoft.com.br", ""),
    ("QuimiBras",      "Química",     "Solventes",   "(13) 88000-1313", "quimibras@email.com","Santos",         "", ""),
]

for f in fornecedores:
    nome, cat_nome, sub_nome = f[0], f[1], f[2]
    cat_id = cat_ids.get(cat_nome)
    sub_row = conn.execute("SELECT id FROM subcategorias WHERE nome=? AND categoria_id=?", (sub_nome, cat_id)).fetchone()
    sub_id  = sub_row[0] if sub_row else None
    conn.execute("""INSERT INTO fornecedores (nome,categoria_id,subcategoria_id,contato,email,cidade,site,whatsapp)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (nome, cat_id, sub_id, f[3], f[4], f[5], f[6], f[7]))

conn.commit()
conn.close()
print("✅ Banco populado com sucesso!")
print("\nLogin padrão:")
print("  E-mail: admin@sistema.com")
print("  Senha:  admin123")
