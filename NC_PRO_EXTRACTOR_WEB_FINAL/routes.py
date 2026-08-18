from functools import wraps
import hashlib
import re
import logging
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
from models import Acao, Desmanche, ExtratoPonto, MetaSemanalUsuario, Operacao, PerfilSetor, Usuario


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
    "Chefe de Setor",
    "Alto Conselho",
    "Sub Gerente",
]

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
    if usuario.cargo not in CARGOS:
        usuario.cargo = "Funcionário"
        return True
    return False


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
    registro, inicio_local, fim_local = obter_meta_semana(usuario.id, criar=True)

    inicio_utc = inicio_local.astimezone(timezone.utc)
    fim_utc = fim_local.astimezone(timezone.utc)

    lavagens = Operacao.query.filter(
        Operacao.usuario_id == usuario.id,
        Operacao.criado_em >= inicio_utc,
        Operacao.criado_em < fim_utc,
    ).count()

    meta = CARGOS.get(usuario.cargo)
    meta_entregue = bool(registro.meta_entregue)
    impulsos = registro.impulsos if registro.impulsos in (0,1,2) else 0
    meta_org = meta_organizacao(usuario.cargo, impulsos)

    if meta is None:
        faltam = 0
        percentual = 100
        apto = False
        status = "Possível convite para Gerência"
    else:
        faltam = max(meta - lavagens, 0)
        percentual = min(round((lavagens / meta) * 100), 100) if meta else 100
        apto = lavagens >= meta and meta_entregue
        if apto:
            status = "Apto para upamento"
        elif lavagens >= meta and not meta_entregue:
            status = "Quantidade atingida — falta entregar a meta"
        else:
            status = f"Faltam {faltam} lavagens"

    return {
        "cargo": usuario.cargo,
        "meta": meta,
        "lavagens": lavagens,
        "faltam": faltam,
        "percentual": percentual,
        "meta_entregue": meta_entregue,
        "impulsos": impulsos,
        "meta_org": meta_org,
        "funcao": FUNCOES_CARGOS.get(usuario.cargo, ""),
        "apto": apto,
        "status": status,
        "inicio": inicio_local,
        "fim_exclusivo": fim_local,
        "fim_exibicao": fim_local - timedelta(minutes=1),
    }



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

    @app.route("/")
    def inicio():
        return redirect(url_for("dashboard" if current_user.is_authenticated else "login"))

    @app.route("/cadastro", methods=["GET", "POST"])
    def cadastro():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "GET":
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO)

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

        if not usuario or not senha or not confirmar_senha or not setor_cadastro:
            return render_template(
                "cadastro.html",
                cargos_lavagem=ORDEM_CARGOS,
                cargos_acao=CARGOS_ACAO_CADASTRO,
                erro="Preencha todos os campos e selecione seu cargo atual.",
            )
        if len(usuario) < 3:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="O nome de usuário deve possuir pelo menos 3 caracteres.")
        if len(senha) < 6:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="A senha deve possuir pelo menos 6 caracteres.")
        if senha != confirmar_senha:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="As senhas não coincidem.")

        usuario_existente = Usuario.query.filter(func.lower(Usuario.usuario) == usuario.lower()).first()
        if usuario_existente:
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="Este usuário já existe.")

        novo_usuario = Usuario(
            usuario=usuario,
            senha=bcrypt.generate_password_hash(senha).decode("utf-8"),
            # Mantém compatibilidade com o sistema antigo de Lavagem.
            # Para contas de Ação, o cargo real fica em PerfilSetor.
            cargo=cargo_lavagem if setor_cadastro == "lavagem" else "Funcionário",
        )
        try:
            db.session.add(novo_usuario)
            db.session.flush()

            perfil = PerfilSetor(
                usuario_id=novo_usuario.id,
                setor_lavagem=(setor_cadastro == "lavagem"),
                setor_acao=(setor_cadastro == "acao"),
                cargo_acao=cargo_acao if setor_cadastro == "acao" else None,
                impulsos_acao=0,
                impulsos_lavagem=0,
            )
            db.session.add(perfil)

            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="Este usuário já existe.")
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Erro de banco ao cadastrar usuário.")
            return render_template("cadastro.html", cargos_lavagem=ORDEM_CARGOS, cargos_acao=CARGOS_ACAO_CADASTRO, erro="Não foi possível concluir o cadastro.")

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

        return render_template(
            "dashboard.html",
            total_operacoes=total_operacoes,
            valor_total=valor_total,
            lucro_total=ganhos_total,
            ultimas_operacoes=ultimas_operacoes,
            progresso=progresso,
            data_hoje=data_hoje,
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
                tzinfo=ZoneInfo(
                    "America/Sao_Paulo"
                )
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
        usuarios = Usuario.query.order_by(
            Usuario.usuario.asc()
        ).all()

        membros = []

        for usuario in usuarios:
            if getattr(usuario, "is_admin", False):
                continue

            perfil = PerfilSetor.query.filter_by(
                usuario_id=usuario.id
            ).first()

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

            membros.append({
                "usuario": usuario,
                "perfil": perfil,
                "lavagens": total_lavagens,
                "acoes": total_acoes,
                "desmanches": total_desmanches,
                "pontos_acao": int(pontos_acao or 0),
                "pontos_lavagem": int(pontos_lavagem or 0),
            })

        total_membros = len(membros)
        total_acoes_geral = Acao.query.count()
        total_desmanches_geral = Desmanche.query.count()
        total_lavagens_geral = Operacao.query.count()

        return render_template(
            "admin_dashboard.html",
            membros=membros,
            total_membros=total_membros,
            total_acoes_geral=total_acoes_geral,
            total_desmanches_geral=total_desmanches_geral,
            total_lavagens_geral=total_lavagens_geral,
        )


    @app.route("/admin/membro/<int:usuario_id>")
    @login_required
    @admin_required
    def admin_membro(usuario_id):
        usuario = db.session.get(
            Usuario,
            usuario_id
        )

        if usuario is None:
            flash("Membro não encontrado.", "erro")
            return redirect(url_for("admin_dashboard"))

        perfil = PerfilSetor.query.filter_by(
            usuario_id=usuario.id
        ).first()

        lavagens = Operacao.query.filter_by(
            usuario_id=usuario.id
        ).order_by(
            Operacao.criado_em.desc()
        ).limit(25).all()

        acoes = Acao.query.filter_by(
            usuario_id=usuario.id
        ).order_by(
            Acao.data_hora.desc()
        ).limit(25).all()

        desmanches = Desmanche.query.filter_by(
            usuario_id=usuario.id
        ).order_by(
            Desmanche.data_hora.desc()
        ).limit(25).all()

        extrato = ExtratoPonto.query.filter_by(
            usuario_id=usuario.id
        ).order_by(
            ExtratoPonto.criado_em.desc()
        ).limit(50).all()

        pontos_acao = sum(
            item.pontos
            for item in extrato
            if item.categoria == "acao"
        )

        pontos_lavagem = sum(
            item.pontos
            for item in extrato
            if item.categoria == "lavagem"
        )

        return render_template(
            "admin_membro.html",
            membro=usuario,
            perfil=perfil,
            lavagens=lavagens,
            acoes=acoes,
            desmanches=desmanches,
            extrato=extrato,
            pontos_acao=pontos_acao,
            pontos_lavagem=pontos_lavagem,
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
            cargo_novo = limpar_texto(request.form.get("cargo"), 30)
            meta_entregue = request.form.get("meta_entregue") == "1"
            try: impulsos = int(request.form.get("impulsos", "0"))
            except (TypeError, ValueError): impulsos = 0
            if impulsos not in (0,1,2): impulsos = 0

            if cargo_novo not in CARGOS:
                flash("Selecione um cargo válido.", "erro")
                return redirect(url_for("configuracoes"))

            cargo_anterior = current_user.cargo
            houve_promocao = (
                cargo_anterior in ORDEM_CARGOS
                and ORDEM_CARGOS.index(cargo_novo) > ORDEM_CARGOS.index(cargo_anterior)
            )

            try:
                current_user.cargo = cargo_novo
                registro_meta.meta_entregue = meta_entregue
                registro_meta.impulsos = impulsos
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception("Erro ao salvar configurações do usuário %s.", current_user.id)
                flash("Não foi possível salvar as configurações.", "erro")
                return redirect(url_for("configuracoes"))

            if houve_promocao:
                mensagem = MENSAGENS_PROMOCAO.get(cargo_novo, "Parabéns pela promoção! Continue evoluindo junto com sua equipe.")
                flash(f"🎉 {mensagem}", "promocao")
            else:
                flash("Configurações salvas com sucesso.", "sucesso")
            return redirect(url_for("dashboard" if houve_promocao else "configuracoes"))

        progresso = resumo_meta_semanal(current_user)
        return render_template(
            "configuracoes.html",
            cargos=ORDEM_CARGOS,
            metas=CARGOS,
            progresso=progresso,
        )

    @app.route("/historico")
    @login_required
    def historico():
        operacoes = Operacao.query.filter_by(usuario_id=current_user.id).order_by(Operacao.criado_em.desc(), Operacao.id.desc()).all()
        return render_template("historico.html", operacoes=operacoes)

    @app.route("/relatorios")
    @login_required
    def relatorios():
        filtro_usuario = Operacao.usuario_id == current_user.id
        resumo = db.session.query(
            func.count(Operacao.id),
            func.coalesce(func.sum(Operacao.valor), 0),
            func.coalesce(func.sum(Operacao.valor_porcentagem), 0),
        ).filter(filtro_usuario).one()
        jogadores = db.session.query(
            Operacao.nome_jogador,
            func.count(Operacao.id).label("total_operacoes"),
            func.coalesce(func.sum(Operacao.valor), 0).label("valor_total"),
            func.coalesce(func.sum(Operacao.valor_porcentagem), 0).label("ganhos_total"),
        ).filter(filtro_usuario).group_by(Operacao.nome_jogador).order_by(func.sum(Operacao.valor).desc()).all()
        return render_template(
            "relatorios.html",
            total_operacoes=resumo[0],
            valor_total=resumo[1],
            ganhos_total=resumo[2],
            jogadores=jogadores,
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
    "Chefe de Setor",
    "Alto Conselho",
    "Sub Gerente",
]

HIERARQUIA_ACAO = {cargo: indice for indice, cargo in enumerate(CARGOS_ACAO)}

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
            local = datetime.strptime(texto, formato).replace(tzinfo=FUSO_GESTAO)
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
    perfil = PerfilSetor.query.filter_by(usuario_id=usuario_id).first()
    if perfil is None and criar:
        perfil = PerfilSetor(
            usuario_id=usuario_id,
            setor_lavagem=True,
            setor_acao=False,
            impulsos_lavagem=0,
            impulsos_acao=0,
        )
        db.session.add(perfil)
        db.session.commit()
    return perfil


def inicio_semana():
    agora = datetime.now(FUSO_GESTAO)
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

        meta_acao = None
        if perfil.cargo_acao in METAS_ACAO:
            meta_acao = METAS_ACAO[perfil.cargo_acao][perfil.impulsos_acao if perfil.impulsos_acao in (0,1,2) else 0]

        return render_template(
            "gestao.html",
            perfil=perfil,
            pontos_acao=int(pontos_acao or 0),
            pontos_lavagem=int(pontos_lavagem or 0),
            meta_acao=meta_acao,
        )

    @app.route("/perfil-setores", methods=["GET", "POST"])
    @login_required
    def perfil_setores():
        perfil = obter_perfil(current_user.id)

        if request.method == "POST":
            perfil.setor_lavagem = request.form.get("setor_lavagem") == "on"
            perfil.setor_acao = request.form.get("setor_acao") == "on"

            cargo = limpar(request.form.get("cargo_acao"), 60)
            perfil.cargo_acao = cargo if cargo in CARGOS_ACAO else None

            try:
                perfil.impulsos_acao = max(0, min(2, int(request.form.get("impulsos_acao", 0))))
                perfil.impulsos_lavagem = max(0, min(2, int(request.form.get("impulsos_lavagem", 0))))
            except ValueError:
                perfil.impulsos_acao = 0
                perfil.impulsos_lavagem = 0

            if not perfil.setor_acao and not perfil.setor_lavagem:
                perfil.setor_lavagem = True

            db.session.commit()
            return redirect(url_for("gestao"))

        return render_template(
            "perfil_setores.html",
            perfil=perfil,
            cargos_acao=CARGOS_ACAO,
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
        dados = request.get_json(silent=True) or {}

        tipo = limpar(dados.get("tipo"), 30)
        resultado = limpar(dados.get("resultado"), 10)
        participantes = limpar(dados.get("participantes"), 5000)
        responsavel = limpar(dados.get("responsavel"), 120)
        resumo = limpar(dados.get("resumo"), 4000)
        lucro = limpar(dados.get("lucro"), 2000) or "Nada"
        prova_nome = limpar(dados.get("prova_nome"), 255)

        if tipo not in PONTOS_ACAO:
            return jsonify(sucesso=False, erro="Tipo de ação inválido."), 400
        if resultado not in {"Vitória", "Derrota"}:
            return jsonify(sucesso=False, erro="Informe Vitória ou Derrota."), 400
        if not participantes:
            return jsonify(sucesso=False, erro="Informe os participantes e cargos."), 400
        if not resumo:
            return jsonify(sucesso=False, erro="Informe um resumo da ação."), 400

        try:
            data_hora = parse_data_hora(dados.get("data_hora"))
            prova_hash = validar_hash(dados.get("prova_hash"))
        except ValueError as erro:
            return jsonify(sucesso=False, erro=str(erro)), 400

        if not responsavel:
            responsavel = sugerir_responsavel(participantes)
        if not responsavel:
            return jsonify(sucesso=False, erro="Informe o responsável oficial da ação."), 400

        pontos = PONTOS_ACAO[tipo][resultado]

        assinatura = fingerprint(
            current_user.id,
            tipo,
            data_hora.isoformat(),
            participantes,
            resultado,
            prova_hash,
        )

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

        try:
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
        except IntegrityError:
            db.session.rollback()
            return jsonify(
                sucesso=False,
                duplicado=True,
                erro="Esta ação parece já ter sido registrada. O salvamento foi bloqueado."
            ), 409
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(sucesso=False, erro="Não foi possível salvar a ação."), 500

        return jsonify(sucesso=True, pontos=pontos, id=acao.id)

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
        dados = request.get_json(silent=True) or {}
        modelo = limpar(dados.get("modelo"), 100)
        destino = limpar(dados.get("destino_pontos"), 20)
        prova_nome = limpar(dados.get("prova_nome"), 255)

        if not modelo:
            return jsonify(sucesso=False, erro="O modelo do veículo é obrigatório."), 400
        if destino not in {"acao", "lavagem"}:
            return jsonify(sucesso=False, erro="Escolha Ação ou Lavagem para receber os pontos."), 400

        try:
            data_hora = parse_data_hora(dados.get("data_hora"))
            quantidade = decimal_positivo(dados.get("quantidade"), "Quantidade recebida")
            prova_hash = validar_hash(dados.get("prova_hash"))
        except ValueError as erro:
            return jsonify(sucesso=False, erro=str(erro)), 400

        pontos = 2 if destino == "acao" else 1
        assinatura = fingerprint(
            current_user.id,
            modelo,
            data_hora.isoformat(),
            quantidade,
            destino,
            prova_hash,
        )

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

        try:
            db.session.add(registro)
            db.session.flush()
            db.session.add(ExtratoPonto(
                usuario_id=current_user.id,
                origem_tipo="desmanche",
                origem_id=registro.id,
                categoria=destino,
                pontos=pontos,
                descricao=f"Desmanche {modelo}",
                criado_em=data_hora,
            ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(
                sucesso=False,
                duplicado=True,
                erro="Este desmanche parece já ter sido registrado. O salvamento foi bloqueado."
            ), 409
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(sucesso=False, erro="Não foi possível salvar o desmanche."), 500

        return jsonify(sucesso=True, pontos=pontos, id=registro.id)

    @app.route("/ranking")
    @login_required
    def ranking():
        categoria = request.args.get("categoria", "acao")
        if categoria not in {"acao", "lavagem"}:
            categoria = "acao"

        periodo = request.args.get("periodo", "semana")
        filtros = [ExtratoPonto.categoria == categoria]
        if periodo == "semana":
            filtros.append(ExtratoPonto.criado_em >= inicio_semana())
        elif periodo == "mes":
            agora = datetime.now(FUSO_GESTAO)
            inicio_mes = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            filtros.append(ExtratoPonto.criado_em >= inicio_mes)

        ranking_rows = db.session.query(
            Usuario.usuario,
            func.coalesce(func.sum(ExtratoPonto.pontos), 0).label("total"),
        ).join(
            ExtratoPonto,
            ExtratoPonto.usuario_id == Usuario.id,
        ).filter(
            *filtros
        ).group_by(
            Usuario.id,
            Usuario.usuario,
        ).order_by(
            func.sum(ExtratoPonto.pontos).desc()
        ).limit(100).all()

        return render_template(
            "ranking.html",
            ranking=ranking_rows,
            categoria=categoria,
            periodo=periodo,
        )

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

