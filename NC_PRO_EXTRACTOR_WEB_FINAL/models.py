from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from extensions import db


# =========================================================
# HORÁRIO
# =========================================================

def agora_utc():
    return datetime.now(timezone.utc)


# =========================================================
# USUÁRIO
# =========================================================

class Usuario(
    db.Model,
    UserMixin,
):

    __tablename__ = "usuarios"

    __table_args__ = (
        Index(
            "ix_usuarios_usuario",
            "usuario",
        ),
    )


    id = db.Column(
        db.Integer,
        primary_key=True,
    )


    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )


    usuario = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
    )


    senha = db.Column(
        db.String(255),
        nullable=False,
    )


    cargo = db.Column(
        db.String(30),
        nullable=False,
        default="Funcionário",
    )


    ativo = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )


    is_admin = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
    )


    ultimo_login = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )


    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
    )


    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )


    configuracao = db.relationship(
        "ConfiguracaoUsuario",
        back_populates="usuario",
        uselist=False,
        cascade="all, delete-orphan",
    )

    logs = db.relationship(
        "LogAuditoria",
        back_populates="usuario",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    operacoes = db.relationship(
        "Operacao",
        back_populates="usuario",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


    def __repr__(self):
        return (
            f"<Usuario "
            f"id={self.id} "
            f"usuario={self.usuario}>"
        )


# =========================================================
# OPERAÇÃO OCR
# =========================================================

class Operacao(db.Model):

    __tablename__ = "operacoes"

    __table_args__ = (
        CheckConstraint(
            "valor > 0",
            name="ck_operacoes_valor_positivo",
        ),
        CheckConstraint(
            "porcentagem >= -40 "
            "AND porcentagem <= -20",
            name="ck_operacoes_porcentagem",
        ),
        Index(
            "ix_operacoes_usuario_data",
            "usuario_id",
            "criado_em",
        ),
        Index(
            "ix_operacoes_jogador",
            "id_jogador",
        ),
    )


    id = db.Column(
        db.Integer,
        primary_key=True,
    )


    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )


    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "usuarios.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )


    nome_jogador = db.Column(
        db.String(100),
        nullable=False,
    )


    id_jogador = db.Column(
        db.String(50),
        nullable=False,
    )


    valor = db.Column(
        db.Numeric(
            precision=18,
            scale=2,
            asdecimal=True,
        ),
        nullable=False,
        default=Decimal("0.00"),
    )


    porcentagem = db.Column(
        db.Numeric(
            precision=5,
            scale=2,
            asdecimal=True,
        ),
        nullable=False,
        default=Decimal("-20.00"),
    )


    valor_porcentagem = db.Column(
        db.Numeric(
            precision=18,
            scale=2,
            asdecimal=True,
        ),
        nullable=False,
        default=Decimal("0.00"),
    )


    valor_envio = db.Column(
        db.Numeric(
            precision=18,
            scale=2,
            asdecimal=True,
        ),
        nullable=True,
    )


    ocr_confianca = db.Column(
        db.Numeric(
            precision=5,
            scale=2,
            asdecimal=True,
        ),
        nullable=True,
    )


    leitura_ocr = db.Column(
        db.String(100),
        nullable=True,
    )


    status = db.Column(
        db.String(30),
        nullable=False,
        default="concluida",
    )


    observacoes = db.Column(
        db.Text,
        nullable=True,
    )


    # Mantidos por compatibilidade com versões anteriores.
    print_envio = db.Column(
        db.String(500),
        nullable=True,
    )

    print_recebimento = db.Column(
        db.String(500),
        nullable=True,
    )

    # Campos mantidos por compatibilidade. A UI atual não envia os prints ao servidor.
    print_envio_dados = db.Column(
        db.LargeBinary,
        nullable=True,
    )

    print_envio_mime = db.Column(
        db.String(80),
        nullable=True,
    )

    print_recebimento_dados = db.Column(
        db.LargeBinary,
        nullable=True,
    )

    print_recebimento_mime = db.Column(
        db.String(80),
        nullable=True,
    )


    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
    )


    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )


    usuario = db.relationship(
        "Usuario",
        back_populates="operacoes",
    )


    @property
    def data(self):
        """
        Mantém compatibilidade com os templates atuais,
        que ainda usam op.data.
        """

        return self.criado_em


    def __repr__(self):
        return (
            f"<Operacao "
            f"id={self.id} "
            f"jogador={self.nome_jogador} "
            f"valor={self.valor}>"
        )


# =========================================================
# CONFIGURAÇÃO DO USUÁRIO
# =========================================================

class ConfiguracaoUsuario(db.Model):

    __tablename__ = "configuracoes_usuario"

    __table_args__ = (
        UniqueConstraint(
            "usuario_id",
            name="uq_configuracoes_usuario_id",
        ),
    )


    id = db.Column(
        db.Integer,
        primary_key=True,
    )


    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "usuarios.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )


    porcentagem_padrao = db.Column(
        db.Numeric(
            precision=5,
            scale=2,
            asdecimal=True,
        ),
        nullable=False,
        default=Decimal("-20.00"),
    )


    tema = db.Column(
        db.String(30),
        nullable=False,
        default="escuro",
    )


    precisao_ocr = db.Column(
        db.String(30),
        nullable=False,
        default="alta",
    )


    salvar_prints = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )


    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
    )


    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )


    usuario = db.relationship(
        "Usuario",
        back_populates="configuracao",
    )


# =========================================================
# LOG DE AUDITORIA
# =========================================================

class LogAuditoria(db.Model):

    __tablename__ = "logs_auditoria"

    __table_args__ = (
        Index(
            "ix_logs_usuario_data",
            "usuario_id",
            "criado_em",
        ),
        Index(
            "ix_logs_acao",
            "acao",
        ),
    )


    id = db.Column(
        db.Integer,
        primary_key=True,
    )


    uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )


    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "usuarios.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )


    acao = db.Column(
        db.String(100),
        nullable=False,
    )


    entidade = db.Column(
        db.String(100),
        nullable=True,
    )


    entidade_id = db.Column(
        db.String(100),
        nullable=True,
    )


    detalhes = db.Column(
        db.Text,
        nullable=True,
    )


    endereco_ip = db.Column(
        db.String(100),
        nullable=True,
    )


    user_agent = db.Column(
        db.String(500),
        nullable=True,
    )


    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
    )


    usuario = db.relationship(
        "Usuario",
        back_populates="logs",
    )


    def __repr__(self):
        return (
            f"<LogAuditoria "
            f"id={self.id} "
            f"acao={self.acao}>"
        )

# =========================================================
# META SEMANAL DO USUÁRIO
# =========================================================

class MetaSemanalUsuario(db.Model):

    __tablename__ = "metas_semanais_usuario"

    __table_args__ = (
        UniqueConstraint(
            "usuario_id",
            "inicio_semana",
            name="uq_meta_usuario_semana",
        ),
        Index(
            "ix_meta_usuario_semana",
            "usuario_id",
            "inicio_semana",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    inicio_semana = db.Column(
        db.Date,
        nullable=False,
    )

    meta_entregue = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )

    impulsos = db.Column(db.Integer, nullable=False, default=0)

    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
    )

    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )

# =========================================================
# GESTÃO COMPLETA — AÇÃO, DESMANCHE E PONTOS
# =========================================================

class PerfilSetor(db.Model):
    __tablename__ = "perfis_setor"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    setor_lavagem = db.Column(db.Boolean, nullable=False, default=True)
    setor_acao = db.Column(db.Boolean, nullable=False, default=False)
    cargo_acao = db.Column(db.String(60), nullable=True)
    impulsos_acao = db.Column(db.Integer, nullable=False, default=0)
    impulsos_lavagem = db.Column(db.Integer, nullable=False, default=0)
    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )


class Acao(db.Model):
    __tablename__ = "acoes"

    __table_args__ = (
        UniqueConstraint("usuario_id", "fingerprint", name="uq_acao_usuario_fingerprint"),
        Index("ix_acoes_usuario_data", "usuario_id", "data_hora"),
        Index("ix_acoes_tipo_resultado", "tipo", "resultado"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo = db.Column(db.String(30), nullable=False)
    data_hora = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    participantes = db.Column(db.Text, nullable=False)
    responsavel = db.Column(db.String(120), nullable=False)
    resumo = db.Column(db.Text, nullable=False)
    resultado = db.Column(db.String(10), nullable=False)
    lucro = db.Column(db.Text, nullable=False, default="Nada")
    pontos = db.Column(db.Integer, nullable=False, default=0)
    prova_hash = db.Column(db.String(64), nullable=False)
    prova_nome = db.Column(db.String(255), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=agora_utc)


class Desmanche(db.Model):
    __tablename__ = "desmanches"

    __table_args__ = (
        UniqueConstraint("usuario_id", "fingerprint", name="uq_desmanche_usuario_fingerprint"),
        Index("ix_desmanches_usuario_data", "usuario_id", "data_hora"),
        Index("ix_desmanches_modelo", "modelo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    modelo = db.Column(db.String(100), nullable=False)
    data_hora = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    quantidade = db.Column(db.Numeric(18, 2, asdecimal=True), nullable=False, default=Decimal("0.00"))
    destino_pontos = db.Column(db.String(20), nullable=False)
    pontos = db.Column(db.Integer, nullable=False)
    prova_hash = db.Column(db.String(64), nullable=False)
    prova_nome = db.Column(db.String(255), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=agora_utc)


class ExtratoPonto(db.Model):
    __tablename__ = "extrato_pontos"

    __table_args__ = (
        UniqueConstraint("origem_tipo", "origem_id", "categoria", name="uq_ponto_origem_categoria"),
        Index("ix_pontos_usuario_categoria_data", "usuario_id", "categoria", "criado_em"),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origem_tipo = db.Column(db.String(20), nullable=False)
    origem_id = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(20), nullable=False)
    pontos = db.Column(db.Integer, nullable=False)
    descricao = db.Column(db.String(255), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=agora_utc)

# =========================================================
# PERFIL DO GAME + APROVAÇÃO ADMINISTRATIVA
# =========================================================

class PerfilGame(db.Model):
    __tablename__ = "perfis_game"

    __table_args__ = (
        UniqueConstraint("id_game", name="uq_perfil_game_id_game"),
        Index("ix_perfil_game_usuario", "usuario_id"),
        Index("ix_perfil_game_nome", "nome_game"),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    nome_game = db.Column(db.String(100), nullable=False)
    id_game = db.Column(db.String(30), nullable=False, unique=True)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=agora_utc)
    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        onupdate=agora_utc,
    )


class SolicitacaoPerfilGame(db.Model):
    __tablename__ = "solicitacoes_perfil_game"

    __table_args__ = (
        Index("ix_solicitacao_perfil_status_data", "status", "solicitado_em"),
        Index("ix_solicitacao_perfil_usuario", "usuario_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nome_atual = db.Column(db.String(100), nullable=True)
    id_atual = db.Column(db.String(30), nullable=True)
    nome_novo = db.Column(db.String(100), nullable=False)
    id_novo = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pendente", index=True)
    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    motivo_recusa = db.Column(db.String(500), nullable=True)
    solicitado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=agora_utc)
    decidido_em = db.Column(db.DateTime(timezone=True), nullable=True)



class LogAdmin(db.Model):
    __tablename__ = "logs_admin"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    alvo_usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    acao = db.Column(db.String(80), nullable=False, index=True)
    detalhes = db.Column(db.String(1000), nullable=True)
    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        index=True,
    )


class AdvertenciaAdmin(db.Model):
    __tablename__ = "advertencias_admin"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    motivo = db.Column(db.String(1000), nullable=False)
    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=agora_utc,
        index=True,
    )
    expira_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    removida = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    removida_por_admin_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    removida_em = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
    )
