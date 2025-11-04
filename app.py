import os
import re
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_ 
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
from urllib.parse import quote 

# --- 1. CONFIGURAÇÃO INICIAL ---

# ****** MUDANÇA IMPORTANTE PARA O RENDER.COM ******
# Procura pelo "Disco Persistente" do Render. Se não achar, usa o diretório local.
DATA_DIR = os.environ.get('RENDER_DISK_MOUNT_PATH', '.')
database_file = "sqlite:///{}".format(os.path.join(DATA_DIR, "database.db"))
# ****** FIM DA MUDANÇA ******

app = Flask(__name__)
app.config["SECRET_KEY"] = "SUA_CHAVE_SECRETA_MUITO_SEGURA_AQUI"
app.config["SQLALCHEMY_DATABASE_URI"] = database_file
db = SQLAlchemy(app)

# --- 2. MODELO DO BANCO DE DADOS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    apelido = db.Column(db.String(80), unique=True, nullable=False)
    telefone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=True) 
    password_hash = db.Column(db.String(128), nullable=False)
    produto = db.Column(db.String(50), nullable=False)
    periodo = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pendente') # pendente, ativo, inativo
    data_vencimento = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    assinaturas = db.relationship('Assinatura', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Assinatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_nome = db.Column(db.String(100), nullable=False)
    variacao = db.Column(db.String(100), nullable=True) 
    data_inicio = db.Column(db.DateTime, nullable=False)
    data_vencimento = db.Column(db.DateTime, nullable=True) 
    status = db.Column(db.String(20), nullable=False, default='ativa') # ativa, inativa
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# --- 3. ROTAS (O QUE CADA LINK FAZ) ---

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        telefone_raw = request.form['telefone']
        senha = request.form['senha']
        
        telefone = re.sub(r'\D', '', telefone_raw)
        
        user = User.query.filter_by(telefone=telefone).first() 

        if not user or not user.check_password(senha):
            flash('Telefone ou senha inválidos.', 'error')
            return redirect(url_for('login'))
        
        if user.status == 'pendente':
            flash('Sua conta ainda está pendente de aprovação.', 'error')
            return redirect(url_for('login'))
            
        if user.status == 'inativo':
            flash('Sua conta foi desativada pelo administrador.', 'error')
            return redirect(url_for('login'))

        session['user_id'] = user.id
        session['user_apelido'] = user.apelido
        session['is_admin'] = user.is_admin

        if user.is_admin:
            return redirect(url_for('admin_pendentes'))
        else:
            return redirect(url_for('painel_cliente'))

    return render_template('login.html')

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        try:
            apelido = request.form['nickname']
            telefone_raw = request.form['phone'] 
            senha = request.form['password']
            produto = request.form['product']
            periodo = request.form['period']
            email = request.form.get('email') 

            if produto == 'other':
                produto = request.form.get('other_product', 'Outro')

            telefone = re.sub(r'\D', '', telefone_raw)

            if User.query.filter_by(telefone=telefone).first(): 
                flash('Este telefone já está cadastrado.', 'error')
                return redirect(url_for('cadastro'))
            if User.query.filter_by(apelido=apelido).first():
                flash('Este apelido já está em uso.', 'error')
                return redirect(url_for('cadastro'))

            new_user = User(
                apelido=apelido,
                telefone=telefone, 
                email=email,
                produto=produto,
                periodo=periodo
            )
            new_user.set_password(senha)
            
            if User.query.count() == 0:
                new_user.is_admin = True
                new_user.status = 'ativo' 

            db.session.add(new_user)
            db.session.commit()
            
            flash('Cadastro enviado! Aguarde aprovação do administrador.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            flash(f'Erro ao cadastrar: {e}', 'error')
            return redirect(url_for('cadastro'))

    return render_template('cadastro.html')

@app.route('/logout')
def logout():
    session.clear() 
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))

@app.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if request.method == 'POST':
        telefone_raw = request.form['telefone']
        
        mensagem = f"Olá, esqueci minha senha. Meu número de telefone cadastrado é: {telefone_raw}. Por favor, me ajude a redefinir."
        mensagem_encodada = quote(mensagem)
        whatsapp_url = f"https://api.whatsapp.com/send?phone=5511914853814&text={mensagem_encodada}"
        
        return redirect(whatsapp_url)

    return render_template('esqueci_senha.html')

# --- 4. ROTAS DO PAINEL DO CLIENTE ---

@app.route('/painel')
def painel_cliente():
    if 'user_id' not in session:
        flash('Você precisa estar logado para ver esta página.', 'error')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('logout'))

    today = datetime.datetime.utcnow()
    
    dias_restantes_principal = "N/D"
    if user.periodo == 'lifetime':
        dias_restantes_principal = "Vitalício"
    elif user.data_vencimento:
        delta = user.data_vencimento - today
        dias_restantes_principal = (delta.days + 1) if delta.total_seconds() > 0 else 0

    garantia_restante_principal = 0
    if user.periodo == 'monthly':
        garantia_fim = user.data_criacao + datetime.timedelta(days=30)
        if garantia_fim > today:
            garantia_dias = (garantia_fim - today).days
            garantia_restante_principal = garantia_dias + 1
    elif user.periodo == 'lifetime':
        garantia_fim = user.data_criacao + datetime.timedelta(days=365) # 12 meses
        if garantia_fim > today:
            garantia_dias = (garantia_fim - today).days
            garantia_restante_principal = garantia_dias + 1

    assinaturas_processadas = []
    for assinatura in user.assinaturas:
        dias_restantes_assinatura = "N/D"
        if assinatura.variacao == 'vitalicio':
            dias_restantes_assinatura = "Vitalício"
        elif assinatura.data_vencimento:
            delta = assinatura.data_vencimento - today
            dias_restantes_assinatura = (delta.days + 1) if delta.total_seconds() > 0 else 0
        
        garantia_restante_assinatura = 0
        if assinatura.variacao == 'mensal':
            garantia_fim = assinatura.data_inicio + datetime.timedelta(days=30)
            if garantia_fim > today:
                garantia_dias = (garantia_fim - today).days
                garantia_restante_assinatura = garantia_dias + 1
        elif assinatura.variacao == 'vitalicio':
            garantia_fim = assinatura.data_inicio + datetime.timedelta(days=365) # 12 meses
            if garantia_fim > today:
                garantia_dias = (garantia_fim - today).days
                garantia_restante_assinatura = garantia_dias + 1
        
        assinaturas_processadas.append({
            'obj': assinatura,
            'dias_restantes': dias_restantes_assinatura,
            'garantia_restante': garantia_restante_assinatura
        })

    return render_template('painel_cliente.html', 
                           usuario=user, 
                           dias_restantes_principal=dias_restantes_principal,
                           garantia_restante_principal=garantia_restante_principal,
                           assinaturas_processadas=assinaturas_processadas)

@app.route('/mudar-senha', methods=['GET', 'POST'])
def mudar_senha():
    if 'user_id' not in session:
        flash('Você precisa estar logado para ver esta página.', 'error')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('logout'))

    if request.method == 'POST':
        senha_antiga = request.form['senha_antiga']
        nova_senha = request.form['nova_senha']

        if not user.check_password(senha_antiga):
            flash('Sua senha antiga está incorreta.', 'error')
            return redirect(url_for('mudar_senha'))
        
        try:
            user.set_password(nova_senha)
            db.session.commit()
            flash('Senha alterada com sucesso!', 'success')
            return redirect(url_for('mudar_senha'))
        except Exception as e:
            flash(f'Erro ao alterar senha: {e}', 'error')
            return redirect(url_for('mudar_senha'))

    return render_template('cliente_mudar_senha.html', usuario=user)

# --- 5. ROTAS DO PAINEL DO ADMIN ---

def check_admin():
    if not session.get('is_admin'):
        flash('Acesso negado. Você não é um administrador.', 'error')
        return redirect(url_for('login'))

@app.route('/admin')
@app.route('/admin/pendentes')
def admin_pendentes():
    # check_admin() 
    
    usuarios_pendentes = User.query.filter_by(status='pendente').all()
    
    return render_template('admin_pendentes.html', usuarios=usuarios_pendentes)

@app.route('/admin/clientes')
def admin_clientes():
    # check_admin() 
    
    usuarios = User.query.filter(User.status.in_(['ativo', 'inativo'])).all()
    
    return render_template('admin_clientes.html', usuarios=usuarios)

@app.route('/admin/logs')
def admin_logs():
    # check_admin() 
    return render_template('admin_logs.html')

@app.route('/admin/rejeitados')
def admin_rejeitados():
    # check_admin() 
    
    usuarios_rejeitados = User.query.filter_by(status='inativo').all()
    
    return render_template('admin_rejeitados.html', usuarios=usuarios_rejeitados)


# --- 6. AÇÕES DO ADMIN ---

@app.route('/admin/aprovar/<int:user_id>')
def aprovar_usuario(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if user and user.status == 'pendente':
        user.status = 'ativo'
        
        if user.periodo == 'monthly':
            user.data_vencimento = datetime.datetime.utcnow() + datetime.timedelta(days=30)
            
        db.session.commit()
        flash(f'Usuário {user.apelido} aprovado.', 'success')
    else:
        flash('Usuário não encontrado ou já processado.', 'error')
        
    return redirect(url_for('admin_pendentes'))

@app.route('/admin/rejeitar/<int:user_id>')
def rejeitar_usuario(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if user and user.status == 'pendente':
        user.status = 'inativo'
        db.session.commit()
        flash(f'Usuário {user.apelido} rejeitado.', 'success')
    else:
        flash('Usuário não encontrado ou já processado.', 'error')
        
    return redirect(url_for('admin_pendentes'))

@app.route('/admin/adicionar-dias/<int:user_id>', methods=['GET', 'POST'])
def adicionar_dias(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))

    if request.method == 'POST':
        try:
            dias_a_adicionar = int(request.form['dias'])
            
            data_base = user.data_vencimento
            if not data_base or data_base < datetime.datetime.utcnow():
                data_base = datetime.datetime.utcnow()

            user.data_vencimento = data_base + datetime.timedelta(days=dias_a_adicionar)
                
            db.session.commit()
            flash(f'{dias_a_adicionar} dias adicionados para {user.apelido}.', 'success')
            return redirect(url_for('admin_clientes'))
            
        except Exception as e:
            flash(f'Erro ao adicionar dias: {e}', 'error')
            return redirect(url_for('adicionar_dias', user_id=user_id))

    return render_template('admin_adicionar_dias.html', usuario=user)

@app.route('/admin/toggle-status/<int:user_id>')
def toggle_status(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    
    if user.status == 'ativo':
        user.status = 'inativo'
        flash(f'Usuário {user.apelido} foi DESATIVADO (produto retirado).', 'success')
    elif user.status == 'inativo':
        user.status = 'ativo'
        flash(f'Usuário {user.apelido} foi ATIVADO.', 'success')
    else:
        flash(f'Não é possível alterar o status de um usuário {user.status}.', 'error')

    db.session.commit()
    return redirect(url_for('admin_clientes'))

@app.route('/admin/editar-datas/<int:user_id>', methods=['GET', 'POST'])
def editar_datas(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))

    if request.method == 'POST':
        data_str = request.form['data_vencimento']
        try:
            nova_data = datetime.datetime.strptime(data_str, '%Y-%m-%d')
            
            user.data_vencimento = nova_data.replace(hour=23, minute=59, second=59)
            
            db.session.commit()
            flash(f'Data de vencimento de {user.apelido} atualizada para {data_str}.', 'success')
            return redirect(url_for('admin_clientes'))
            
        except Exception as e:
            flash(f'Formato de data inválido: {e}', 'error')
            return redirect(url_for('editar_datas', user_id=user_id))

    data_atual = (user.data_vencimento or datetime.date.today()).strftime('%Y-%m-%d')
    return render_template('admin_editar_datas.html', usuario=user, data_atual=data_atual)

@app.route('/admin/trocar-plano/<int:user_id>', methods=['GET', 'POST'])
def trocar_plano(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))

    if request.method == 'POST':
        novo_produto = request.form['produto']
        novo_periodo = request.form['periodo']
        
        if not novo_produto:
            flash('O nome do produto não pode estar vazio.', 'error')
            return redirect(url_for('trocar-plano', user_id=user_id))

        try:
            user.produto = novo_produto
            user.periodo = novo_periodo
            
            db.session.commit()
            flash(f'Plano de {user.apelido} atualizado para {novo_produto} ({novo_periodo}).', 'success')
            return redirect(url_for('admin_clientes'))
            
        except Exception as e:
            flash(f'Erro ao trocar plano: {e}', 'error')
            return redirect(url_for('trocar-plano', user_id=user_id))

    return render_template('admin_trocar_plano.html', usuario=user)

@app.route('/admin/detalhes/<int:user_id>')
def detalhes_cliente(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    
    return render_template('admin_detalhes.html', usuario=user, datetime=datetime)

@app.route('/admin/enviar-aviso/<int:user_id>', methods=['GET', 'POST'])
def enviar_aviso(user_id):
    # check_admin() 
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))

    if request.method == 'POST':
        mensagem = request.form['mensagem']
        
        if not mensagem:
            flash('A mensagem não pode estar vazia.', 'error')
            return redirect(url_for('enviar-aviso', user_id=user_id))
        
        # --- LÓGICA DE ENVIO (SIMULAÇÃO) ---
        print("------------------------------------------")
        print(f"--- SIMULAÇÃO DE ENVIO DE AVISO ---")
        print(f"Para: {user.apelido} ({user.telefone})")
        print(f"Mensagem: {mensagem}")
        print("------------------------------------------")
        # --- FIM DA SIMULAÇÃO ---
            
        flash(f'Aviso enviado para {user.apelido}.', 'success')
        return redirect(url_for('admin_clientes'))

    return render_template('admin_enviar_aviso.html', usuario=user)

@app.route('/admin/adicionar', methods=['GET', 'POST'])
def admin_adicionar_cliente():
    # check_admin()
    
    if request.method == 'POST':
        try:
            apelido = request.form['apelido']
            telefone_raw = request.form['telefone']
            senha = request.form['senha']
            produto = request.form['produto']
            periodo = request.form['periodo']
            status = request.form['status']
            
            telefone = re.sub(r'\D', '', telefone_raw)

            if not apelido or not telefone or not senha or not produto:
                flash('Todos os campos obrigatórios devem ser preenchidos.', 'error')
                return redirect(url_for('admin_adicionar_cliente'))

            if User.query.filter_by(telefone=telefone).first(): 
                flash('Este telefone já está cadastrado.', 'error')
                return redirect(url_for('admin_adicionar_cliente'))
            if User.query.filter_by(apelido=apelido).first():
                flash('Este apelido já está em uso.', 'error')
                return redirect(url_for('admin_adicionar_cliente'))

            new_user = User(
                apelido=apelido,
                telefone=telefone,
                email=None, 
                produto=produto,
                periodo=periodo,
                status=status 
            )
            new_user.set_password(senha)
            
            if periodo == 'monthly' and status == 'ativo':
                new_user.data_vencimento = datetime.datetime.utcnow() + datetime.timedelta(days=30)

            db.session.add(new_user)
            db.session.commit()
            
            flash(f'Novo cliente "{apelido}" criado com sucesso!', 'success')
            return redirect(url_for('admin_clientes'))

        except Exception as e:
            flash(f'Erro ao criar cliente: {e}', 'error')
            return redirect(url_for('admin_adicionar_cliente'))

    return render_template('admin_adicionar.html')

@app.route('/admin/aviso-todos', methods=['GET', 'POST'])
def aviso_todos():
    # check_admin()
    
    usuarios = User.query.filter(User.status.in_(['ativo', 'inativo'])).all()
    count_usuarios = len(usuarios)

    if request.method == 'POST':
        mensagem = request.form['mensagem']
        
        if not mensagem:
            flash('A mensagem não pode estar vazia.', 'error')
            return redirect(url_for('aviso_todos'))
        
        # --- LÓGICA DE ENVIO (SIMULAÇÃO) ---
        print("**********************************************")
        print(f"--- SIMULAÇÃO DE ENVIO DE AVISO EM MASSA ---")
        print(f"Mensagem: {mensagem}")
        print(f"Enviando para {count_usuarios} clientes:")
        for user in usuarios:
            print(f"-> {user.apelido} ({user.telefone})")
        print("**********************************************")
        # --- FIM DA SIMULAÇÃO ---
            
        flash(f'Aviso em massa enviado para {count_usuarios} clientes.', 'success')
        return redirect(url_for('admin_clientes'))

    return render_template('admin_aviso_todos.html', count_usuarios=count_usuarios)

@app.route('/admin/adicionar-assinatura/<int:user_id>', methods=['POST'])
def adicionar_assinatura(user_id):
    # check_admin()
    
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    
    try:
        produto_nome = request.form['produto_nome']
        variacao = request.form['variation'] 
        data_inicio_str = request.form['start_date']

        if produto_nome == 'outro':
            produto_nome = request.form.get('produto_outro')
            if not produto_nome:
                flash('Você selecionou "Outro" mas não digitou um nome de produto.', 'error')
                return redirect(url_for('detalhes_cliente', user_id=user_id))

        if not produto_nome or not variacao or not data_inicio_str:
            flash('Erro: Dados incompletos do formulário.', 'error')
            return redirect(url_for('detalhes_cliente', user_id=user_id))

        data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d')
        
        data_vencimento = None
        if variacao == 'mensal':
            data_vencimento = data_inicio + datetime.timedelta(days=30)
        elif variacao == 'trimestral':
            data_vencimento = data_inicio + datetime.timedelta(days=90)
        elif variacao == 'anual':
            data_vencimento = data_inicio + datetime.timedelta(days=365)

        nova_assinatura = Assinatura(
            produto_nome=produto_nome,
            variacao=variacao,
            data_inicio=data_inicio,
            data_vencimento=data_vencimento, 
            status='ativa',
            user_id=user.id
        )
        
        db.session.add(nova_assinatura)
        db.session.commit()
        
        flash(f'Nova assinatura "{produto_nome}" adicionada para {user.apelido}.', 'success')
        
    except Exception as e:
        db.session.rollback() 
        flash(f'Erro ao adicionar assinatura: {e}', 'error')
        
    return redirect(url_for('detalhes_cliente', user_id=user_id))

@app.route('/admin/detalhes/downloads/<int:user_id>')
def detalhes_downloads(user_id):
    # check_admin()
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    return render_template('admin_detalhes_downloads.html', usuario=user)

@app.route('/admin/detalhes/tickets/<int:user_id>')
def detalhes_tickets(user_id):
    # check_admin()
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    return render_template('admin_detalhes_tickets.html', usuario=user)

@app.route('/admin/detalhes/seguranca/<int:user_id>')
def detalhes_seguranca(user_id):
    # check_admin()
    user = User.query.get(user_id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_clientes'))
    return render_template('admin_detalhes_seguranca.html', usuario=user)


# --- 7. COMANDO PARA CRIAR O BANCO DE DADOS ---
@app.cli.command("init-db")
def init_db_command():
    """Cria as tabelas do banco de dados."""
    with app.app_context():
        db.create_all()
    print("Banco de dados inicializado.")

# --- 8. RODAR A APLICAÇÃO ---
if __name__ == '__main__':
    with app.app_context():
        # Cria as tabelas ANTES de rodar
        db.create_all()
    
    # Roda o app na porta 8080 para testes locais
    app.run(host='0.0.0.0', port=8080, debug=True)
