from functools import wraps
import hashlib
import re
import logging
import json
import base64
import binascii
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import bcrypt, db
from models import Acao, AdvertenciaAdmin, Desmanche, ExtratoPonto, LogAdmin, MetaSemanalUsuario, Notificacao, Operacao, PerfilGame, PerfilSetor, SolicitacaoCorrecao, SolicitacaoPerfilGame, Usuario


logger = logging.getLogger(__name__)

FUSO_LOCAL = ZoneInfo("America/Fortaleza")

CARGOS = {
    "Funcionário": 50,
    "Vendedor": 40,
    "Financista": 30,
    "Contador": 20,
    "Doleiro": None,
}

ORDEM_CARGOS = list(CARGOS.keys())

CARGOS_ACAO_CADASTRO = [
    "Lanterninha",
    "Olheiro",
    "Cobrador",
    "Soldado",
    "Capanga",
    "Tenente de Rua",
]

CARGOS_GERENCIA = [
    "Sub Gerente",
    "Chefe de Setor",
    "Alto Conselho",
]


TODOS_CARGOS = (
    ORDEM_CARGOS
    + CARGOS_ACAO_CADASTRO
    + CARGOS_GERENCIA
)


def setor_do_cargo(cargo):
    """
    Retorna exatamente um setor para exatamente um cargo.
    """
    if cargo in CARGOS:
        return "lavagem"

    if cargo in CARGOS_ACAO_CADASTRO:
        return "acao"

    if cargo in CARGOS_GERENCIA:
        return "gerencia"

    return None


def sincronizar_perfil_cargo_unico(usuario, perfil=None):
    """
    Mantém PerfilSetor compatível com a base antiga,
    mas Usuario.cargo é a única fonte oficial do cargo.

    Regras:
    - Lavagem: setor_lavagem=True, setor_acao=False
    - Ação: setor_lavagem=False, setor_acao=True
    - Gerência: setor_lavagem=False, setor_acao=False
    - Nunca ambos.
    """
    if perfil is None:
        perfil = PerfilSetor.query.filter_by(
            usuario_id=usuario.id
        ).first()

    if perfil is None:
        perfil = PerfilSetor(
            usuario_id=usuario.id,
            setor_lavagem=False,
            setor_acao=False,
            cargo_acao=None,
            impulsos_acao=0,
            impulsos_lavagem=0,
        )
        db.session.add(perfil)

    # Migração automática da estrutura antiga:
    # contas de Ação/Gerência eram salvas como "Funcionário"
    # em Usuario.cargo e o cargo real ficava em perfil.cargo_acao.
    cargo_legado = (
        perfil.cargo_acao
        if perfil.cargo_acao in (
            CARGOS_ACAO_CADASTRO
            + CARGOS_GERENCIA
        )
        else None
    )

    if (
        cargo_legado
        and perfil.setor_acao
        and usuario.cargo in CARGOS
    ):
        usuario.cargo = cargo_legado

    setor = setor_do_cargo(
        usuario.cargo
    )

    perfil.setor_lavagem = (
        setor == "lavagem"
    )

    perfil.setor_acao = (
        setor == "acao"
    )

    # Compatibilidade apenas para telas antigas de Ação.
    # Gerência é separada e não usa cargo_acao.
    perfil.cargo_acao = (
        usuario.cargo
        if setor == "acao"
        else None
    )

    return perfil


METAS_ORGANIZACAO = {
 "Funcionário":{"normal":(100,100,5000000),"1":(80,80,4000000),"2":(50,50,2500000)},
 "Vendedor":{"normal":(90,90,4500000),"1":(72,72,3600000),"2":(45,45,2225000)},
 "Financista":{"normal":(80,80,4000000),"1":(64,64,3200000),"2":(40,40,2000000)},
 "Contador":{"normal":(70,70,3500000),"1":(56,56,2800000),"2":(35,35,1750000)},
 "Doleiro":{"normal":(50,50,3000000),"1":(40,40,2400000),"2":(25,25,1500000)},
}
FUNCOES_CARGOS = {
 "Funcionário":"Membro da organização responsável por executar tarefas operacionais específicas, seguindo as orientações da liderança e mantendo a eficiência nas atividades designadas.",
 "Vendedor":"Responsável pela área comercial, atuando na captação de clientes, negociação e expansão dos serviços, contribuindo diretamente para o crescimento da organização.",
 "Financista":"Possui acesso à máquina e é especialista na área financeira, com acesso aos sistemas principais. É responsável pela gestão, controlo e organização dos recursos financeiros.",
 "Contador":"Administra toda a estrutura e os colaboradores da linha financeira, supervisionando atividades, acompanhando desempenho e propondo melhorias contínuas para o setor.",
 "Doleiro":"Responsável por supervisionar a equipe, auxiliar os membros, organizar a área e garantir a proteção do local. Atua diretamente no suporte das operações, organização das funções e no crescimento da equipe e dos lucros.",
}
def meta_organizacao(cargo, impulsos=0):
    v=METAS_ORGANIZACAO.get(cargo, METAS_ORGANIZACAO["Funcionário"])[str(impulsos) if impulsos in (1,2) else "normal"]
    return {"papeis":v[0],"spray":v[1],"sujo":v[2]}


MENSAGENS_PROMOCAO = {
    "Vendedor": "Parabéns pela evolução para Vendedor! Seu compromisso fortalece toda a equipe. Continue somando, ajudando os companheiros e construindo resultados junto com todos.",
    "Financista": "Parabéns pela promoção para Financista! Sua constância mostra o valor do trabalho em equipe. Continue compartilhando experiência e crescendo junto com seus companheiros.",
    "Contador": "Parabéns por chegar a Contador! Essa conquista representa dedicação e parceria. Continue sendo referência, apoiando a equipe e mantendo o companheirismo em cada meta.",
    "Doleiro": "Parabéns por alcançar Doleiro! Você chegou a uma etapa de grande confiança. Continue valorizando a equipe, ajudando seus companheiros e mostrando preparo para novas responsabilidades e um possível convite à Gerência.",
}


def limpar_texto(valor, limite=None):
    texto = str(valor or "").strip()
    return texto[:limite] if limite is not None else texto


def converter_decimal(valor, campo):
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError) as erro:
        raise ValueError(f"O campo '{campo}' possui um valor inválido.") from erro
    if not numero.is_finite():
        raise ValueError(f"O campo '{campo}' possui um valor inválido.")
    return numero



def decodificar_imagem_base64(valor, campo):
    """Recebe data:image/...;base64,... e retorna bytes + MIME."""
    if not valor:
        return None, None
    if not isinstance(valor, str) or not valor.startswith("data:image/"):
        raise ValueError(f"O {campo} não é uma imagem válida.")
    try:
        cabecalho, conteudo = valor.split(",", 1)
        mime = cabecalho.split(";", 1)[0].split(":", 1)[1].strip().lower()
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/bmp"}:
            raise ValueError(f"O formato do {campo} não é permitido.")
        dados = base64.b64decode(conteudo, validate=True)
    except (ValueError, binascii.Error) as erro:
        raise ValueError(f"Não foi possível ler o {campo}.") from erro
    if len(dados) > 7 * 1024 * 1024:
        raise ValueError(f"O {campo} ultrapassa 7 MB.")
    return dados, mime


def resposta_erro(mensagem, status=400):
    return jsonify({"sucesso": False, "erro": mensagem}), status


def agora_local():
    return datetime.now(FUSO_LOCAL)


def periodo_semana(referencia=None):
    """Retorna domingo 00:00 até o próximo domingo 00:00 no fuso de Fortaleza."""
    referencia = referencia or agora_local()
    if referencia.tzinfo is None:
        referencia = referencia.replace(tzinfo=FUSO_LOCAL)
    else:
        referencia = referencia.astimezone(FUSO_LOCAL)

    # weekday(): segunda=0 ... domingo=6
    dias_desde_domingo = (referencia.weekday() + 1) % 7
    data_inicio = referencia.date() - timedelta(days=dias_desde_domingo)
    inicio_local = datetime.combine(data_inicio, time.min, tzinfo=FUSO_LOCAL)
    fim_local = inicio_local + timedelta(days=7)
    return inicio_local, fim_local


def garantir_cargo_valido(usuario):
    """
    Valida qualquer cargo oficial.
    Não converte cargos de Ação/Gerência para Funcionário.
    """
    if usuario.cargo in TODOS_CARGOS:
        return False

    usuario.cargo = "Funcionário"
    return True


def obter_meta_semana(usuario_id, criar=True):
    inicio_local, fim_local = periodo_semana()
    inicio_data = inicio_local.date()

    registro = MetaSemanalUsuario.query.filter_by(
        usuario_id=usuario_id,
        inicio_semana=inicio_data,
    ).first()

    if registro is None and criar:
        registro = MetaSemanalUsuario(
            usuario_id=usuario_id,
            inicio_semana=inicio_data,
            meta_entregue=False,
            impulsos=0,
        )
        db.session.add(registro)
        db.session.commit()

    return registro, inicio_local, fim_local


def resumo_meta_semanal(usuario):
    registro, inicio_local, fim_local = obter_meta_semana(
        usuario.id,
        criar=True,
    )

    inicio_utc = inicio_local.astimezone(
        timezone.utc
    )

    fim_utc = fim_local.astimezone(
        timezone.utc
    )

    lavagens = Operacao.query.filter(
        Operacao.usuario_id == usuario.id,
        Operacao.criado_em >= inicio_utc,
        Operacao.criado_em < fim_utc,
    ).count()

    setor = setor_do_cargo(
        usuario.cargo
    )

    # Apenas cargos de Lavagem possuem meta de Lavagem.
    if setor != "lavagem":
        return {
            "cargo": usuario.cargo,
            "setor": setor,
            "meta": None,
            "lavagens": lavagens,
            "faltam": 0,
            "percentual": 0,
            "meta_entregue": False,
            "impulsos": 0,
            "meta_org": {
                "papeis": 0,
                "spray": 0,
                "sujo": 0,
            },
            "funcao": "",
            "apto": False,
            "status": (
                "Cargo pertencente ao setor de "
                + (
                    "Ação"
                    if setor == "acao"
                    else "Gerência"
                    if setor == "gerencia"
                    else "não definido"
                )
            ),
            "inicio": inicio_local,
            "fim_exclusivo": fim_local,
            "fim_exibicao": (
                fim_local
                - timedelta(minutes=1)
            ),
        }

    meta = CARGOS.get(
        usuario.cargo
    )

    meta_entregue = bool(
        registro.meta_entregue
    )

    impulsos = (
        registro.impulsos
        if registro.impulsos in (0, 1, 2)
        else 0
    )

    meta_org = meta_organizacao(
        usuario.cargo,
        impulsos,
    )

    if meta is None:
        faltam = 0
        percentual = 100
        apto = False
        status = "Possível convite para Gerência"

    else:
        faltam = max(
            meta - lavagens,
            0,
        )

        percentual = (
            min(
                round(
                    (
                        lavagens
                        / meta
                    )
                    * 100
                ),
                100,
            )
            if meta
            else 100
        )

        apto = (
            lavagens >= meta
            and meta_entregue
        )

        if apto:
            status = "Apto para upamento"
        elif (
            lavagens >= meta
            and not meta_entregue
        ):
            status = (
                "Quantidade atingida — "
                "falta entregar a meta"
            )
        else:
            status = (
                f"Faltam {faltam} lavagens"
            )

    return {
        "cargo": usuario.cargo,
        "setor": setor,
        "meta": meta,
        "lavagens": lavagens,
        "faltam": faltam,
        "percentual": percentual,
        "meta_entregue": meta_entregue,
        "impulsos": impulsos,
        "meta_org": meta_org,
        "funcao": FUNCOES_CARGOS.get(
            usuario.cargo,
            "",
        ),
        "apto": apto,
        "status": status,
        "inicio": inicio_local,
        "fim_exclusivo": fim_local,
        "fim_exibicao": (
            fim_local
            - timedelta(minutes=1)
        ),
    }




def obter_perfil_game(usuario_id):
    return PerfilGame.query.filter_by(usuario_id=usuario_id).first()


def obter_solicitacao_perfil_pendente(usuario_id):
    return SolicitacaoPerfilGame.query.filter_by(
        usuario_id=usuario_id,
        status="pendente",
    ).order_by(SolicitacaoPerfilGame.solicitado_em.desc()).first()


def validar_dados_game(nome_game, id_game):
    nome = limpar_texto(nome_game, 100)
    identificador = limpar_texto(id_game, 30)

    if len(nome) < 2:
        raise ValueError("Informe seu nome no game.")
    if not re.fullmatch(r"[0-9]{1,12}", identificador):
        raise ValueError("O ID do game deve conter somente números.")
    return nome, identificador


def nome_membro_exibicao(usuario):
    perfil_game = obter_perfil_game(usuario.id)
    return perfil_game.nome_game if perfil_game else usuario.usuario




def criar_notificacao(usuario_id, titulo, mensagem, tipo="info"):
    notificacao = Notificacao(
        usuario_id=usuario_id,
        titulo=limpar_texto(titulo, 160),
        mensagem=limpar_texto(mensagem, 1200),
        tipo=limpar_texto(tipo, 40) or "info",
        lida=False,
    )
    db.session.add(notificacao)
    return notificacao


def total_notificacoes_nao_lidas(usuario_id):
    return Notificacao.query.filter_by(
        usuario_id=usuario_id,
        lida=False,
    ).count()


def registrar_log_admin(acao, alvo_usuario_id=None, detalhes=None):
    log = LogAdmin(
        admin_id=current_user.id if current_user.is_authenticated else None,
        alvo_usuario_id=alvo_usuario_id,
        acao=limpar_texto(acao, 80),
        detalhes=limpar_texto(detalhes, 1000),
    )
    db.session.add(log)


def advertencias_ativas(usuario_id):
    agora = datetime.now(timezone.utc)
    return AdvertenciaAdmin.query.filter(
        AdvertenciaAdmin.usuario_id == usuario_id,
        AdvertenciaAdmin.removida.is_(False),
        AdvertenciaAdmin.expira_em > agora,
    ).order_by(
        AdvertenciaAdmin.criado_em.desc()
    ).all()


def admin_required(funcao):
    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Acesso restrito à administração.", "erro")
            return redirect(url_for("dashboard"))
        return funcao(*args, **kwargs)
    return wrapper


def configurar_rotas(app):

    @app.context_processor
    def contexto_notificacoes():
        try:
            if current_user.is_authenticated:
                return {
                    "notificacoes_nao_lidas":
                        total_notificacoes_nao_lidas(current_user.id)
                }
        except Exception:
            pass
        return {"notificacoes_nao_lidas": 0}



    @app.context_processor
    def contexto_primeiro_admin():
        """
        Permite que a tela de login mostre o atalho somente enquanto
        ainda não existir nenhum administrador.
        """
        try:
            existe_admin = Usuario.query.filter_by(
                is_admin=True
            ).first() is not None
        except Exception:
            existe_admin = True

        return {
            "primeiro_admin_disponivel":
                not existe_admin
        }


    @app.route(
        "/primeiro-admin",
        methods=[
            "GET",
            "POST",
        ],
    )
    def primeiro_admin():
        """
        Assistente de configuração inicial.

        A rota funciona SOMENTE enquanto não houver nenhum usuário
        com is_admin=True. Assim que o primeiro ADM é criado, esta
        página é bloqueada automaticamente.
        """
        admin_existente = Usuario.query.filter_by(
            is_admin=True
        ).first()

        if admin_existente is not None:
            flash(
                "O administrador inicial já foi configurado.",
                "info",
            )

            if current_user.is_authenticated:
                return redirect(
                    url_for(
                        "admin_dashboard"
                        if getattr(
                            current_user,
                            "is_admin",
                            False,
                        )
                        else "dashboard"
                    )
                )

            return redirect(
                url_for(
                    "login"
                )
            )

        if request.method == "GET":
            return render_template(
                "primeiro_admin.html"
            )

        usuario = limpar_texto(
            request.form.get(
                "usuario"
            ),
            50,
        )

        nome_game = limpar_texto(
            request.form.get(
                "nome_game"
            ),
            100,
        )

        id_game = limpar_texto(
            request.form.get(
                "id_game"
            ),
            30,
        )

        senha = str(
            request.form.get(
                "senha"
            )
            or ""
        )

        confirmar = str(
            request.form.get(
                "confirmar_senha"
            )
            or ""
        )

        if (
            not usuario
            or not nome_game
            or not id_game
            or not senha
            or not confirmar
        ):
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Preencha usuário, Nome no Game, "
                    "ID no Game e as duas senhas."
                ),
                dados=request.form,
            )

        if len(usuario) < 3:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "O usuário precisa ter "
                    "pelo menos 3 caracteres."
                ),
                dados=request.form,
            )

        if len(nome_game) < 2:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Informe um Nome no Game válido."
                ),
                dados=request.form,
            )

        if len(senha) < 8:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "A senha do administrador deve "
                    "possuir pelo menos 8 caracteres."
                ),
                dados=request.form,
            )

        if senha != confirmar:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "As senhas não coincidem."
                ),
                dados=request.form,
            )

        usuario_existente = Usuario.query.filter(
            func.lower(
                Usuario.usuario
            )
            == usuario.lower()
        ).first()

        if usuario_existente is not None:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Esse usuário já está sendo usado "
                    "por outra conta."
                ),
                dados=request.form,
            )

        id_existente = PerfilGame.query.filter(
            func.lower(
                PerfilGame.id_game
            )
            == id_game.lower()
        ).first()

        if id_existente is not None:
            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Esse ID do Game já está vinculado "
                    "a outra conta."
                ),
                dados=request.form,
            )

        # Confere novamente imediatamente antes de gravar,
        # reduzindo a janela para criação simultânea de dois ADMs.
        if Usuario.query.filter_by(
            is_admin=True
        ).first() is not None:
            flash(
                "Outro administrador acabou de ser criado.",
                "info",
            )
            return redirect(
                url_for(
                    "login"
                )
            )

        try:
            novo_admin = Usuario(
                usuario=usuario,
                senha=bcrypt.generate_password_hash(
                    senha
                ).decode(
                    "utf-8"
                ),
                # Mantém compatibilidade com a lógica antiga
                # de cargos de Lavagem. A permissão real de ADM
                # é controlada exclusivamente por is_admin.
                cargo="Funcionário",
                ativo=True,
                is_admin=True,
            )

            db.session.add(
                novo_admin
            )

            db.session.flush()

            perfil_game = PerfilGame(
                usuario_id=
                    novo_admin.id,
                nome_game=
                    nome_game,
                id_game=
                    id_game,
            )

            perfil_setor = PerfilSetor(
                usuario_id=
                    novo_admin.id,
                setor_lavagem=False,
                setor_acao=False,
                cargo_acao=None,
                impulsos_acao=0,
                impulsos_lavagem=0,
            )

            db.session.add(
                perfil_game
            )

            db.session.add(
                perfil_setor
            )

            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Usuário ou ID do Game já existe. "
                    "Use outros dados."
                ),
                dados=request.form,
            )

        except SQLAlchemyError:
            db.session.rollback()

            logger.exception(
                "Erro de banco ao criar o primeiro administrador."
            )

            return render_template(
                "primeiro_admin.html",
                erro=(
                    "Não foi possível criar o administrador. "
                    "Tente novamente."
                ),
                dados=request.form,
            )

        login_user(
            novo_admin,
            remember=False,
        )

        flash(
            "Administrador criado com sucesso.",
            "sucesso",
        )

        return redirect(
            url_for(
                "admin_dashboard"
            )
        )


    @app.route("/")
    def inicio():
        return redirect(url_for("dashboard" if current_user.is_authenticated else "login"))

    @app.route("/cadastro", methods=["GET", "POST"])
    def cadastro():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "GET":
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA)

        usuario = limpar_texto(request.form.get("usuario"), 50)
        senha = str(request.form.get("senha") or "")
        confirmar_senha = str(request.form.get("confirmar_senha") or "")
        cargo_selecionado = limpar_texto(
            request.form.get("cargo"),
            80,
        )

        setor_cadastro = ""
        cargo_lavagem = None
        cargo_acao = None

        if cargo_selecionado.startswith("lavagem:"):
            cargo_lavagem = cargo_selecionado.split(":", 1)[1].strip()
            if cargo_lavagem in CARGOS:
                setor_cadastro = "lavagem"

        elif cargo_selecionado.startswith("acao:"):
            cargo_acao = cargo_selecionado.split(":", 1)[1].strip()
            if cargo_acao in CARGOS_ACAO_CADASTRO:
                setor_cadastro = "acao"

        elif cargo_selecionado.startswith("gerencia:"):
            cargo_acao = cargo_selecionado.split(":", 1)[1].strip()
            if cargo_acao in CARGOS_GERENCIA:
                setor_cadastro = "gerencia"

        if not usuario or not senha or not confirmar_senha or not setor_cadastro:
            return render_template(
                "cadastro.html",
                cargos_lavagem=ORDEM_CARGOS,
                cargos_acao=CARGOS_ACAO_CADASTRO,
                cargos_gerencia=CARGOS_GERENCIA,
                erro="Preencha todos os campos e selecione seu cargo atual.",
            )
        if len(usuario) < 3:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="O nome de usuário deve possuir pelo menos 3 caracteres.")
        if len(senha) < 6:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="A senha deve possuir pelo menos 6 caracteres.")
        if senha != confirmar_senha:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="As senhas não coincidem.")

        usuario_existente = Usuario.query.filter(func.lower(Usuario.usuario) == usuario.lower()).first()
        if usuario_existente:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="Este usuário já existe.")

        cargo_unico = (
            cargo_lavagem
            if setor_cadastro == "lavagem"
            else cargo_acao
        )

        novo_usuario = Usuario(
            usuario=usuario,
            senha=bcrypt.generate_password_hash(senha).decode("utf-8"),
            cargo=cargo_unico,
        )
        try:
            db.session.add(novo_usuario)
            db.session.flush()

            perfil = PerfilSetor(
                usuario_id=novo_usuario.id,
                setor_lavagem=False,
                setor_acao=False,
                cargo_acao=None,
                impulsos_acao=0,
                impulsos_lavagem=0,
            )

            db.session.add(perfil)

            sincronizar_perfil_cargo_unico(
                novo_usuario,
                perfil,
            )

            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="Este usuário já existe.")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro de banco ao cadastrar usuário.")
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, cargos_gerencia=CARGOS_GERENCIA, erro="Não foi possível concluir o cadastro.")

        flash("Conta criada com sucesso. Entre com seu usuário e senha.", "sucesso")
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "GET":
            return render_template("login.html")

        usuario = limpar_texto(request.form.get("usuario"), 50)
        senha = str(request.form.get("senha") or "")
        if not usuario or not senha:
            return render_template("login.html", erro="Preencha usuário e senha.")

        user = Usuario.query.filter(func.lower(Usuario.usuario) == usuario.lower()).first()
        if not user or not bcrypt.check_password_hash(user.senha, senha):
            return render_template("login.html", erro="Usuário ou senha inválidos.")
        if not user.ativo:
            return render_template("login.html", erro="Esta conta está desativada.")

        login_user(user, remember=False)
        try:
            alterou = garantir_cargo_valido(user)
            user.ultimo_login = datetime.now(timezone.utc)
            db.session.commit()
            if alterou:
                flash("Sua conta antiga foi definida como Funcionário. Você pode ajustar o cargo em Configurações.", "aviso")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Não foi possível atualizar o último login do usuário %s.", user.id)

        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        consulta_usuario = Operacao.query.filter_by(usuario_id=current_user.id)
        total_operacoes = consulta_usuario.count()
        valor_total = db.session.query(func.coalesce(func.sum(Operacao.valor), 0)).filter(Operacao.usuario_id == current_user.id).scalar()
        ganhos_total = db.session.query(func.coalesce(func.sum(Operacao.valor_porcentagem), 0)).filter(Operacao.usuario_id == current_user.id).scalar()
        ultimas_operacoes = consulta_usuario.order_by(Operacao.criado_em.desc(), Operacao.id.desc()).limit(10).all()
        progresso = resumo_meta_semanal(current_user)
        data_hoje = agora_local().strftime("%d/%m/%Y")
        total_acoes = Acao.query.filter_by(usuario_id=current_user.id).count()
        total_desmanches = Desmanche.query.filter_by(usuario_id=current_user.id).count()
        pontos_acao = db.session.query(func.coalesce(func.sum(ExtratoPonto.pontos), 0)).filter(ExtratoPonto.usuario_id == current_user.id, ExtratoPonto.categoria == "acao").scalar()

        return render_template(
            "dashboard.html",
            total_operacoes=total_operacoes,
            valor_total=valor_total,
            lucro_total=ganhos_total,
            ultimas_operacoes=ultimas_operacoes,
            progresso=progresso,
            data_hoje=data_hoje,
            total_acoes=total_acoes,
            total_desmanches=total_desmanches,
            pontos_acao=int(pontos_acao or 0),
        )

    @app.route("/salvar-operacao", methods=["POST"])
    @login_required
    def salvar_operacao():
        dados = request.get_json(silent=True)
        if not isinstance(dados, dict):
            return resposta_erro("Os dados enviados são inválidos.")

        nome_jogador = limpar_texto(dados.get("nome_jogador"), 100)
        id_jogador = limpar_texto(dados.get("id_jogador"), 50)
        observacoes = limpar_texto(dados.get("observacoes"), 2000)

        try:
            print_envio_dados, print_envio_mime = decodificar_imagem_base64(
                dados.get("print_envio_base64"),
                "print de envio",
            )
            print_recebimento_dados, print_recebimento_mime = decodificar_imagem_base64(
                dados.get("print_recebimento_base64"),
                "print de recebimento",
            )
        except ValueError as erro:
            return resposta_erro(str(erro))

        if not nome_jogador or nome_jogador in {"---", "Não identificado"}:
            return resposta_erro("O nome do jogador é inválido.")
        if not id_jogador or id_jogador in {"---", "Não identificado"}:
            return resposta_erro("O ID do jogador é inválido.")

        try:
            valor = converter_decimal(
                dados.get("valor"),
                "valor original",
            )
            valor_envio = converter_decimal(
                dados.get("valor_envio"),
                "valor enviado",
            )
        except ValueError as erro:
            return resposta_erro(str(erro))

        if valor <= 0:
            return resposta_erro(
                "O valor original da operação deve ser maior que zero."
            )

        if valor_envio <= 0:
            return resposta_erro(
                "O valor enviado deve ser maior que zero."
            )

        if valor_envio >= valor:
            return resposta_erro(
                "Os valores não conferem: o valor enviado precisa ser menor que o valor original."
            )

        ganho_calculado = (
            valor -
            valor_envio
        ).quantize(
            Decimal("0.01")
        )

        percentual_bruto = (
            ganho_calculado /
            valor *
            Decimal("100")
        )

        percentual_inteiro = Decimal(
            round(
                float(
                    percentual_bruto
                )
            )
        )

        distancia_inteiro = abs(
            percentual_bruto -
            percentual_inteiro
        )

        if (
            distancia_inteiro <=
            Decimal("0.35")
        ):
            percentual_positivo = (
                percentual_inteiro
            )
        else:
            percentual_positivo = (
                percentual_bruto
                .quantize(
                    Decimal("0.01")
                )
            )

        if (
            percentual_positivo <
            Decimal("20")
            or
            percentual_positivo >
            Decimal("40")
        ):
            return resposta_erro(
                "A porcentagem automática ficou fora de 20% a 40%. O OCR pode ter perdido algum zero."
            )

        # Recalcula o ganho pela taxa normalizada.
        ganho_calculado = (
            valor *
            percentual_positivo /
            Decimal("100")
        ).quantize(
            Decimal("0.01")
        )

        # Compatibilidade com o banco atual, que armazena taxa negativa.
        porcentagem = (
            -percentual_positivo
        ).quantize(
            Decimal("0.01")
        )

        data_exibicao = limpar_texto(
            dados.get("data_exibicao"),
            40,
        )

        if not data_exibicao:
            return resposta_erro(
                "A data e hora do print final não foram identificadas."
            )

        try:
            data_local = datetime.strptime(
                data_exibicao,
                "%d/%m/%Y %H:%M",
            ).replace(
                tzinfo=FUSO_LOCAL
            )

            criado_em_operacao = (
                data_local
                .astimezone(
                    timezone.utc
                )
            )
        except ValueError:
            return resposta_erro(
                "A data e hora extraídas do print estão em formato inválido."
            )

        nova_operacao = Operacao(
            usuario_id=current_user.id,
            nome_jogador=nome_jogador,
            id_jogador=id_jogador,
            valor=valor,
            valor_envio=valor_envio,
            porcentagem=porcentagem,
            valor_porcentagem=ganho_calculado,
            observacoes=observacoes,
            print_envio_dados=print_envio_dados,
            print_envio_mime=print_envio_mime,
            print_recebimento_dados=print_recebimento_dados,
            print_recebimento_mime=print_recebimento_mime,
            criado_em=criado_em_operacao,
        )
        try:
            db.session.add(nova_operacao)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro ao salvar operação.")
            return resposta_erro("Não foi possível salvar a operação.", 500)

        progresso = resumo_meta_semanal(current_user)
        return jsonify({
            "sucesso": True,
            "mensagem": "Operação salva com sucesso.",
            "operacao_id": nova_operacao.id,
            "lavagens_semana": progresso["lavagens"],
            "meta": progresso["meta"],
            "apto": progresso["apto"],
        }), 201


    @app.route("/admin")
    @login_required
    @admin_required
    def admin_dashboard():
        q = limpar_texto(
            request.args.get("q"),
            100,
        ).lower()

        filtro_status = limpar_texto(
            request.args.get("status", "todos"),
            20,
        )

        filtro_setor = limpar_texto(
            request.args.get("setor", "todos"),
            30,
        )

        if filtro_status not in {"todos", "ativo", "inativo", "adv", "pd"}:
            filtro_status = "todos"

        if filtro_setor not in {"todos", "lavagem", "acao", "gerencia"}:
            filtro_setor = "todos"

        usuarios = Usuario.query.filter(
            Usuario.is_admin.is_(False)
        ).order_by(
            Usuario.usuario.asc()
        ).all()

        membros = []

        houve_migracao_cargos = False

        for usuario in usuarios:
            perfil = PerfilSetor.query.filter_by(
                usuario_id=usuario.id
            ).first()

            cargo_antes = usuario.cargo
            cargo_secundario_antes = (
                perfil.cargo_acao
                if perfil
                else None
            )

            perfil = sincronizar_perfil_cargo_unico(
                usuario,
                perfil,
            )

            if (
                usuario.cargo != cargo_antes
                or (
                    perfil
                    and perfil.cargo_acao
                    != cargo_secundario_antes
                )
            ):
                houve_migracao_cargos = True

            perfil_game = obter_perfil_game(usuario.id)
            adv_ativas = advertencias_ativas(usuario.id)
            quantidade_adv = len(adv_ativas)

            total_lavagens = Operacao.query.filter_by(
                usuario_id=usuario.id
            ).count()

            total_acoes = Acao.query.filter_by(
                usuario_id=usuario.id
            ).count()

            total_desmanches = Desmanche.query.filter_by(
                usuario_id=usuario.id
            ).count()

            pontos_acao = db.session.query(
                func.coalesce(
                    func.sum(ExtratoPonto.pontos),
                    0
                )
            ).filter(
                ExtratoPonto.usuario_id == usuario.id,
                ExtratoPonto.categoria == "acao",
            ).scalar()

            pontos_lavagem = db.session.query(
                func.coalesce(
                    func.sum(ExtratoPonto.pontos),
                    0
                )
            ).filter(
                ExtratoPonto.usuario_id == usuario.id,
                ExtratoPonto.categoria == "lavagem",
            ).scalar()

            cargo = usuario.cargo
            setor = (
                setor_do_cargo(cargo)
                or "lavagem"
            )

            texto_busca = " ".join([
                usuario.usuario or "",
                perfil_game.nome_game if perfil_game else "",
                perfil_game.id_game if perfil_game else "",
                cargo or "",
            ]).lower()

            if q and q not in texto_busca:
                continue

            if filtro_status == "ativo" and not usuario.ativo:
                continue
            if filtro_status == "inativo" and usuario.ativo:
                continue
            if filtro_status == "adv" and quantidade_adv != 1:
                continue
            if filtro_status == "pd" and quantidade_adv < 2:
                continue
            if filtro_setor != "todos" and setor != filtro_setor:
                continue

            membros.append({
                "usuario": usuario,
                "perfil": perfil,
                "perfil_game": perfil_game,
                "lavagens": total_lavagens,
                "acoes": total_acoes,
                "desmanches": total_desmanches,
                "pontos_acao": int(pontos_acao or 0),
                "pontos_lavagem": int(pontos_lavagem or 0),
                "advertencias_ativas": adv_ativas,
                "quantidade_adv": quantidade_adv,
                "setor_exibicao": setor,
                "cargo_exibicao": cargo,
            })

        if houve_migracao_cargos:
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception(
                    "Erro ao consolidar cargos únicos no painel ADM."
                )

        total_membros = Usuario.query.filter(
            Usuario.is_admin.is_(False)
        ).count()

        total_acoes_geral = Acao.query.count()
        total_desmanches_geral = Desmanche.query.count()
        total_lavagens_geral = Operacao.query.count()

        solicitacoes_pendentes = SolicitacaoPerfilGame.query.filter_by(
            status="pendente"
        ).order_by(
            SolicitacaoPerfilGame.solicitado_em.asc()
        ).all()

        solicitacoes = [
            {
                "solicitacao": sol,
                "usuario": db.session.get(Usuario, sol.usuario_id),
            }
            for sol in solicitacoes_pendentes
        ]

        correcoes_pendentes = SolicitacaoCorrecao.query.filter_by(
            status="pendente"
        ).count()

        return render_template(
            "admin_dashboard.html",
            membros=membros,
            total_membros=total_membros,
            total_acoes_geral=total_acoes_geral,
            total_desmanches_geral=total_desmanches_geral,
            total_lavagens_geral=total_lavagens_geral,
            solicitacoes=solicitacoes,
            total_solicitacoes=len(solicitacoes),
            correcoes_pendentes=correcoes_pendentes,
            q=q,
            filtro_status=filtro_status,
            filtro_setor=filtro_setor,
        )

    @app.route(
        "/admin/membro/<int:usuario_id>/status",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_alterar_status_membro(usuario_id):
        membro = db.session.get(
            Usuario,
            usuario_id,
        )

        if membro is None:
            flash(
                "Membro não encontrado.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        if membro.id == current_user.id:
            flash(
                "Você não pode desativar a própria conta administrativa.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        if getattr(
            membro,
            "is_admin",
            False,
        ):
            flash(
                "O status de outro administrador não pode ser alterado por esta tela.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        acao = limpar_texto(
            request.form.get(
                "acao"
            ),
            20,
        )

        if acao not in {
            "ativar",
            "desativar",
        }:
            flash(
                "Ação administrativa inválida.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        membro.ativo = (
            acao == "ativar"
        )

        registrar_log_admin(
            "ALTERAR_STATUS",
            membro.id,
            f"Conta {'ativada' if membro.ativo else 'desativada'}.",
        )

        try:
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            logger.exception(
                "Erro ao alterar status do membro %s.",
                membro.id,
            )

            flash(
                "Não foi possível alterar o status da conta.",
                "erro",
            )

            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        flash(
            (
                "Conta reativada com sucesso."
                if membro.ativo
                else "Conta desativada com sucesso."
            ),
            "sucesso",
        )

        return redirect(
            url_for(
                "admin_dashboard"
            )
        )


    @app.route(
        "/admin/membro/<int:usuario_id>/apagar",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_apagar_membro(usuario_id):
        """
        PD = apagar permanentemente uma conta comum.

        Proteções:
        - não permite apagar a própria conta;
        - não permite apagar outro administrador;
        - exige confirmação digitada: APAGAR;
        - remove solicitações ligadas ao usuário antes da conta.
        """
        membro = db.session.get(
            Usuario,
            usuario_id,
        )

        if membro is None:
            flash(
                "Membro não encontrado.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        if membro.id == current_user.id:
            flash(
                "Você não pode apagar sua própria conta administrativa.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        if getattr(
            membro,
            "is_admin",
            False,
        ):
            flash(
                "Contas administrativas não podem ser apagadas por esta função.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        confirmacao = str(
            request.form.get(
                "confirmacao"
            )
            or ""
        ).strip().upper()

        if confirmacao != "APAGAR":
            flash(
                "Para apagar a conta, digite APAGAR na confirmação.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        nome_conta = membro.usuario

        try:
            # Solicitações possuem vínculo com o usuário e podem
            # impedir exclusão em bancos com integridade referencial.
            SolicitacaoPerfilGame.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            SolicitacaoCorrecao.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            Notificacao.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            # Extratos / módulos novos
            ExtratoPonto.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            Acao.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            Desmanche.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            PerfilGame.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            PerfilSetor.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            MetaSemanalUsuario.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            # Operações antigas normalmente usam cascade pelo relacionamento,
            # mas removemos explicitamente para deixar a função previsível.
            Operacao.query.filter_by(
                usuario_id=membro.id
            ).delete(
                synchronize_session=False
            )

            registrar_log_admin(
                "PD_APAGAR_CONTA",
                membro.id,
                f"Conta {nome_conta} apagada permanentemente.",
            )

            db.session.delete(
                membro
            )

            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            logger.exception(
                "Erro ao apagar permanentemente a conta %s.",
                usuario_id,
            )

            flash(
                "Não foi possível apagar a conta. Nenhuma alteração foi concluída.",
                "erro",
            )

            return redirect(
                url_for(
                    "admin_dashboard"
                )
            )

        flash(
            f"Conta '{nome_conta}' apagada permanentemente.",
            "sucesso",
        )

        return redirect(
            url_for(
                "admin_dashboard"
            )
        )



    @app.route(
        "/admin/membro/<int:usuario_id>/resetar-senha",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_resetar_senha(usuario_id):
        membro = db.session.get(Usuario, usuario_id)

        if membro is None:
            flash("Membro não encontrado.", "erro")
            return redirect(url_for("admin_dashboard"))

        if getattr(membro, "is_admin", False) and membro.id != current_user.id:
            flash("A senha de outro ADM não pode ser alterada por esta função.", "erro")
            return redirect(url_for("admin_dashboard"))

        nova_senha = str(request.form.get("nova_senha") or "")
        confirmar = str(request.form.get("confirmar_senha") or "")

        if len(nova_senha) < 8:
            flash("A nova senha deve ter pelo menos 8 caracteres.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        if nova_senha != confirmar:
            flash("As senhas não coincidem.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        membro.senha = bcrypt.generate_password_hash(
            nova_senha
        ).decode("utf-8")

        registrar_log_admin(
            "RESET_SENHA",
            membro.id,
            f"Senha da conta {membro.usuario} redefinida.",
        )

        criar_notificacao(
            membro.id,
            "Senha redefinida",
            "Sua senha foi redefinida pela administração.",
            "aviso",
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível redefinir a senha.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        flash("Senha redefinida com sucesso.", "sucesso")
        return redirect(url_for("admin_membro", usuario_id=membro.id))


    @app.route(
        "/admin/membro/<int:usuario_id>/cargo-setor",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_alterar_cargo_setor(usuario_id):
        membro = db.session.get(
            Usuario,
            usuario_id,
        )

        if membro is None:
            flash(
                "Membro não encontrado.",
                "erro",
            )
            return redirect(
                url_for("admin_dashboard")
            )

        if getattr(
            membro,
            "is_admin",
            False,
        ):
            flash(
                "Não altere cargo/setor de uma conta ADM por esta tela.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_membro",
                    usuario_id=membro.id,
                )
            )

        setor = limpar_texto(
            request.form.get("setor"),
            30,
        )

        if setor == "lavagem":
            cargo = limpar_texto(
                request.form.get(
                    "cargo_lavagem"
                ),
                60,
            )

            if cargo not in CARGOS:
                flash(
                    "Cargo de Lavagem inválido.",
                    "erro",
                )
                return redirect(
                    url_for(
                        "admin_membro",
                        usuario_id=membro.id,
                    )
                )

        elif setor == "acao":
            cargo = limpar_texto(
                request.form.get(
                    "cargo_acao"
                ),
                60,
            )

            if cargo not in CARGOS_ACAO_CADASTRO:
                flash(
                    "Cargo de Ação inválido.",
                    "erro",
                )
                return redirect(
                    url_for(
                        "admin_membro",
                        usuario_id=membro.id,
                    )
                )

        elif setor == "gerencia":
            cargo = limpar_texto(
                request.form.get(
                    "cargo_gerencia"
                ),
                60,
            )

            if cargo not in CARGOS_GERENCIA:
                flash(
                    "Cargo de Gerência inválido.",
                    "erro",
                )
                return redirect(
                    url_for(
                        "admin_membro",
                        usuario_id=membro.id,
                    )
                )

        else:
            flash(
                "Setor inválido. Cada membro deve pertencer a apenas um setor.",
                "erro",
            )
            return redirect(
                url_for(
                    "admin_membro",
                    usuario_id=membro.id,
                )
            )

        cargo_anterior = (
            membro.cargo
        )

        membro.cargo = cargo

        perfil = sincronizar_perfil_cargo_unico(
            membro
        )

        registrar_log_admin(
            "ALTERAR_CARGO_SETOR",
            membro.id,
            (
                f"Cargo anterior: {cargo_anterior}. "
                f"Novo setor: {setor}. "
                f"Novo cargo único: {cargo}."
            ),
        )

        criar_notificacao(
            membro.id,
            "Cargo atualizado",
            (
                f"Seu cargo foi atualizado pela administração "
                f"para {cargo} ({setor})."
            ),
            "info",
        )

        try:
            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()

            flash(
                "Não foi possível alterar o cargo.",
                "erro",
            )

            return redirect(
                url_for(
                    "admin_membro",
                    usuario_id=membro.id,
                )
            )

        flash(
            f"Cargo atualizado: {cargo}. O membro agora possui apenas este cargo.",
            "sucesso",
        )

        return redirect(
            url_for(
                "admin_membro",
                usuario_id=membro.id,
            )
        )



    @app.route(
        "/admin/membro/<int:usuario_id>/advertencia",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_advertir_membro(usuario_id):
        membro = db.session.get(Usuario, usuario_id)

        if membro is None:
            flash("Membro não encontrado.", "erro")
            return redirect(url_for("admin_dashboard"))

        if getattr(membro, "is_admin", False):
            flash("Esta função não aplica ADV em contas ADM.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        motivo = limpar_texto(request.form.get("motivo"), 1000)
        if not motivo:
            flash("Informe o motivo da advertência.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        ativas_antes = advertencias_ativas(membro.id)

        if len(ativas_antes) >= 2:
            flash("O membro já possui 2 ADVs ativas e está em situação de PD.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        agora = datetime.now(timezone.utc)

        adv = AdvertenciaAdmin(
            usuario_id=membro.id,
            admin_id=current_user.id,
            motivo=motivo,
            criado_em=agora,
            expira_em=agora + timedelta(days=14),
            removida=False,
        )
        db.session.add(adv)

        registrar_log_admin(
            "APLICAR_ADV",
            membro.id,
            f"ADV aplicada por 14 dias. Motivo: {motivo}",
        )

        criar_notificacao(
            membro.id,
            "Advertência recebida",
            f"Você recebeu uma ADV válida por 14 dias. Motivo: {motivo}",
            "aviso",
        )

        total_ativas = len(ativas_antes) + 1

        if total_ativas >= 2:
            membro.ativo = False
            registrar_log_admin(
                "PD_OBRIGATORIO",
                membro.id,
                "Membro alcançou 2 ADVs ativas. Conta bloqueada aguardando PD.",
            )

            criar_notificacao(
                membro.id,
                "Situação de PD",
                "Você atingiu 2 ADVs ativas. Sua conta foi bloqueada e marcada para análise de PD.",
                "erro",
            )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível registrar a advertência.", "erro")
            return redirect(url_for("admin_membro", usuario_id=membro.id))

        if total_ativas >= 2:
            flash(
                "2ª ADV aplicada. A conta foi bloqueada e marcada para PD.",
                "aviso",
            )
        else:
            flash(
                "ADV aplicada. Ela expira automaticamente em 14 dias.",
                "sucesso",
            )

        return redirect(url_for("admin_membro", usuario_id=membro.id))


    @app.route(
        "/admin/advertencia/<int:advertencia_id>/remover",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_remover_advertencia(advertencia_id):
        adv = db.session.get(AdvertenciaAdmin, advertencia_id)

        if adv is None:
            flash("Advertência não encontrada.", "erro")
            return redirect(url_for("admin_dashboard"))

        if adv.removida:
            flash("Essa ADV já foi removida.", "info")
            return redirect(url_for("admin_membro", usuario_id=adv.usuario_id))

        adv.removida = True
        adv.removida_por_admin_id = current_user.id
        adv.removida_em = datetime.now(timezone.utc)

        registrar_log_admin(
            "REMOVER_ADV",
            adv.usuario_id,
            f"ADV #{adv.id} removida pelo ADM.",
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível remover a ADV.", "erro")
            return redirect(url_for("admin_membro", usuario_id=adv.usuario_id))

        flash("Advertência removida. Se a conta estava bloqueada por PD, reative-a manualmente apenas se for apropriado.", "sucesso")
        return redirect(url_for("admin_membro", usuario_id=adv.usuario_id))



    @app.route(
        "/admin/reset-registros/<categoria>",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_reset_registros(categoria):
        """
        Reset administrativo global.

        Categorias:
        - lavagens: apaga todas as operações de lavagem;
        - acoes: apaga ações e os pontos originados por ações;
        - desmanches: apaga desmanches e os pontos originados por desmanches;
        - tudo: apaga as três categorias e seus pontos vinculados.

        Exige confirmação digitada para impedir exclusão acidental.
        """

        categorias_validas = {
            "lavagens",
            "acoes",
            "desmanches",
            "tudo",
        }

        if categoria not in categorias_validas:
            flash(
                "Categoria de reset inválida.",
                "erro",
            )
            return redirect(
                url_for("admin_dashboard")
            )

        confirmacao = str(
            request.form.get("confirmacao")
            or ""
        ).strip().upper()

        confirmacoes = {
            "lavagens": "RESETAR LAVAGENS",
            "acoes": "RESETAR ACOES",
            "desmanches": "RESETAR DESMANCHES",
            "tudo": "RESETAR TUDO",
        }

        esperado = confirmacoes[categoria]

        if confirmacao != esperado:
            flash(
                f"Confirmação incorreta. Digite exatamente: {esperado}",
                "erro",
            )
            return redirect(
                url_for("admin_dashboard")
            )

        try:
            apagados_lavagens = 0
            apagados_acoes = 0
            apagados_desmanches = 0
            apagados_pontos = 0
            apagadas_correcoes = 0

            if categoria in {
                "lavagens",
                "tudo",
            }:
                apagados_lavagens = (
                    Operacao.query.delete(
                        synchronize_session=False
                    )
                )

                apagadas_correcoes += (
                    SolicitacaoCorrecao.query.filter_by(
                        registro_tipo="lavagem"
                    ).delete(
                        synchronize_session=False
                    )
                )

            if categoria in {
                "acoes",
                "tudo",
            }:
                apagados_pontos += (
                    ExtratoPonto.query.filter_by(
                        origem_tipo="acao"
                    ).delete(
                        synchronize_session=False
                    )
                )

                apagados_acoes = (
                    Acao.query.delete(
                        synchronize_session=False
                    )
                )

                apagadas_correcoes += (
                    SolicitacaoCorrecao.query.filter_by(
                        registro_tipo="acao"
                    ).delete(
                        synchronize_session=False
                    )
                )

            if categoria in {
                "desmanches",
                "tudo",
            }:
                # Pontos de desmanche podem ter sido destinados
                # tanto para Ação quanto para Lavagem.
                apagados_pontos += (
                    ExtratoPonto.query.filter_by(
                        origem_tipo="desmanche"
                    ).delete(
                        synchronize_session=False
                    )
                )

                apagados_desmanches = (
                    Desmanche.query.delete(
                        synchronize_session=False
                    )
                )

                apagadas_correcoes += (
                    SolicitacaoCorrecao.query.filter_by(
                        registro_tipo="desmanche"
                    ).delete(
                        synchronize_session=False
                    )
                )

            detalhes = (
                f"Reset global '{categoria}'. "
                f"Lavagens: {apagados_lavagens}; "
                f"Ações: {apagados_acoes}; "
                f"Desmanches: {apagados_desmanches}; "
                f"Pontos removidos: {apagados_pontos}; "
                f"Correções removidas: {apagadas_correcoes}."
            )

            registrar_log_admin(
                "RESET_GLOBAL_REGISTROS",
                detalhes=detalhes,
            )

            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()

            logger.exception(
                "Erro no reset administrativo de registros: %s",
                categoria,
            )

            flash(
                "Não foi possível concluir o reset. Nenhum reset parcial foi confirmado.",
                "erro",
            )

            return redirect(
                url_for("admin_dashboard")
            )

        nomes = {
            "lavagens": "Lavagens",
            "acoes": "Ações",
            "desmanches": "Desmanches",
            "tudo": "Lavagens, Ações e Desmanches",
        }

        flash(
            (
                f"Reset concluído: {nomes[categoria]}. "
                f"Removidos: {apagados_lavagens} lavagens, "
                f"{apagados_acoes} ações, "
                f"{apagados_desmanches} desmanches e "
                f"{apagados_pontos} lançamentos de pontos."
            ),
            "sucesso",
        )

        return redirect(
            url_for("admin_dashboard")
        )


    @app.route("/admin/logs")
    @login_required
    @admin_required
    def admin_logs():
        logs = LogAdmin.query.order_by(
            LogAdmin.criado_em.desc()
        ).limit(300).all()

        linhas = []

        for log in logs:
            admin = (
                db.session.get(Usuario, log.admin_id)
                if log.admin_id
                else None
            )

            alvo = (
                db.session.get(Usuario, log.alvo_usuario_id)
                if log.alvo_usuario_id
                else None
            )

            linhas.append({
                "log": log,
                "admin": admin,
                "alvo": alvo,
            })

        return render_template(
            "admin_logs.html",
            linhas=linhas,
        )


    @app.route("/admin/membro/<int:usuario_id>")
    @login_required
    @admin_required
    def admin_membro(usuario_id):
        """
        Detalhe administrativo do membro.

        A rota prepara dados simples para o template para evitar erro 500
        causado por Decimal, timezone ou registros antigos incompletos.
        """
        usuario = db.session.get(
            Usuario,
            usuario_id,
        )

        if usuario is None:
            flash(
                "Membro não encontrado.",
                "erro",
            )
            return redirect(
                url_for("admin_dashboard")
            )

        try:
            perfil = PerfilSetor.query.filter_by(
                usuario_id=usuario.id
            ).first()

            perfil = sincronizar_perfil_cargo_unico(
                usuario,
                perfil,
            )

            db.session.flush()

            perfil_game = obter_perfil_game(
                usuario.id
            )

            lavagens_db = Operacao.query.filter_by(
                usuario_id=usuario.id
            ).order_by(
                Operacao.criado_em.desc()
            ).limit(25).all()

            acoes_db = Acao.query.filter_by(
                usuario_id=usuario.id
            ).order_by(
                Acao.data_hora.desc()
            ).limit(25).all()

            desmanches_db = Desmanche.query.filter_by(
                usuario_id=usuario.id
            ).order_by(
                Desmanche.data_hora.desc()
            ).limit(25).all()

            extrato_db = ExtratoPonto.query.filter_by(
                usuario_id=usuario.id
            ).order_by(
                ExtratoPonto.criado_em.desc()
            ).limit(50).all()

            def moeda_segura(valor):
                try:
                    numero = float(
                        valor or 0
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    numero = 0

                return (
                    f"{numero:,.2f}"
                    .replace(",", "X")
                    .replace(".", ",")
                    .replace("X", ".")
                )

            def data_segura(valor):
                if valor is None:
                    return "—"

                try:
                    if (
                        getattr(
                            valor,
                            "tzinfo",
                            None,
                        )
                        is None
                    ):
                        valor = valor.replace(
                            tzinfo=timezone.utc
                        )

                    return (
                        valor
                        .astimezone(FUSO_LOCAL)
                        .strftime(
                            "%d/%m/%Y %H:%M"
                        )
                    )

                except Exception:
                    return "—"

            lavagens = []

            for op in lavagens_db:
                try:
                    percentual = abs(
                        float(
                            op.porcentagem
                            or 0
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    percentual = 0

                lavagens.append({
                    "nome": (
                        op.nome_jogador
                        or "Não informado"
                    ),
                    "id_game": (
                        op.id_jogador
                        or "—"
                    ),
                    "percentual": int(
                        round(percentual)
                    ),
                    "valor": moeda_segura(
                        op.valor
                    ),
                    "data": data_segura(
                        op.criado_em
                    ),
                })

            acoes = [
                {
                    "tipo": (
                        item.tipo
                        or "Ação"
                    ),
                    "resultado": (
                        item.resultado
                        or "—"
                    ),
                    "pontos": int(
                        item.pontos
                        or 0
                    ),
                    "responsavel": (
                        item.responsavel
                        or "Não informado"
                    ),
                    "data": data_segura(
                        item.data_hora
                    ),
                }
                for item in acoes_db
            ]

            desmanches = [
                {
                    "modelo": (
                        item.modelo
                        or "Não informado"
                    ),
                    "pontos": int(
                        item.pontos
                        or 0
                    ),
                    "destino": (
                        item.destino_pontos
                        or "—"
                    ),
                    "valor": moeda_segura(
                        item.quantidade
                    ),
                    "data": data_segura(
                        item.data_hora
                    ),
                }
                for item in desmanches_db
            ]

            extrato = [
                {
                    "descricao": (
                        item.descricao
                        or "Registro"
                    ),
                    "pontos": int(
                        item.pontos
                        or 0
                    ),
                    "categoria": (
                        item.categoria
                        or "—"
                    ),
                    "data": data_segura(
                        item.criado_em
                    ),
                }
                for item in extrato_db
            ]

            pontos_acao = sum(
                item["pontos"]
                for item in extrato
                if item["categoria"] == "acao"
            )

            pontos_lavagem = sum(
                item["pontos"]
                for item in extrato
                if item["categoria"] == "lavagem"
            )

            adv_db = AdvertenciaAdmin.query.filter_by(
                usuario_id=usuario.id
            ).order_by(
                AdvertenciaAdmin.criado_em.desc()
            ).limit(20).all()

            advertencias = [
                {
                    "id": adv.id,
                    "motivo": (
                        adv.motivo
                        or "Sem motivo informado."
                    ),
                    "criado_em": data_segura(
                        adv.criado_em
                    ),
                    "expira_em": data_segura(
                        adv.expira_em
                    ),
                    "removida": bool(
                        adv.removida
                    ),
                }
                for adv in adv_db
            ]

            ads_ativas = advertencias_ativas(
                usuario.id
            )

            return render_template(
                "admin_membro.html",
                membro=usuario,
                perfil=perfil,
                perfil_game=perfil_game,
                lavagens=lavagens,
                acoes=acoes,
                desmanches=desmanches,
                extrato=extrato,
                pontos_acao=pontos_acao,
                pontos_lavagem=pontos_lavagem,
                advertencias=advertencias,
                total_advertencias_ativas=len(
                    ads_ativas
                ),
                cargos_lavagem=ORDEM_CARGOS,
                cargos_acao=CARGOS_ACAO_CADASTRO,
                cargos_gerencia=CARGOS_GERENCIA,
                setor_membro=setor_do_cargo(
                    usuario.cargo
                ),
            )

        except SQLAlchemyError:
            logger.exception(
                "Erro de banco ao abrir membro ADM %s",
                usuario_id,
            )

            flash(
                "Não foi possível carregar os dados do membro.",
                "erro",
            )

            return redirect(
                url_for("admin_dashboard")
            )


    @app.route("/reset-semanal", methods=["POST"])
    @login_required
    def reset_semanal():
        # Mantida por compatibilidade. Nunca apaga operações.
        flash("A contagem semanal é automática: domingo 00:00 até sábado 23:59. Seu histórico não foi apagado.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/configuracoes", methods=["GET", "POST"])
    @login_required
    def configuracoes():
        garantir_cargo_valido(current_user)
        registro_meta, _, _ = obter_meta_semana(current_user.id, criar=True)

        if request.method == "POST":
            setor_atual = (
                setor_do_cargo(
                    current_user.cargo
                )
            )

            # Cargo é administrativo. O usuário nunca cria
            # uma combinação de setores pela própria configuração.
            if setor_atual != "lavagem":
                flash(
                    "Seu cargo é gerenciado pela administração.",
                    "info",
                )
                return redirect(
                    url_for("configuracoes")
                )

            meta_entregue = (
                request.form.get(
                    "meta_entregue"
                )
                == "1"
            )

            try:
                impulsos = int(
                    request.form.get(
                        "impulsos",
                        "0",
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                impulsos = 0

            if impulsos not in (
                0,
                1,
                2,
            ):
                impulsos = 0

            try:
                registro_meta.meta_entregue = (
                    meta_entregue
                )
                registro_meta.impulsos = impulsos
                db.session.commit()

            except SQLAlchemyError:
                db.session.rollback()

                logger.exception(
                    "Erro ao salvar configurações do usuário %s.",
                    current_user.id,
                )

                flash(
                    "Não foi possível salvar as configurações.",
                    "erro",
                )

                return redirect(
                    url_for("configuracoes")
                )

            flash(
                "Configurações salvas com sucesso.",
                "sucesso",
            )

            return redirect(
                url_for("configuracoes")
            )

        setor_atual = setor_do_cargo(
            current_user.cargo
        )

        progresso = (
            resumo_meta_semanal(
                current_user
            )
            if setor_atual == "lavagem"
            else None
        )
        perfil_game = obter_perfil_game(current_user.id)
        solicitacao_perfil = obter_solicitacao_perfil_pendente(current_user.id)
        historico_solicitacoes = SolicitacaoPerfilGame.query.filter_by(
            usuario_id=current_user.id
        ).order_by(
            SolicitacaoPerfilGame.solicitado_em.desc()
        ).limit(5).all()

        return render_template(
            "configuracoes.html",
            cargos=ORDEM_CARGOS,
            metas=CARGOS,
            setor_atual=setor_atual,
            progresso=progresso,
            perfil_game=perfil_game,
            solicitacao_perfil=solicitacao_perfil,
            historico_solicitacoes=historico_solicitacoes,
        )

    @app.route("/configuracoes/perfil-game", methods=["POST"])
    @login_required
    def salvar_perfil_game():
        try:
            nome_novo, id_novo = validar_dados_game(
                request.form.get("nome_game"),
                request.form.get("id_game"),
            )
        except ValueError as erro:
            flash(str(erro), "erro")
            return redirect(url_for("configuracoes"))

        perfil_atual = obter_perfil_game(current_user.id)

        # Primeira vinculação: é salva imediatamente.
        if perfil_atual is None:
            id_em_uso = PerfilGame.query.filter_by(id_game=id_novo).first()
            if id_em_uso:
                flash("Este ID do game já está vinculado a outra conta.", "erro")
                return redirect(url_for("configuracoes"))

            try:
                db.session.add(PerfilGame(
                    usuario_id=current_user.id,
                    nome_game=nome_novo,
                    id_game=id_novo,
                ))
                db.session.commit()
                flash("Nome e ID do game vinculados à sua conta.", "sucesso")
            except IntegrityError:
                db.session.rollback()
                flash("Este ID do game já está vinculado a outra conta.", "erro")
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception("Erro ao criar perfil game do usuário %s", current_user.id)
                flash("Não foi possível salvar seu perfil do game.", "erro")
            return redirect(url_for("configuracoes"))

        if perfil_atual.nome_game == nome_novo and perfil_atual.id_game == id_novo:
            flash("Nenhuma alteração foi detectada.", "info")
            return redirect(url_for("configuracoes"))

        if obter_solicitacao_perfil_pendente(current_user.id):
            flash("Você já possui uma alteração de Nome/ID aguardando aprovação do ADM.", "aviso")
            return redirect(url_for("configuracoes"))

        id_em_uso = PerfilGame.query.filter(
            PerfilGame.id_game == id_novo,
            PerfilGame.usuario_id != current_user.id,
        ).first()
        if id_em_uso:
            flash("Este ID do game já está vinculado a outra conta.", "erro")
            return redirect(url_for("configuracoes"))

        try:
            db.session.add(SolicitacaoPerfilGame(
                usuario_id=current_user.id,
                nome_atual=perfil_atual.nome_game,
                id_atual=perfil_atual.id_game,
                nome_novo=nome_novo,
                id_novo=id_novo,
                status="pendente",
            ))
            db.session.commit()
            flash("Alteração enviada. Seu Nome/ID atual só muda após aprovação de um ADM.", "sucesso")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro ao solicitar alteração de perfil game do usuário %s", current_user.id)
            flash("Não foi possível enviar a solicitação.", "erro")

        return redirect(url_for("configuracoes"))

    @app.route("/historico")
    @login_required
    def historico():
        operacoes = Operacao.query.filter_by(usuario_id=current_user.id).order_by(Operacao.criado_em.desc(), Operacao.id.desc()).all()
        return render_template("historico.html", operacoes=operacoes)

    @app.route("/relatorios")
    @login_required
    def relatorios():
        resumo = db.session.query(
            func.count(Operacao.id),
            func.coalesce(func.sum(Operacao.valor), 0),
            func.coalesce(func.sum(Operacao.valor_porcentagem), 0),
        ).one()

        membros = db.session.query(
            Usuario.id.label("usuario_id"),
            Usuario.usuario.label("usuario_site"),
            Usuario.cargo.label("cargo"),
            PerfilGame.nome_game.label("nome_game"),
            PerfilGame.id_game.label("id_game"),
            func.count(Operacao.id).label("total_operacoes"),
            func.coalesce(func.sum(Operacao.valor), 0).label("valor_total"),
            func.coalesce(func.sum(Operacao.valor_porcentagem), 0).label("ganhos_total"),
        ).join(
            Operacao,
            Operacao.usuario_id == Usuario.id,
        ).outerjoin(
            PerfilGame,
            PerfilGame.usuario_id == Usuario.id,
        ).filter(
            Usuario.is_admin.is_(False),
        ).group_by(
            Usuario.id,
            Usuario.usuario,
            Usuario.cargo,
            PerfilGame.nome_game,
            PerfilGame.id_game,
        ).order_by(
            func.count(Operacao.id).desc(),
            func.sum(Operacao.valor).desc(),
        ).all()

        return render_template(
            "relatorios.html",
            total_operacoes=resumo[0],
            valor_total=resumo[1],
            ganhos_total=resumo[2],
            membros=membros,
        )

    @app.route("/excluir-operacao/<int:id>", methods=["POST"])
    @login_required
    def excluir_operacao(id):
        operacao = Operacao.query.filter_by(id=id, usuario_id=current_user.id).first()
        if operacao is None:
            return redirect(url_for("historico"))
        try:
            db.session.delete(operacao)
            db.session.commit()
            db.session.expire_all()
            flash("Operação excluída definitivamente.", "sucesso")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro ao excluir operação %s.", id)
            flash("Não foi possível excluir a operação.", "erro")
        return redirect(url_for("historico", atualizado=int(datetime.now(timezone.utc).timestamp())))


    @app.route("/operacao/<int:id>/print/<tipo>")
    @login_required
    def print_operacao(id, tipo):
        operacao = Operacao.query.filter_by(
            id=id,
            usuario_id=current_user.id,
        ).first_or_404()

        if tipo == "envio":
            dados = operacao.print_envio_dados
            mime = operacao.print_envio_mime
        elif tipo == "recebimento":
            dados = operacao.print_recebimento_dados
            mime = operacao.print_recebimento_mime
        else:
            return resposta_erro("Tipo de print inválido.", 404)

        if not dados:
            return resposta_erro("Print não disponível.", 404)

        return Response(
            bytes(dados),
            mimetype=mime or "image/png",
            headers={"Cache-Control": "private, max-age=300"},
        )

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    logger.info("Rotas registradas com sucesso.")

# =========================================================
# GESTÃO COMPLETA — AÇÕES, DESMANCHES, RANKING E HISTÓRICO
# =========================================================

PONTOS_ACAO = {
    "Drop": {"Vitória": 3, "Derrota": 1},
    "Lojinha": {"Vitória": 6, "Derrota": 3},
    "Joalheria": {"Vitória": 8, "Derrota": 3},
    "Banco": {"Vitória": 15, "Derrota": 7},
    "Invasão": {"Vitória": 12, "Derrota": 5},
}

CARGOS_ACAO = [
    "Lanterninha",
    "Olheiro",
    "Cobrador",
    "Soldado",
    "Capanga",
    "Tenente de Rua",
]

CARGOS_PERFIL = CARGOS_ACAO + CARGOS_GERENCIA

HIERARQUIA_ACAO = {cargo: indice for indice, cargo in enumerate(CARGOS_PERFIL)}

METAS_ACAO = {
    "Lanterninha": {
        0: {"pontos": None, "papeis": 125, "spray": 125, "dinheiro": 1500000},
        1: {"pontos": None, "papeis": 100, "spray": 100, "dinheiro": 1200000},
        2: {"pontos": None, "papeis": 62, "spray": 62, "dinheiro": 750000},
    },
    "Olheiro": {
        0: {"pontos": 90, "papeis": 50, "spray": 50, "dinheiro": 4000000},
        1: {"pontos": 72, "papeis": 40, "spray": 40, "dinheiro": 3200000},
        2: {"pontos": 45, "papeis": 25, "spray": 25, "dinheiro": 2000000},
    },
    "Cobrador": {
        0: {"pontos": 80, "papeis": 40, "spray": 40, "dinheiro": 3500000},
        1: {"pontos": 64, "papeis": 32, "spray": 32, "dinheiro": 2800000},
        2: {"pontos": 40, "papeis": 20, "spray": 20, "dinheiro": 1750000},
    },
    "Soldado": {
        0: {"pontos": 70, "papeis": 30, "spray": 30, "dinheiro": 3000000},
        1: {"pontos": 56, "papeis": 24, "spray": 24, "dinheiro": 2400000},
        2: {"pontos": 35, "papeis": 20, "spray": 20, "dinheiro": 1500000},
    },
    "Capanga": {
        0: {"pontos": 60, "papeis": 20, "spray": 20, "dinheiro": 2500000},
        1: {"pontos": 48, "papeis": 16, "spray": 16, "dinheiro": 2000000},
        2: {"pontos": 30, "papeis": 10, "spray": 10, "dinheiro": 1250000},
    },
    "Tenente de Rua": {
        0: {"pontos": 50, "papeis": 10, "spray": 10, "dinheiro": 2000000},
        1: {"pontos": 40, "papeis": 8, "spray": 8, "dinheiro": 1600000},
        2: {"pontos": 25, "papeis": 5, "spray": 5, "dinheiro": 1000000},
    },
    "Chefe de Setor": {
        0: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 2000000},
        1: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 1600000},
        2: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 1000000},
    },
    "Alto Conselho": {
        0: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 2000000},
        1: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 1600000},
        2: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 1000000},
    },
    "Sub Gerente": {
        0: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 2500000},
        1: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 2000000},
        2: {"pontos": None, "papeis": None, "spray": None, "dinheiro": 1250000},
    },
}


def limpar(valor, limite=2000):
    return str(valor or "").strip()[:limite]


def decimal_positivo(valor, campo):
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{campo} inválido.")
    if not numero.is_finite() or numero <= 0:
        raise ValueError(f"{campo} precisa ser maior que zero.")
    return numero.quantize(Decimal("0.01"))


def parse_data_hora(valor):
    texto = limpar(valor, 40)
    formatos = ("%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y - %H:%M")
    for formato in formatos:
        try:
            local = datetime.strptime(texto, formato).replace(tzinfo=FUSO_LOCAL)
            return local.astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError("Data e hora inválidas.")


def validar_hash(valor):
    texto = limpar(valor, 80).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", texto):
        raise ValueError("A prova final precisa ser um print válido.")
    return texto


def fingerprint(*partes):
    base = "|".join(limpar(p, 500).lower() for p in partes)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def obter_perfil(usuario_id, criar=True):
    perfil = PerfilSetor.query.filter_by(
        usuario_id=usuario_id
    ).first()

    usuario = db.session.get(
        Usuario,
        usuario_id,
    )

    if perfil is None and criar:
        perfil = PerfilSetor(
            usuario_id=usuario_id,
            setor_lavagem=False,
            setor_acao=False,
            cargo_acao=None,
            impulsos_lavagem=0,
            impulsos_acao=0,
        )
        db.session.add(perfil)

    if (
        perfil is not None
        and usuario is not None
    ):
        cargo_antes = usuario.cargo
        perfil_cargo_antes = perfil.cargo_acao
        setor_lavagem_antes = perfil.setor_lavagem
        setor_acao_antes = perfil.setor_acao

        sincronizar_perfil_cargo_unico(
            usuario,
            perfil,
        )

        if (
            usuario.cargo != cargo_antes
            or perfil.cargo_acao != perfil_cargo_antes
            or perfil.setor_lavagem != setor_lavagem_antes
            or perfil.setor_acao != setor_acao_antes
        ):
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception(
                    "Erro ao migrar cargo único do usuário %s.",
                    usuario_id,
                )

    return perfil


def inicio_semana():
    agora = datetime.now(FUSO_LOCAL)
    dias = (agora.weekday() + 1) % 7
    inicio = (agora - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio.astimezone(timezone.utc)


def sugerir_responsavel(participantes):
    melhor = None
    melhor_nivel = -1
    for linha in participantes.splitlines():
        if "|" not in linha:
            continue
        nome, cargo = [x.strip() for x in linha.split("|", 1)]
        nivel = HIERARQUIA_ACAO.get(cargo, -1)
        if nome and nivel > melhor_nivel:
            melhor = f"{nome} | {cargo}"
            melhor_nivel = nivel
    return melhor or ""


def configurar_rotas_gestao(app):

    @app.route("/gestao")
    @login_required
    def gestao():
        perfil = obter_perfil(current_user.id)
        perfil_game = obter_perfil_game(current_user.id)
        solicitacao_perfil = obter_solicitacao_perfil_pendente(current_user.id)
        inicio = inicio_semana()

        pontos_acao = db.session.query(
            func.coalesce(func.sum(ExtratoPonto.pontos), 0)
        ).filter(
            ExtratoPonto.usuario_id == current_user.id,
            ExtratoPonto.categoria == "acao",
            ExtratoPonto.criado_em >= inicio,
        ).scalar()

        pontos_lavagem = db.session.query(
            func.coalesce(func.sum(ExtratoPonto.pontos), 0)
        ).filter(
            ExtratoPonto.usuario_id == current_user.id,
            ExtratoPonto.categoria == "lavagem",
            ExtratoPonto.criado_em >= inicio,
        ).scalar()

        lavagens_semana, valor_semana = db.session.query(
            func.count(Operacao.id),
            func.coalesce(func.sum(Operacao.valor), 0),
        ).filter(
            Operacao.usuario_id == current_user.id,
            Operacao.criado_em >= inicio,
        ).one()

        acoes_semana = Acao.query.filter(
            Acao.usuario_id == current_user.id,
            Acao.data_hora >= inicio,
        ).count()

        desmanches_semana = Desmanche.query.filter(
            Desmanche.usuario_id == current_user.id,
            Desmanche.data_hora >= inicio,
        ).count()

        setor_atual = (
            setor_do_cargo(
                current_user.cargo
            )
        )

        meta_acao = None

        if (
            setor_atual == "acao"
            and current_user.cargo in METAS_ACAO
        ):
            meta_acao = METAS_ACAO[
                current_user.cargo
            ][
                perfil.impulsos_acao
                if perfil.impulsos_acao in (0, 1, 2)
                else 0
            ]

        meta_lavagem = (
            resumo_meta_semanal(
                current_user
            )
            if setor_atual == "lavagem"
            else None
        )

        # Posição semanal em cada ranking.
        lavagem_rank = db.session.query(
            Operacao.usuario_id,
            func.count(Operacao.id).label("total"),
        ).filter(
            Operacao.criado_em >= inicio,
        ).group_by(Operacao.usuario_id).order_by(func.count(Operacao.id).desc()).all()

        acao_rank = db.session.query(
            ExtratoPonto.usuario_id,
            func.sum(ExtratoPonto.pontos).label("total"),
        ).filter(
            ExtratoPonto.categoria == "acao",
            ExtratoPonto.criado_em >= inicio,
        ).group_by(ExtratoPonto.usuario_id).order_by(func.sum(ExtratoPonto.pontos).desc()).all()

        desmanche_rank = db.session.query(
            Desmanche.usuario_id,
            func.count(Desmanche.id).label("total"),
        ).filter(
            Desmanche.data_hora >= inicio,
        ).group_by(Desmanche.usuario_id).order_by(func.count(Desmanche.id).desc()).all()

        def posicao(lista):
            for indice, linha in enumerate(lista, 1):
                if linha[0] == current_user.id:
                    return indice
            return None

        posicoes = {
            "lavagem": posicao(lavagem_rank),
            "acao": posicao(acao_rank),
            "desmanche": posicao(desmanche_rank),
        }

        atividades = []
        for op in Operacao.query.filter_by(usuario_id=current_user.id).order_by(Operacao.criado_em.desc()).limit(4).all():
            atividades.append({"data": op.criado_em, "icone": "💰", "tipo": "Lavagem", "titulo": f"{op.nome_jogador} #{op.id_jogador}"})
        for acao in Acao.query.filter_by(usuario_id=current_user.id).order_by(Acao.data_hora.desc()).limit(4).all():
            atividades.append({"data": acao.data_hora, "icone": "🔫", "tipo": "Ação", "titulo": f"{acao.tipo} — {acao.resultado}"})
        for des in Desmanche.query.filter_by(usuario_id=current_user.id).order_by(Desmanche.data_hora.desc()).limit(4).all():
            atividades.append({"data": des.data_hora, "icone": "🚗", "tipo": "Desmanche", "titulo": des.modelo})

        def timestamp_seguro(item):
            data = item["data"]
            if data is None:
                return 0
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            return data.timestamp()

        atividades = sorted(atividades, key=timestamp_seguro, reverse=True)[:8]

        return render_template(
            "gestao.html",
            perfil=perfil,
            perfil_game=perfil_game,
            setor_atual=setor_atual,
            solicitacao_perfil=solicitacao_perfil,
            pontos_acao=int(pontos_acao or 0),
            pontos_lavagem=int(pontos_lavagem or 0),
            lavagens_semana=int(lavagens_semana or 0),
            valor_semana=valor_semana or 0,
            acoes_semana=acoes_semana,
            desmanches_semana=desmanches_semana,
            meta_acao=meta_acao,
            meta_lavagem=meta_lavagem,
            posicoes=posicoes,
            atividades=atividades,
            advertencias_ativas=advertencias_ativas(current_user.id),
            notificacoes_recentes=Notificacao.query.filter_by(
                usuario_id=current_user.id
            ).order_by(
                Notificacao.criado_em.desc()
            ).limit(5).all(),
        )

    @app.route("/perfil-setores", methods=["GET", "POST"])
    @login_required
    def perfil_setores():
        """
        Visualização do setor atual.
        O próprio usuário não pode acumular ou trocar setores.
        Mudanças de cargo/setor são feitas pelo ADM.
        """
        perfil = obter_perfil(
            current_user.id
        )

        sincronizar_perfil_cargo_unico(
            current_user,
            perfil,
        )

        if request.method == "POST":
            flash(
                "Cargo e setor são alterados somente pela administração.",
                "info",
            )
            return redirect(
                url_for("perfil_setores")
            )

        return render_template(
            "perfil_setores.html",
            perfil=perfil,
            cargo_atual=current_user.cargo,
            setor_atual=setor_do_cargo(
                current_user.cargo
            ),
            cargos_acao=CARGOS_ACAO_CADASTRO,
            cargos_gerencia=CARGOS_GERENCIA,
        )



    @app.route("/acoes")
    @login_required
    def acoes():
        perfil = obter_perfil(current_user.id)
        ultimas = Acao.query.filter_by(usuario_id=current_user.id).order_by(
            Acao.data_hora.desc(), Acao.id.desc()
        ).limit(20).all()
        return render_template(
            "acoes.html",
            tipos=list(PONTOS_ACAO.keys()),
            cargos=CARGOS_ACAO,
            perfil=perfil,
            ultimas=ultimas,
        )

    @app.route("/acoes/salvar", methods=["POST"])
    @login_required
    def salvar_acao():
        """API de ações: sempre devolve JSON, inclusive em falhas inesperadas."""
        try:
            if not request.is_json:
                return jsonify(
                    sucesso=False,
                    erro="A requisição da ação precisa ser enviada em JSON.",
                    codigo="ACAO_JSON_INVALIDO",
                ), 415

            dados = request.get_json(silent=True)
            if not isinstance(dados, dict):
                return jsonify(
                    sucesso=False,
                    erro="Não foi possível ler os dados enviados.",
                    codigo="ACAO_DADOS_INVALIDOS",
                ), 400

            tipo = limpar(dados.get("tipo"), 30)
            resultado = limpar(dados.get("resultado"), 10)
            participantes = limpar(dados.get("participantes"), 5000)
            responsavel = limpar(dados.get("responsavel"), 120)
            resumo = limpar(dados.get("resumo"), 4000)
            lucro = limpar(dados.get("lucro"), 2000) or "Nada"
            prova_nome = limpar(dados.get("prova_nome"), 255)

            if tipo not in PONTOS_ACAO:
                return jsonify(
                    sucesso=False,
                    erro="Tipo de ação inválido.",
                    codigo="ACAO_TIPO_INVALIDO",
                ), 400

            if resultado not in {"Vitória", "Derrota"}:
                return jsonify(
                    sucesso=False,
                    erro="Informe Vitória ou Derrota.",
                    codigo="ACAO_RESULTADO_INVALIDO",
                ), 400

            if not participantes:
                return jsonify(
                    sucesso=False,
                    erro="Informe os participantes e cargos.",
                    codigo="ACAO_PARTICIPANTES_OBRIGATORIOS",
                ), 400

            if not resumo:
                return jsonify(
                    sucesso=False,
                    erro="Informe um resumo da ação.",
                    codigo="ACAO_RESUMO_OBRIGATORIO",
                ), 400

            try:
                data_hora = parse_data_hora(dados.get("data_hora"))
                prova_hash = validar_hash(dados.get("prova_hash"))
            except ValueError as erro:
                return jsonify(
                    sucesso=False,
                    erro=str(erro),
                    codigo="ACAO_VALIDACAO",
                ), 400

            if not responsavel:
                responsavel = sugerir_responsavel(participantes)

            if not responsavel:
                return jsonify(
                    sucesso=False,
                    erro="Informe o responsável oficial da ação.",
                    codigo="ACAO_RESPONSAVEL_OBRIGATORIO",
                ), 400

            pontos = PONTOS_ACAO[tipo][resultado]

            assinatura = fingerprint(
                current_user.id,
                tipo,
                data_hora.isoformat(),
                participantes,
                resultado,
                prova_hash,
            )

            existente = Acao.query.filter_by(
                usuario_id=current_user.id,
                fingerprint=assinatura,
            ).first()

            if existente:
                return jsonify(
                    sucesso=False,
                    duplicado=True,
                    erro="Esta ação já foi registrada.",
                    codigo="ACAO_DUPLICADA",
                ), 409

            acao = Acao(
                usuario_id=current_user.id,
                tipo=tipo,
                data_hora=data_hora,
                participantes=participantes,
                responsavel=responsavel,
                resumo=resumo,
                resultado=resultado,
                lucro=lucro,
                pontos=pontos,
                prova_hash=prova_hash,
                prova_nome=prova_nome or "print-final",
                fingerprint=assinatura,
            )

            db.session.add(acao)
            db.session.flush()
            db.session.add(ExtratoPonto(
                usuario_id=current_user.id,
                origem_tipo="acao",
                origem_id=acao.id,
                categoria="acao",
                pontos=pontos,
                descricao=f"{tipo} — {resultado}",
                criado_em=data_hora,
            ))
            db.session.commit()

            return jsonify(
                sucesso=True,
                pontos=pontos,
                id=acao.id,
            ), 201

        except IntegrityError:
            db.session.rollback()
            return jsonify(
                sucesso=False,
                duplicado=True,
                erro="Esta ação parece já ter sido registrada.",
                codigo="ACAO_DUPLICADA",
            ), 409

        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro de banco ao salvar ação")
            return jsonify(
                sucesso=False,
                erro="O banco de dados recusou o registro da ação.",
                codigo="ACAO_BANCO",
            ), 500

        except Exception:
            db.session.rollback()
            logger.exception("Erro inesperado ao salvar ação")
            return jsonify(
                sucesso=False,
                erro="O servidor encontrou um erro ao salvar a ação.",
                codigo="ACAO_SERVIDOR",
            ), 500

    @app.route("/desmanches")
    @login_required
    def desmanches():
        perfil = obter_perfil(current_user.id)
        ultimos = Desmanche.query.filter_by(usuario_id=current_user.id).order_by(
            Desmanche.data_hora.desc(), Desmanche.id.desc()
        ).limit(20).all()
        return render_template(
            "desmanches.html",
            perfil=perfil,
            ultimos=ultimos,
        )

    @app.route("/desmanches/salvar", methods=["POST"])
    @login_required
    def salvar_desmanche():
        """
        API de desmanche.
        IMPORTANTE: esta rota sempre responde JSON, inclusive em erros inesperados,
        para o front-end nunca receber HTML e quebrar no response.json().
        """
        try:
            if not request.is_json:
                return jsonify(
                    sucesso=False,
                    erro="A requisição do desmanche precisa ser enviada em JSON.",
                    codigo="DESMANCHE_JSON_INVALIDO",
                ), 415

            dados = request.get_json(silent=True)
            if not isinstance(dados, dict):
                return jsonify(
                    sucesso=False,
                    erro="Não foi possível ler os dados enviados.",
                    codigo="DESMANCHE_DADOS_INVALIDOS",
                ), 400

            modelo = limpar(dados.get("modelo"), 100)
            destino = limpar(dados.get("destino_pontos"), 20)
            prova_nome = limpar(dados.get("prova_nome"), 255)

            if not modelo:
                return jsonify(
                    sucesso=False,
                    erro="O modelo do veículo é obrigatório.",
                    codigo="DESMANCHE_MODELO_OBRIGATORIO",
                ), 400

            if destino not in {"acao", "lavagem"}:
                return jsonify(
                    sucesso=False,
                    erro="Escolha Ação ou Lavagem para receber os pontos.",
                    codigo="DESMANCHE_DESTINO_INVALIDO",
                ), 400

            try:
                data_hora = parse_data_hora(dados.get("data_hora"))
                quantidade = decimal_positivo(
                    dados.get("quantidade"),
                    "Quantidade recebida",
                )
                prova_hash = validar_hash(dados.get("prova_hash"))
            except ValueError as erro:
                return jsonify(
                    sucesso=False,
                    erro=str(erro),
                    codigo="DESMANCHE_VALIDACAO",
                ), 400

            # Regra atual de Desmanche:
            # - cada desmanche destinado à Ação vale +1 ponto;
            # - Lavagem continua +1 ponto;
            # - a cada R$ 2.000.000 acumulados em dinheiro de desmanche,
            #   o usuário recebe +2 pontos extras no mesmo destino escolhido.
            pontos_base = 1

            total_antes = db.session.query(
                func.coalesce(
                    func.sum(Desmanche.quantidade),
                    0,
                )
            ).filter(
                Desmanche.usuario_id == current_user.id
            ).scalar()

            total_antes = Decimal(
                str(total_antes or 0)
            )

            faixa_antes = int(
                total_antes //
                Decimal("2000000")
            )

            total_depois = (
                total_antes +
                quantidade
            )

            faixa_depois = int(
                total_depois //
                Decimal("2000000")
            )

            faixas_novas = max(
                0,
                faixa_depois - faixa_antes
            )

            pontos_bonus = (
                faixas_novas * 2
            )

            pontos = (
                pontos_base +
                pontos_bonus
            )

            assinatura = fingerprint(
                current_user.id,
                modelo,
                data_hora.isoformat(),
                quantidade,
                destino,
                prova_hash,
            )

            # Verificação antecipada deixa a mensagem de duplicidade mais clara
            existente = Desmanche.query.filter_by(
                usuario_id=current_user.id,
                fingerprint=assinatura,
            ).first()

            if existente:
                return jsonify(
                    sucesso=False,
                    duplicado=True,
                    erro="Este desmanche já foi registrado.",
                    codigo="DESMANCHE_DUPLICADO",
                ), 409

            registro = Desmanche(
                usuario_id=current_user.id,
                modelo=modelo,
                data_hora=data_hora,
                quantidade=quantidade,
                destino_pontos=destino,
                pontos=pontos,
                prova_hash=prova_hash,
                prova_nome=prova_nome or "print-desmanche",
                fingerprint=assinatura,
            )

            db.session.add(registro)
            db.session.flush()

            extrato = ExtratoPonto(
                usuario_id=current_user.id,
                origem_tipo="desmanche",
                origem_id=registro.id,
                categoria=destino,
                pontos=pontos,
                descricao=(
                    f"Desmanche {modelo}"
                    + (
                        f" + bônus R$ 2M x{faixas_novas}"
                        if faixas_novas
                        else ""
                    )
                ),
                criado_em=data_hora,
            )

            db.session.add(extrato)
            db.session.commit()

            return jsonify(
                sucesso=True,
                pontos=pontos,
                pontos_base=pontos_base,
                pontos_bonus=pontos_bonus,
                faixas_bonus=faixas_novas,
                total_desmanches=float(total_depois),
                proximo_bonus=float(
                    (
                        Decimal(faixa_depois + 1)
                        * Decimal("2000000")
                    )
                    - total_depois
                ),
                id=registro.id,
            ), 201

        except IntegrityError:
            db.session.rollback()
            return jsonify(
                sucesso=False,
                duplicado=True,
                erro="Este desmanche parece já ter sido registrado.",
                codigo="DESMANCHE_DUPLICADO",
            ), 409

        except SQLAlchemyError as erro:
            db.session.rollback()
            logger.exception("Erro de banco ao salvar desmanche")
            return jsonify(
                sucesso=False,
                erro="O banco de dados recusou o registro. Tente novamente.",
                codigo="DESMANCHE_BANCO",
            ), 500

        except Exception as erro:
            db.session.rollback()
            logger.exception("Erro inesperado ao salvar desmanche")
            return jsonify(
                sucesso=False,
                erro="O servidor encontrou um erro ao salvar o desmanche.",
                codigo="DESMANCHE_SERVIDOR",
            ), 500



    @app.route("/calculadora")
    @login_required
    def calculadora():
        return render_template(
            "calculadora.html",
        )


    @app.route("/ranking")
    @login_required
    def ranking():
        categoria = request.args.get("categoria", "lavagem")
        if categoria not in {"lavagem", "acao", "desmanche"}:
            categoria = "lavagem"

        periodo = request.args.get("periodo", "semana")
        if periodo not in {"semana", "mes", "geral"}:
            periodo = "semana"

        inicio_periodo = None

        if periodo == "semana":
            inicio_periodo = inicio_semana()

        elif periodo == "mes":
            agora_local_ranking = datetime.now(FUSO_LOCAL)
            inicio_periodo = agora_local_ranking.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ).astimezone(timezone.utc)

        usuarios = Usuario.query.filter(
            Usuario.is_admin.is_(False)
        ).order_by(
            Usuario.usuario.asc()
        ).all()

        ids_usuarios = [
            usuario.id
            for usuario in usuarios
        ]

        perfis_game = {}
        perfis_setor = {}

        if ids_usuarios:
            perfis_game = {
                perfil.usuario_id: perfil
                for perfil in PerfilGame.query.filter(
                    PerfilGame.usuario_id.in_(ids_usuarios)
                ).all()
            }

            perfis_setor = {
                perfil.usuario_id: perfil
                for perfil in PerfilSetor.query.filter(
                    PerfilSetor.usuario_id.in_(ids_usuarios)
                ).all()
            }

        consulta_lavagem = db.session.query(
            Operacao.usuario_id,
            func.count(Operacao.id),
        ).filter(
            Operacao.usuario_id.in_(ids_usuarios)
            if ids_usuarios
            else False
        )

        consulta_acao = db.session.query(
            ExtratoPonto.usuario_id,
            func.coalesce(
                func.sum(ExtratoPonto.pontos),
                0,
            ),
        ).filter(
            ExtratoPonto.usuario_id.in_(ids_usuarios)
            if ids_usuarios
            else False,
            ExtratoPonto.categoria == "acao",
        )

        consulta_desmanche = db.session.query(
            Desmanche.usuario_id,
            func.count(Desmanche.id),
        ).filter(
            Desmanche.usuario_id.in_(ids_usuarios)
            if ids_usuarios
            else False
        )

        if inicio_periodo is not None:
            consulta_lavagem = consulta_lavagem.filter(
                Operacao.criado_em >= inicio_periodo
            )

            consulta_acao = consulta_acao.filter(
                ExtratoPonto.criado_em >= inicio_periodo
            )

            consulta_desmanche = consulta_desmanche.filter(
                Desmanche.data_hora >= inicio_periodo
            )

        totais_lavagem = dict(
            consulta_lavagem.group_by(
                Operacao.usuario_id
            ).all()
        )

        totais_acao = dict(
            consulta_acao.group_by(
                ExtratoPonto.usuario_id
            ).all()
        )

        totais_desmanche = dict(
            consulta_desmanche.group_by(
                Desmanche.usuario_id
            ).all()
        )

        def linha_usuario(
            usuario,
            total,
        ):
            perfil_game = perfis_game.get(
                usuario.id
            )

            perfil_setor = perfis_setor.get(
                usuario.id
            )

            cargo_exibido = (
                usuario.cargo
            )

            return {
                "usuario_id": usuario.id,
                "usuario_site": usuario.usuario,
                "nome_game": (
                    perfil_game.nome_game
                    if perfil_game
                    else None
                ),
                "id_game": (
                    perfil_game.id_game
                    if perfil_game
                    else None
                ),
                "cargo": cargo_exibido,
                "total": int(
                    total
                    or 0
                ),
            }

        rankings = {
            "lavagem": [
                linha_usuario(
                    usuario,
                    totais_lavagem.get(
                        usuario.id,
                        0,
                    ),
                )
                for usuario in usuarios
            ],
            "acao": [
                linha_usuario(
                    usuario,
                    totais_acao.get(
                        usuario.id,
                        0,
                    ),
                )
                for usuario in usuarios
            ],
            "desmanche": [
                linha_usuario(
                    usuario,
                    totais_desmanche.get(
                        usuario.id,
                        0,
                    ),
                )
                for usuario in usuarios
            ],
        }

        for chave in rankings:
            rankings[chave].sort(
                key=lambda item: (
                    -item["total"],
                    (
                        item["nome_game"]
                        or item["usuario_site"]
                    ).lower(),
                )
            )

        def primeiro_com_resultado(lista):
            for item in lista:
                if item["total"] > 0:
                    return item
            return None

        top3 = [
            item
            for item in rankings[categoria]
            if item["total"] > 0
        ][:3]

        minha_posicao = None
        meu_total = 0

        for indice, item in enumerate(
            rankings[categoria],
            1,
        ):
            if item["usuario_id"] == current_user.id:
                minha_posicao = indice
                meu_total = item["total"]
                break

        return render_template(
            "ranking.html",
            ranking=rankings[categoria],
            categoria=categoria,
            periodo=periodo,
            top_lavagem=primeiro_com_resultado(
                rankings["lavagem"]
            ),
            top_acao=primeiro_com_resultado(
                rankings["acao"]
            ),
            top_desmanche=primeiro_com_resultado(
                rankings["desmanche"]
            ),
            top3=top3,
            minha_posicao=minha_posicao,
            meu_total=meu_total,
        )


    @app.route("/admin/solicitacao-perfil/<int:solicitacao_id>/<acao>", methods=["POST"])
    @login_required
    @admin_required
    def decidir_solicitacao_perfil(solicitacao_id, acao):
        solicitacao = db.session.get(SolicitacaoPerfilGame, solicitacao_id)
        if solicitacao is None:
            flash("Solicitação não encontrada.", "erro")
            return redirect(url_for("admin_dashboard"))
        if solicitacao.status != "pendente":
            flash("Esta solicitação já foi analisada.", "info")
            return redirect(url_for("admin_dashboard"))

        if acao not in {"aprovar", "recusar"}:
            flash("Ação administrativa inválida.", "erro")
            return redirect(url_for("admin_dashboard"))

        try:
            if acao == "aprovar":
                conflito = PerfilGame.query.filter(
                    PerfilGame.id_game == solicitacao.id_novo,
                    PerfilGame.usuario_id != solicitacao.usuario_id,
                ).first()
                if conflito:
                    flash("Não foi possível aprovar: o novo ID já pertence a outro membro.", "erro")
                    return redirect(url_for("admin_dashboard"))

                perfil_game = obter_perfil_game(solicitacao.usuario_id)
                if perfil_game is None:
                    perfil_game = PerfilGame(usuario_id=solicitacao.usuario_id)
                    db.session.add(perfil_game)
                perfil_game.nome_game = solicitacao.nome_novo
                perfil_game.id_game = solicitacao.id_novo
                solicitacao.status = "aprovada"
                solicitacao.motivo_recusa = None
            else:
                solicitacao.status = "recusada"
                solicitacao.motivo_recusa = limpar_texto(request.form.get("motivo"), 500) or "Alteração recusada pela administração."

            solicitacao.admin_id = current_user.id
            solicitacao.decidido_em = datetime.now(timezone.utc)

            registrar_log_admin(
                "PERFIL_GAME_APROVAR" if acao == "aprovar" else "PERFIL_GAME_RECUSAR",
                solicitacao.usuario_id,
                (
                    f"Nome/ID solicitado: {solicitacao.nome_novo} "
                    f"#{solicitacao.id_novo}. Decisão: {acao}."
                ),
            )

            criar_notificacao(
                solicitacao.usuario_id,
                "Alteração de Nome/ID Game",
                (
                    "Sua alteração de Nome/ID Game foi aprovada."
                    if acao == "aprovar"
                    else "Sua alteração de Nome/ID Game foi recusada."
                ),
                "sucesso" if acao == "aprovar" else "aviso",
            )

            db.session.commit()
            flash("Solicitação aprovada." if acao == "aprovar" else "Solicitação recusada.", "sucesso")
        except IntegrityError:
            db.session.rollback()
            flash("Não foi possível aprovar: o ID do game já está em uso.", "erro")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro ao decidir solicitação de perfil %s", solicitacao_id)
            flash("Não foi possível concluir a decisão.", "erro")

        return redirect(url_for("admin_dashboard"))


    @app.route("/notificacoes")
    @login_required
    def notificacoes():
        itens = Notificacao.query.filter_by(
            usuario_id=current_user.id
        ).order_by(
            Notificacao.criado_em.desc()
        ).limit(100).all()

        return render_template(
            "notificacoes.html",
            itens=itens,
        )


    @app.route("/notificacoes/marcar-lidas", methods=["POST"])
    @login_required
    def notificacoes_marcar_lidas():
        Notificacao.query.filter_by(
            usuario_id=current_user.id,
            lida=False,
        ).update(
            {"lida": True},
            synchronize_session=False,
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível atualizar as notificações.", "erro")
            return redirect(url_for("notificacoes"))

        flash("Notificações marcadas como lidas.", "sucesso")
        return redirect(url_for("notificacoes"))


    @app.route("/historico-geral/correcao", methods=["POST"])
    @login_required
    def solicitar_correcao_registro():
        registro_tipo = limpar_texto(
            request.form.get("registro_tipo"),
            30,
        ).lower()

        try:
            registro_id = int(
                request.form.get("registro_id")
                or 0
            )
        except (TypeError, ValueError):
            registro_id = 0

        motivo = limpar_texto(
            request.form.get("motivo"),
            1200,
        )

        if registro_tipo not in {"lavagem", "acao", "desmanche"}:
            flash("Tipo de registro inválido.", "erro")
            return redirect(url_for("historico_geral"))

        if registro_id <= 0 or not motivo:
            flash("Informe o registro e o motivo da correção.", "erro")
            return redirect(url_for("historico_geral"))

        # O usuário só pode pedir correção de registro próprio.
        modelo = {
            "lavagem": Operacao,
            "acao": Acao,
            "desmanche": Desmanche,
        }[registro_tipo]

        registro = modelo.query.filter_by(
            id=registro_id,
            usuario_id=current_user.id,
        ).first()

        if registro is None:
            flash("Registro não encontrado.", "erro")
            return redirect(url_for("historico_geral"))

        pendente = SolicitacaoCorrecao.query.filter_by(
            usuario_id=current_user.id,
            registro_tipo=registro_tipo,
            registro_id=registro_id,
            status="pendente",
        ).first()

        if pendente:
            flash("Já existe uma solicitação pendente para este registro.", "aviso")
            return redirect(url_for("historico_geral"))

        db.session.add(
            SolicitacaoCorrecao(
                usuario_id=current_user.id,
                registro_tipo=registro_tipo,
                registro_id=registro_id,
                motivo=motivo,
                status="pendente",
            )
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível enviar a solicitação.", "erro")
            return redirect(url_for("historico_geral"))

        # Avisar ADMs.
        for admin in Usuario.query.filter_by(is_admin=True, ativo=True).all():
            criar_notificacao(
                admin.id,
                "Nova solicitação de correção",
                f"{current_user.usuario} solicitou correção de um registro de {registro_tipo}.",
                "admin",
            )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()

        flash("Solicitação de correção enviada ao ADM.", "sucesso")
        return redirect(url_for("historico_geral"))


    @app.route("/admin/correcoes")
    @login_required
    @admin_required
    def admin_correcoes():
        status = limpar_texto(
            request.args.get("status", "pendente"),
            20,
        )
        if status not in {"pendente", "aprovada", "recusada", "todos"}:
            status = "pendente"

        consulta = SolicitacaoCorrecao.query

        if status != "todos":
            consulta = consulta.filter_by(
                status=status
            )

        solicitacoes = consulta.order_by(
            SolicitacaoCorrecao.solicitado_em.desc()
        ).limit(200).all()

        linhas = []
        for sol in solicitacoes:
            linhas.append({
                "solicitacao": sol,
                "usuario": db.session.get(Usuario, sol.usuario_id),
            })

        return render_template(
            "admin_correcoes.html",
            linhas=linhas,
            status=status,
        )


    @app.route(
        "/admin/correcoes/<int:solicitacao_id>/<acao>",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def admin_decidir_correcao(solicitacao_id, acao):
        if acao not in {"aprovar", "recusar"}:
            flash("Decisão inválida.", "erro")
            return redirect(url_for("admin_correcoes"))

        sol = db.session.get(
            SolicitacaoCorrecao,
            solicitacao_id,
        )

        if sol is None or sol.status != "pendente":
            flash("Solicitação não encontrada ou já decidida.", "erro")
            return redirect(url_for("admin_correcoes"))

        resposta = limpar_texto(
            request.form.get("resposta_admin"),
            1200,
        )

        sol.status = (
            "aprovada"
            if acao == "aprovar"
            else "recusada"
        )
        sol.admin_id = current_user.id
        sol.resposta_admin = resposta
        sol.decidido_em = datetime.now(timezone.utc)

        criar_notificacao(
            sol.usuario_id,
            "Solicitação de correção analisada",
            (
                f"Sua solicitação para {sol.registro_tipo} #{sol.registro_id} "
                f"foi {sol.status}."
                + (f" Resposta: {resposta}" if resposta else "")
            ),
            "sucesso" if acao == "aprovar" else "aviso",
        )

        registrar_log_admin(
            "CORRECAO_REGISTRO",
            sol.usuario_id,
            f"Solicitação #{sol.id} {sol.status}: {sol.registro_tipo} #{sol.registro_id}.",
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Não foi possível concluir a decisão.", "erro")
            return redirect(url_for("admin_correcoes"))

        flash("Solicitação atualizada.", "sucesso")
        return redirect(url_for("admin_correcoes"))


    @app.route("/admin/backup")
    @login_required
    @admin_required
    def admin_backup():
        """
        Exporta um snapshot JSON leve dos dados de gestão.
        Não inclui bytes de prints e não altera o banco.
        """
        from flask import make_response
        from decimal import Decimal as _Decimal

        def serializar(valor):
            if valor is None:
                return None
            if isinstance(valor, datetime):
                return valor.isoformat()
            if isinstance(valor, _Decimal):
                return str(valor)
            if isinstance(valor, (bytes, bytearray)):
                return None
            return valor

        tabelas = [
            Usuario,
            PerfilGame,
            PerfilSetor,
            Operacao,
            Acao,
            Desmanche,
            ExtratoPonto,
            AdvertenciaAdmin,
            SolicitacaoPerfilGame,
            SolicitacaoCorrecao,
            Notificacao,
            LogAdmin,
        ]

        dados = {
            "formato": "CHINA_PRO_BACKUP_V1",
            "gerado_em": datetime.now(timezone.utc).isoformat(),
            "tabelas": {},
        }

        for modelo in tabelas:
            linhas = []
            for obj in modelo.query.all():
                linha = {}
                for coluna in modelo.__table__.columns:
                    # Não exporta senha nem imagens/binários.
                    if coluna.name in {
                        "senha",
                        "print_envio_dados",
                        "print_recebimento_dados",
                    }:
                        continue
                    linha[coluna.name] = serializar(
                        getattr(obj, coluna.name)
                    )
                linhas.append(linha)

            dados["tabelas"][modelo.__tablename__] = linhas

        conteudo = json.dumps(
            dados,
            ensure_ascii=False,
            indent=2,
        )

        resposta = make_response(conteudo)
        resposta.headers["Content-Type"] = "application/json; charset=utf-8"
        resposta.headers["Content-Disposition"] = (
            "attachment; filename=china_pro_backup.json"
        )

        registrar_log_admin(
            "GERAR_BACKUP",
            detalhes="Backup JSON de gestão gerado.",
        )

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()

        return resposta


    @app.route("/historico-geral")
    @login_required
    def historico_geral():
        tipo = request.args.get("tipo", "todos")
        q = limpar(request.args.get("q"), 100).lower()

        itens = []

        if tipo in {"todos", "lavagem"}:
            consulta = Operacao.query.filter_by(usuario_id=current_user.id).order_by(
                Operacao.criado_em.desc()
            ).limit(80)
            for op in consulta:
                if q and q not in f"{op.nome_jogador} {op.id_jogador}".lower():
                    continue
                itens.append({
                    "tipo": "Lavagem",
                    "tipo_slug": "lavagem",
                    "registro_id": op.id,
                    "icone": "💰",
                    "titulo": f"{op.nome_jogador} #{op.id_jogador}",
                    "detalhe": f"R$ {float(op.valor):,.2f} • {abs(float(op.porcentagem)):.0f}%",
                    "data": op.criado_em,
                })

        if tipo in {"todos", "acao"}:
            consulta = Acao.query.filter_by(usuario_id=current_user.id).order_by(
                Acao.data_hora.desc()
            ).limit(80)
            for item in consulta:
                if q and q not in f"{item.tipo} {item.resultado} {item.responsavel}".lower():
                    continue
                itens.append({
                    "tipo": "Ação",
                    "tipo_slug": "acao",
                    "registro_id": item.id,
                    "icone": "🔫",
                    "titulo": f"{item.tipo} — {item.resultado}",
                    "detalhe": f"+{item.pontos} pts • {item.responsavel}",
                    "data": item.data_hora,
                })

        if tipo in {"todos", "desmanche"}:
            consulta = Desmanche.query.filter_by(usuario_id=current_user.id).order_by(
                Desmanche.data_hora.desc()
            ).limit(80)
            for item in consulta:
                if q and q not in item.modelo.lower():
                    continue
                itens.append({
                    "tipo": "Desmanche",
                    "tipo_slug": "desmanche",
                    "registro_id": item.id,
                    "icone": "🚗",
                    "titulo": item.modelo,
                    "detalhe": f"R$ {float(item.quantidade):,.2f} • +{item.pontos} {item.destino_pontos}",
                    "data": item.data_hora,
                })

        itens.sort(key=lambda item: item["data"], reverse=True)
        itens = itens[:100]

        return render_template(
            "historico_geral.html",
            itens=itens,
            tipo=tipo,
            q=q,
        )

