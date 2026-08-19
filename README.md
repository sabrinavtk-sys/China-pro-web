# CHINA PRO EXTRACTOR — GESTÃO COMPLETA

Sistema web completo para Vercel + Neon.

## Módulos

- Lavagem com OCR
- Porcentagem automática
- Data e hora lidas do print
- Relatório em texto
- Ações com pontuação automática
- Desmanches
- Ranking
- Histórico Geral
- Histórico de Lavagem
- Setores e cargos
- Impulsos
- Metas
- Proteção contra duplicidade
- Extrato de pontos

## Otimização

Os prints usados pelo OCR não são armazenados permanentemente.

Lavagem:
- O print é processado no navegador.
- Os dados extraídos são enviados ao servidor.
- O arquivo original não é salvo no Neon.

Ações:
- 1 print final obrigatório.
- O navegador gera SHA-256.
- O arquivo não é enviado nem salvo.
- Apenas o hash é usado para validação e duplicidade.

Desmanches:
- 1 print obrigatório.
- O navegador gera SHA-256.
- O arquivo não é enviado nem salvo.

Isso reduz uso do Neon, evita payloads grandes e mantém o sistema leve.

## Pontuação de Ações

- Drop: Vitória +3 / Derrota +1
- Lojinha: Vitória +6 / Derrota +3
- Joalheria: Vitória +8 / Derrota +3
- Banco: Vitória +15 / Derrota +7
- Invasão: Vitória +12 / Derrota +5

## Desmanches

- Destino Ação: +2 pontos
- Destino Lavagem: +1 ponto

## Deploy — Vercel + Neon

Envie os arquivos diretamente para a raiz do repositório GitHub.

Na Vercel mantenha:

DATABASE_URL = connection string do Neon
SECRET_KEY = chave secreta
HTTPS = 1

A Vercel detecta Flask automaticamente.

As tabelas novas são criadas automaticamente pelo `db.create_all()` na inicialização.


## Conta administrativa

Configure na Vercel:

ADMIN_PASSWORD = uma senha forte para o admin
ADMIN_USER = admin  (opcional; se não informar, será "admin")

No próximo deploy, o sistema cria automaticamente a conta administrativa.

O admin acessa normalmente pela tela de login e verá o menu "Administração".


## UI China PRO 2026
Interface unificada preto/rosa/dourado aplicada a login, cadastro, dashboard e módulos de gestão. O Cassino da China aparece apenas como teaser bloqueado (Em breve), sem funcionalidade ativa.
