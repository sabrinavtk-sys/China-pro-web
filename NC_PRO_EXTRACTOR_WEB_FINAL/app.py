import logging
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import inspect, text

from config import Config

from extensions import (
    bcrypt,
    db,
    login_manager,
    migrate,
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)

def garantir_colunas_compatibilidade():
    insp = inspect(db.engine)

    if "usuarios" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("usuarios")}
        if "is_admin" not in cols:
            db.session.execute(text(
                "ALTER TABLE usuarios "
                "ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            db.session.commit()


    if "metas_semanais_usuario" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("metas_semanais_usuario")}
        if "impulsos" not in cols:
            db.session.execute(text(
                "ALTER TABLE metas_semanais_usuario "
                "ADD COLUMN impulsos INTEGER NOT NULL DEFAULT 0"
            ))
            db.session.commit()

    if "operacoes" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("operacoes")}
        faltantes = {
            "print_envio_dados": "BYTEA" if db.engine.dialect.name == "postgresql" else "BLOB",
            "print_envio_mime": "VARCHAR(80)",
            "print_recebimento_dados": "BYTEA" if db.engine.dialect.name == "postgresql" else "BLOB",
            "print_recebimento_mime": "VARCHAR(80)",
        }
        for nome, tipo in faltantes.items():
            if nome not in cols:
                db.session.execute(text(
                    f"ALTER TABLE operacoes ADD COLUMN {nome} {tipo}"
                ))
        db.session.commit()



def garantir_admin_inicial():
    """
    Compatibilidade opcional com ADMIN_USER / ADMIN_PASSWORD.

    Segurança:
    - se já existe qualquer administrador, não cria nem promove outra conta;
    - só funciona na instalação inicial, quando ainda há zero ADMs;
    - a forma recomendada continua sendo /primeiro-admin.
    """
    from models import Usuario

    admin_existente = Usuario.query.filter_by(
        is_admin=True
    ).first()

    if admin_existente is not None:
        return

    senha_admin = os.getenv(
        "ADMIN_PASSWORD",
        "",
    ).strip()

    if not senha_admin:
        logger.info(
            "Nenhum ADM automático configurado. "
            "Use /primeiro-admin para a configuração inicial."
        )
        return

    usuario_admin = (
        os.getenv(
            "ADMIN_USER",
            "admin",
        ).strip()
        or "admin"
    )

    conta_existente = Usuario.query.filter(
        db.func.lower(
            Usuario.usuario
        )
        == usuario_admin.lower()
    ).first()

    if conta_existente is not None:
        # Nunca transforma silenciosamente uma conta comum em ADM.
        logger.warning(
            "ADMIN_USER já pertence a uma conta comum. "
            "Promoção automática bloqueada por segurança."
        )
        return

    admin = Usuario(
        usuario=usuario_admin,
        senha=bcrypt.generate_password_hash(
            senha_admin
        ).decode("utf-8"),
        cargo="Funcionário",
        ativo=True,
        is_admin=True,
    )

    db.session.add(admin)
    db.session.commit()

    logger.info(
        "Conta administrativa inicial criada: %s",
        usuario_admin,
    )


def criar_app():

    app = Flask(__name__)

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
    )

    # =====================================================
    # CONFIGURAÇÕES
    # =====================================================

    app.config.from_object(
        Config
    )

    # =====================================================
    # EXTENSÕES
    # =====================================================

    db.init_app(
        app
    )

    bcrypt.init_app(
        app
    )

    login_manager.init_app(
        app
    )

    migrate.init_app(
        app,
        db,
    )

    # =====================================================
    # LOGIN MANAGER
    # =====================================================

    from models import Usuario

    @login_manager.user_loader
    def carregar_usuario(user_id):

        try:
            usuario_id = int(
                user_id
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        return db.session.get(
            Usuario,
            usuario_id,
        )

    @login_manager.unauthorized_handler
    def api_unauthorized():
        from flask import request, jsonify, redirect, url_for
        if request.path.startswith(("/acoes/", "/desmanches/", "/salvar-operacao")):
            return jsonify(
                sucesso=False,
                erro="Sua sessão expirou. Entre novamente no sistema.",
                codigo="SESSAO_EXPIRADA",
            ), 401
        return redirect(url_for("login"))

    # =====================================================
    # ROTAS
    # =====================================================

    from routes import configurar_rotas, configurar_rotas_gestao

    configurar_rotas(
        app
    )

    configurar_rotas_gestao(
        app
    )



    # =====================================================
    # ERROS DAS APIS — SEM HTML
    # =====================================================

    @app.errorhandler(404)
    def erro_404_api(erro):
        from flask import request, jsonify
        if request.path.startswith(("/desmanches/", "/acoes/", "/salvar-operacao")):
            return jsonify(
                sucesso=False,
                erro="Endpoint da API não encontrado.",
                codigo="API_404",
            ), 404
        return erro

    @app.errorhandler(405)
    def erro_405_api(erro):
        from flask import request, jsonify
        if request.path.startswith(("/desmanches/", "/acoes/", "/salvar-operacao")):
            return jsonify(
                sucesso=False,
                erro="Método não permitido nesta API.",
                codigo="API_405",
            ), 405
        return erro


    # =====================================================
    # BANCO / CACHE
    # =====================================================

    # Garante que uma instalação nova tenha as tabelas sem
    # depender de executar um comando manual antes do primeiro login.
    with app.app_context():
        db.create_all()
        garantir_colunas_compatibilidade()
        garantir_admin_inicial()

    @app.after_request
    def desabilitar_cache_dados_usuario(resposta):
        # Impede o navegador de reapresentar dashboard/histórico/relatórios
        # antigos ao trocar de conta, excluir registros ou usar Voltar.
        if resposta.content_type and "text/html" in resposta.content_type:
            resposta.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            resposta.headers["Pragma"] = "no-cache"
            resposta.headers["Expires"] = "0"
        return resposta

    logger.info(
        "Aplicação iniciada com sucesso."
    )

    return app


app = criar_app()


if __name__ == "__main__":

    print(
        "\n====== ROTAS ATIVAS ======"
    )

    for rota in app.url_map.iter_rules():

        print(
            rota.endpoint,
            "=>",
            rota,
        )

    print(
        "==========================\n"
    )

    porta = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=porta,
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )